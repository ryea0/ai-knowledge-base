"""LLM 供应商管理 REST API 路由。

提供供应商/模型的 CRUD、模型发现、连通性测试和健康状态管理接口。

路由前缀：``/llm``

端点总览：
    - ``GET    /llm/providers``                   -- 供应商列表（支持 type/enabled 筛选）
    - ``POST   /llm/providers``                   -- 创建供应商
    - ``GET    /llm/providers/{id}``              -- 供应商详情（含 models + health）
    - ``PATCH  /llm/providers/{id}``              -- 更新供应商
    - ``DELETE /llm/providers/{id}``              -- 软删除供应商
    - ``POST   /llm/providers/{id}/connectivity`` -- 连通性测试
    - ``GET    /llm/providers/{id}/models``       -- 模型列表
    - ``POST   /llm/providers/{id}/models``       -- 创建模型
    - ``PATCH  /llm/models/{id}``                 -- 更新模型
    - ``DELETE /llm/models/{id}``                 -- 软删除模型
    - ``POST   /llm/providers/{id}/discover``     -- 模型发现
    - ``POST   /llm/health/{model_id}/reset``     -- 重置模型健康状态
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.exceptions import BizException, ErrorCode
from src.common.response import Result
from src.config.database import get_db
from src.llm.connectivity import ConnectivityResult, test_connectivity
from src.llm.connectivity_service import scan_all_providers
from src.llm.health import reset_health
from src.llm.orm import LlmProvider
from src.llm.schemas import (
    DiscoveredModel,
    ModelCreate,
    ModelResponse,
    ModelUpdate,
    ProviderConnectivityResult,
    ProviderCreate,
    ProviderDetailResponse,
    ProviderResponse,
    ProviderUpdate,
)
from src.llm.service import (
    create_model,
    create_provider,
    delete_model,
    delete_provider,
    discover_models,
    get_provider_detail,
    list_models,
    list_providers,
    update_model,
    update_provider,
)
from src.models.enums import LlmProviderType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["LLM 供应商管理"])


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------


@router.get("/providers", summary="供应商列表")
def list_providers_api(
    db: Annotated[Session, Depends(get_db)],
    provider_type: Annotated[int | None, Query(description="供应商类型 0=cloud 1=local")] = None,
    is_enabled: Annotated[bool | None, Query(description="启用状态")] = None,
) -> Result[list[ProviderResponse]]:
    """查询供应商列表，支持按类型和启用状态筛选。"""
    pt = LlmProviderType(provider_type) if provider_type is not None else None
    data = list_providers(db, provider_type=pt, is_enabled=is_enabled)
    return Result.ok(data=data)


@router.post("/providers", summary="创建供应商")
def create_provider_api(
    db: Annotated[Session, Depends(get_db)],
    data: ProviderCreate,
) -> Result[ProviderResponse]:
    """创建供应商，校验 provider_code 唯一性。"""
    try:
        result = create_provider(db, data)
    except ValueError as exc:
        raise BizException(ErrorCode.PARAM_ERROR, str(exc)) from exc
    return Result.ok(data=result)


@router.get("/providers/connectivity", summary="查询供应商联通性状态")
def get_connectivity_api(
    db: Annotated[Session, Depends(get_db)],
) -> Result[list[ProviderConnectivityResult]]:
    """从 DB 读取所有供应商的最近联通性状态（不触发实时探测）。"""
    from src.llm.connectivity_service import get_connectivity_map

    rows = list(
        db.execute(
            select(LlmProvider).where(
                LlmProvider.is_deleted == False,  # noqa: E712
            ).order_by(LlmProvider.priority, LlmProvider.id)
        ).scalars().all()
    )
    provider_ids = [p.id for p in rows]
    conn_map = get_connectivity_map(db, provider_ids)
    results: list[ProviderConnectivityResult] = []
    for p in rows:
        conn = conn_map.get(p.id)
        results.append(
            ProviderConnectivityResult(
                provider_id=p.id,
                success=conn.is_connected if conn else False,
                latency_ms=conn.latency_ms if conn else None,
                error=conn.last_error if conn else None,
                last_check_at=conn.last_check_at if conn else None,
            )
        )
    return Result.ok(data=results)


@router.get("/providers/{provider_id}", summary="供应商详情")
def get_provider_detail_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
) -> Result[ProviderDetailResponse]:
    """查询供应商详情（含关联模型列表和健康状态）。"""
    result = get_provider_detail(db, provider_id)
    if result is None:
        raise BizException(ErrorCode.NOT_FOUND, f"供应商 {provider_id} 不存在")
    return Result.ok(data=result)


@router.patch("/providers/{provider_id}", summary="更新供应商")
def update_provider_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
    data: ProviderUpdate,
) -> Result[ProviderResponse]:
    """更新供应商信息。"""
    try:
        result = update_provider(db, provider_id, data)
    except ValueError as exc:
        raise BizException(ErrorCode.NOT_FOUND, str(exc)) from exc
    return Result.ok(data=result)


@router.delete("/providers/{provider_id}", summary="删除供应商")
def delete_provider_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
) -> Result[None]:
    """软删除供应商。"""
    try:
        delete_provider(db, provider_id)
    except ValueError as exc:
        raise BizException(ErrorCode.NOT_FOUND, str(exc)) from exc
    return Result.ok(data=None, message="删除成功")


# ---------------------------------------------------------------------------
# Connectivity Test
# ---------------------------------------------------------------------------


@router.post("/providers/{provider_id}/connectivity", summary="连通性测试")
def test_connectivity_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
) -> Result[ConnectivityResult]:
    """测试供应商连通性，按 litellm_provider 分派到不同探测端点。"""
    provider = db.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        raise BizException(ErrorCode.NOT_FOUND, f"供应商 {provider_id} 不存在")

    result = test_connectivity(provider)
    return Result.ok(data=result)


@router.post("/providers/batch-connectivity", summary="批量连通性测试")
def batch_connectivity_api(
    db: Annotated[Session, Depends(get_db)],
) -> Result[list[ProviderConnectivityResult]]:
    """对所有未软删除供应商执行连通性测试，持久化结果并返回每条结果。"""
    results = scan_all_providers(db)
    return Result.ok(data=results)


# ---------------------------------------------------------------------------
# Model CRUD
# ---------------------------------------------------------------------------


@router.get("/providers/{provider_id}/models", summary="模型列表")
def list_models_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
) -> Result[list[ModelResponse]]:
    """查询指定供应商的所有模型。"""
    data = list_models(db, provider_id)
    return Result.ok(data=data)


@router.post("/providers/{provider_id}/models", summary="创建模型")
def create_model_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
    data: ModelCreate,
) -> Result[ModelResponse]:
    """在指定供应商下创建模型。"""
    try:
        result = create_model(db, provider_id, data)
    except ValueError as exc:
        raise BizException(ErrorCode.PARAM_ERROR, str(exc)) from exc
    return Result.ok(data=result)


@router.patch("/models/{model_id}", summary="更新模型")
def update_model_api(
    db: Annotated[Session, Depends(get_db)],
    model_id: int,
    data: ModelUpdate,
) -> Result[ModelResponse]:
    """更新模型信息。"""
    try:
        result = update_model(db, model_id, data)
    except ValueError as exc:
        raise BizException(ErrorCode.NOT_FOUND, str(exc)) from exc
    return Result.ok(data=result)


@router.delete("/models/{model_id}", summary="删除模型")
def delete_model_api(
    db: Annotated[Session, Depends(get_db)],
    model_id: int,
) -> Result[None]:
    """软删除模型。"""
    try:
        delete_model(db, model_id)
    except ValueError as exc:
        raise BizException(ErrorCode.NOT_FOUND, str(exc)) from exc
    return Result.ok(data=None, message="删除成功")


# ---------------------------------------------------------------------------
# Model Discovery
# ---------------------------------------------------------------------------


@router.post("/providers/{provider_id}/discover", summary="模型发现")
def discover_models_api(
    db: Annotated[Session, Depends(get_db)],
    provider_id: int,
) -> Result[list[DiscoveredModel]]:
    """通过供应商 API 自动发现可用模型。"""
    try:
        result = discover_models(db, provider_id)
    except ValueError as exc:
        raise BizException(ErrorCode.NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise BizException(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    return Result.ok(data=result)


# ---------------------------------------------------------------------------
# Health Management
# ---------------------------------------------------------------------------


@router.post("/health/{model_id}/reset", summary="重置模型健康状态")
def reset_health_api(
    db: Annotated[Session, Depends(get_db)],
    model_id: int,
) -> Result[None]:
    """重置模型健康状态为 unknown。"""
    reset_health(db, model_id)
    return Result.ok(data=None, message="健康状态已重置")
