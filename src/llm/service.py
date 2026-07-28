"""LLM 供应商管理服务层。

提供供应商/模型的 CRUD 操作和模型自动发现功能。
作为前端 API 层和 ORM 层之间的业务逻辑层。

事务约定：
    本模块所有函数**不调用** ``session.commit()``，仅执行 ``session.flush()``
    以获取自增主键。事务提交/回滚由调用方控制（``session_scope`` 或 FastAPI
    ``get_db`` 依赖），确保多操作可组合在同一事务中。

模型发现流程（``discover_models``）：
    1. 调用 ``GET {base_url}/models`` 获取模型 ID 列表。
    2. 交叉 LiteLLM 注册表补全能力/定价元数据。
    3. 与 DB 已有模型比对去重。
    4. 返回候选列表，由前端用户勾选后批量创建。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.llm.auth_adapter import build_auth_context, build_httpx_headers
from src.llm.connectivity import build_openai_models_url
from src.llm.connectivity_service import get_connectivity_map
from src.llm.crypto import encrypt
from src.llm.orm import LlmHealth, LlmModel, LlmProvider, LlmProviderConnectivity
from src.llm.schemas import (
    DiscoveredModel,
    HealthResponse,
    ModelCreate,
    ModelResponse,
    ModelUpdate,
    ProviderCreate,
    ProviderDetailResponse,
    ProviderResponse,
    ProviderUpdate,
)
from src.models.enums import LlmAuthType, LlmHealthStatus, LlmModelSource, LlmProviderType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------


def create_provider(
    session: Session, data: ProviderCreate
) -> ProviderResponse:
    """创建供应商。

    校验 ``provider_code`` 唯一性（未软删除范围内）。
    若 ``auth_type`` 非 none 且 ``data.api_key`` 不为空，则加密存储。
    事务由调用方管理（``session_scope`` 或 ``get_db``），本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        data: 供应商创建数据。

    Returns:
        创建后的供应商响应（不含 API Key）。

    Raises:
        ValueError: provider_code 已存在。
    """
    existing = session.execute(
        select(LlmProvider).where(
            LlmProvider.provider_code == data.provider_code,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if existing is not None:
        raise ValueError(f"供应商代码 {data.provider_code} 已存在")

    encrypted_key: str | None = None
    encrypted_secret: str | None = None

    if data.auth_type != LlmAuthType.NONE and data.api_key:
        encrypted_key = encrypt(data.api_key)

    if data.auth_type == LlmAuthType.OAUTH and data.secret_key:
        encrypted_secret = encrypt(data.secret_key)

    provider = LlmProvider(
        provider_code=data.provider_code,
        display_name=data.display_name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        litellm_provider=data.litellm_provider,
        auth_type=data.auth_type,
        api_key_encrypted=encrypted_key,
        secret_key_encrypted=encrypted_secret,
        header_name=data.header_name if data.auth_type == LlmAuthType.HEADER else None,
        token_url=data.token_url if data.auth_type == LlmAuthType.OAUTH else None,
        is_enabled=data.is_enabled,
        priority=data.priority,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
        rpm_limit=data.rpm_limit,
    )
    session.add(provider)
    session.flush()

    logger.info("创建供应商: %s (id=%d)", provider.provider_code, provider.id)
    return ProviderResponse.model_validate(provider)


def get_provider(session: Session, provider_id: int) -> ProviderResponse | None:
    """查询单个供应商。"""
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        return None
    return ProviderResponse.model_validate(provider)


def get_provider_detail(
    session: Session, provider_id: int
) -> ProviderDetailResponse | None:
    """查询供应商详情（含关联模型列表和健康状态）。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。

    Returns:
        供应商详情（含 models + health_list），不存在则返回 None。
    """
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        return None

    models = list(
        session.execute(
            select(LlmModel)
            .where(
                LlmModel.provider_id == provider_id,
                LlmModel.is_deleted == False,  # noqa: E712
            )
            .order_by(LlmModel.is_default.desc(), LlmModel.id)
        ).scalars().all()
    )

    health_list = list(
        session.execute(
            select(LlmHealth)
            .where(
                LlmHealth.provider_id == provider_id,
                LlmHealth.is_deleted == False,  # noqa: E712
            )
            .order_by(LlmHealth.model_id)
        ).scalars().all()
    )

    conn_map = get_connectivity_map(session, [provider_id])
    response = ProviderDetailResponse(
        **ProviderResponse.model_validate(provider).model_dump(),
        models=[ModelResponse.model_validate(m) for m in models],
        health_list=[HealthResponse.model_validate(h) for h in health_list],
    )
    response.connectivity = conn_map.get(provider_id)
    return response


def list_providers(
    session: Session,
    *,
    provider_type: LlmProviderType | None = None,
    is_enabled: bool | None = None,
) -> list[ProviderResponse]:
    """查询供应商列表（不含软删除），按优先级排序。

    同时填充 ``model_count``（未软删除模型数）。

    Args:
        session: SQLAlchemy Session。
        provider_type: 按供应商类型筛选（cloud / local），None 不筛选。
        is_enabled: 按启用状态筛选，None 不筛选。

    Returns:
        供应商响应列表。
    """
    stmt = select(LlmProvider).where(
        LlmProvider.is_deleted == False  # noqa: E712
    )

    if provider_type is not None:
        stmt = stmt.where(LlmProvider.provider_type == provider_type)

    if is_enabled is not None:
        stmt = stmt.where(LlmProvider.is_enabled == is_enabled)

    stmt = stmt.order_by(LlmProvider.priority, LlmProvider.id)

    providers = list(session.execute(stmt).scalars().all())
    responses = [ProviderResponse.model_validate(p) for p in providers]
    if not responses:
        return responses

    provider_ids = [r.id for r in responses]
    count_rows = session.execute(
        select(
            LlmModel.provider_id,
            func.count(LlmModel.id).label("cnt"),
        )
        .where(
            LlmModel.provider_id.in_(provider_ids),
            LlmModel.is_deleted == False,  # noqa: E712
        )
        .group_by(LlmModel.provider_id)
    ).all()
    counts: dict[int, int] = {pid: cnt for pid, cnt in count_rows}
    for r in responses:
        r.model_count = counts.get(r.id, 0)

    # 填充联通性状态（从 DB 读取，非实时探测）
    conn_map = get_connectivity_map(session, provider_ids)
    for r in responses:
        r.connectivity = conn_map.get(r.id)
    return responses


def update_provider(
    session: Session, provider_id: int, data: ProviderUpdate
) -> ProviderResponse:
    """更新供应商。

    ``data.api_key`` 非 None 时更新加密凭证，None 表示不修改。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        data: 更新数据。

    Returns:
        更新后的供应商响应。

    Raises:
        ValueError: 供应商不存在。
    """
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        raise ValueError(f"供应商 {provider_id} 不存在")

    update_fields = data.model_dump(exclude_unset=True, exclude_none=True)

    # 单独处理凭证字段：非 None 则加密存储
    api_key = update_fields.pop("api_key", None)
    if api_key is not None:
        provider.api_key_encrypted = encrypt(api_key)

    secret_key = update_fields.pop("secret_key", None)
    if secret_key is not None:
        provider.secret_key_encrypted = encrypt(secret_key)

    for field, value in update_fields.items():
        setattr(provider, field, value)

    session.flush()

    logger.info("更新供应商: %s (id=%d)", provider.provider_code, provider.id)
    return ProviderResponse.model_validate(provider)


def delete_provider(session: Session, provider_id: int) -> None:
    """软删除供应商（设 is_deleted=1 + deleted_at）。

    不物理删除，保留历史健康日志的引用完整性。
    软删除后 provider_code 唯一约束释放（guard 列变 NULL），可重建同名供应商。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。

    Raises:
        ValueError: 供应商不存在。
    """
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        raise ValueError(f"供应商 {provider_id} 不存在")

    provider.is_deleted = True
    provider.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    provider.is_enabled = False
    session.flush()

    # 同步软删除供应商联通性行
    conn = session.execute(
        select(LlmProviderConnectivity).where(
            LlmProviderConnectivity.provider_id == provider_id,
            LlmProviderConnectivity.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if conn is not None:
        conn.is_deleted = True
        conn.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush()

    logger.info("软删除供应商: %s (id=%d)", provider.provider_code, provider.id)


# ---------------------------------------------------------------------------
# Model CRUD
# ---------------------------------------------------------------------------


def create_model(
    session: Session, provider_id: int, data: ModelCreate
) -> ModelResponse:
    """在指定供应商下创建模型。

    若 ``is_default=True``，会先清除该供应商其他模型的 default 标记。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        data: 模型创建数据。

    Returns:
        创建后的模型响应。

    Raises:
        ValueError: 供应商不存在，或 model_code 已存在。
    """
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        raise ValueError(f"供应商 {provider_id} 不存在")

    existing = session.execute(
        select(LlmModel).where(
            LlmModel.provider_id == provider_id,
            LlmModel.model_code == data.model_code,
            LlmModel.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if existing is not None:
        raise ValueError(
            f"模型 {data.model_code} 在供应商 {provider_id} 下已存在"
        )

    # 若设为默认，先清除同供应商其他默认模型
    if data.is_default:
        _clear_default_model(session, provider_id)
        session.flush()

    model = LlmModel(
        provider_id=provider_id,
        model_code=data.model_code,
        litellm_model=data.litellm_model,
        display_name=data.display_name,
        description=data.description,
        context_window=data.context_window,
        max_output_tokens=data.max_output_tokens,
        supports_streaming=data.supports_streaming,
        supports_function_calling=data.supports_function_calling,
        supports_vision=data.supports_vision,
        supports_reasoning=data.supports_reasoning,
        input_price_per_1m=data.input_price_per_1m,
        output_price_per_1m=data.output_price_per_1m,
        is_enabled=data.is_enabled,
        is_default=data.is_default,
        source=LlmModelSource.MANUAL,
    )
    session.add(model)
    session.flush()

    # 自动创建模型健康状态行（health_status=unknown）
    health = LlmHealth(
        provider_id=provider_id,
        model_id=model.id,
        health_status=LlmHealthStatus.UNKNOWN,
    )
    session.add(health)
    session.flush()

    logger.info(
        "创建模型: %s (provider=%s, id=%d)",
        model.model_code,
        provider.provider_code,
        model.id,
    )
    return ModelResponse.model_validate(model)


def list_models(
    session: Session, provider_id: int
) -> list[ModelResponse]:
    """查询指定供应商的所有模型（不含软删除）。"""
    stmt = (
        select(LlmModel)
        .where(
            LlmModel.provider_id == provider_id,
            LlmModel.is_deleted == False,  # noqa: E712
        )
        .order_by(LlmModel.is_default.desc(), LlmModel.id)
    )
    models = list(session.execute(stmt).scalars().all())
    return [ModelResponse.model_validate(m) for m in models]


def update_model(
    session: Session, model_id: int, data: ModelUpdate
) -> ModelResponse:
    """更新模型。

    若 ``is_default=True``，会先清除同供应商其他模型的 default 标记。

    Args:
        session: SQLAlchemy Session。
        model_id: 模型 ID。
        data: 更新数据。

    Raises:
        ValueError: 模型不存在。
    """
    model = session.execute(
        select(LlmModel).where(
            LlmModel.id == model_id,
            LlmModel.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if model is None:
        raise ValueError(f"模型 {model_id} 不存在")

    update_fields = data.model_dump(exclude_unset=True, exclude_none=True)

    if update_fields.get("is_default"):
        _clear_default_model(session, model.provider_id, exclude_id=model_id)
        session.flush()

    for field, value in update_fields.items():
        setattr(model, field, value)

    session.flush()

    logger.info("更新模型: %s (id=%d)", model.model_code, model.id)
    return ModelResponse.model_validate(model)


def delete_model(session: Session, model_id: int) -> None:
    """软删除模型（设 is_deleted=1 + deleted_at）。

    不物理删除，保留历史健康日志的引用完整性。
    软删除后 (provider_id, model_code) 唯一约束释放，可重建同名模型。

    Args:
        session: SQLAlchemy Session。
        model_id: 模型 ID。

    Raises:
        ValueError: 模型不存在。
    """
    model = session.execute(
        select(LlmModel).where(
            LlmModel.id == model_id,
            LlmModel.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if model is None:
        raise ValueError(f"模型 {model_id} 不存在")

    model.is_deleted = True
    model.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    model.is_enabled = False
    session.flush()

    # 同步软删除对应的健康状态行
    health = session.execute(
        select(LlmHealth).where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if health is not None:
        health.is_deleted = True
        health.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush()

    logger.info("软删除模型: id=%d", model_id)


# ---------------------------------------------------------------------------
# Model Discovery
# ---------------------------------------------------------------------------


def discover_models(
    session: Session, provider_id: int
) -> list[DiscoveredModel]:
    """通过 ``GET {base_url}/models`` 自动发现可用模型。

    流程：
        1. 调用供应商的 ``/models`` 端点获取模型 ID 列表。
        2. 交叉 LiteLLM 注册表补全 context_window / pricing / capabilities。
        3. 与 DB 已有模型比对，标记 ``already_exists``。
        4. 返回候选列表（不直接写 DB，由前端用户勾选后调用 :func:`create_model`）。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。

    Returns:
        发现的候选模型列表。

    Raises:
        ValueError: 供应商不存在。
        RuntimeError: 无法连接供应商 API。
    """
    provider = session.execute(
        select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        raise ValueError(f"供应商 {provider_id} 不存在")

    # Step 1: 按 litellm_provider 分派到不同端点
    ctx = build_auth_context(provider)
    headers = build_httpx_headers(ctx)

    if provider.litellm_provider == "ollama":
        url = provider.base_url.rstrip("/") + "/api/tags"
    else:
        url = build_openai_models_url(provider.base_url)

    try:
        resp = httpx.get(url, headers=headers, timeout=provider.timeout_seconds)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("供应商 %s 模型发现失败: %s", provider.provider_code, exc)
        raise RuntimeError(
            f"无法获取供应商 {provider.provider_code} 的模型列表: {exc}"
        ) from exc

    body = resp.json()
    if provider.litellm_provider == "ollama":
        raw_models = [
            {"id": m.get("model", m.get("name", ""))}
            for m in body.get("models", [])
        ]
    else:
        raw_models = body.get("data", [])

    # Step 2: 查 DB 已有 model_code（不含软删除）
    existing_codes: set[str] = set(
        session.execute(
            select(LlmModel.model_code).where(
                LlmModel.provider_id == provider_id,
                LlmModel.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
    )

    # Step 3: 交叉 LiteLLM 注册表
    try:
        import litellm

        litellm_registry: dict[str, Any] = getattr(litellm, "model_cost", {})
    except ImportError:
        litellm_registry = {}
    except Exception:
        litellm_registry = {}

    results: list[DiscoveredModel] = []

    for raw in raw_models:
        model_id_str = raw.get("id", "")
        if not model_id_str:
            continue

        litellm_model_str = f"{provider.litellm_provider}/{model_id_str}"
        already_exists = model_id_str in existing_codes

        # 尝试从 LiteLLM 注册表补全元数据
        info = litellm_registry.get(litellm_model_str, {})

        # 也尝试不带 provider 前缀的查找
        if not info:
            info = litellm_registry.get(model_id_str, {})

        results.append(
            DiscoveredModel(
                model_code=model_id_str,
                litellm_model=litellm_model_str,
                display_name=model_id_str,
                context_window=info.get("max_input_tokens", 4096),
                max_output_tokens=info.get("max_output_tokens", 4096),
                supports_streaming=info.get("supports_streaming", True),
                supports_function_calling=info.get(
                    "supports_function_calling", False
                ),
                supports_vision=info.get("supports_vision", False),
                supports_reasoning=info.get("supports_reasoning", False),
                input_price_per_1m=info.get("input_cost_per_token", 0.0)
                * 1_000_000,
                output_price_per_1m=info.get("output_cost_per_token", 0.0)
                * 1_000_000,
                already_exists=already_exists,
            )
        )

    logger.info(
        "供应商 %s 发现 %d 个模型，其中 %d 个已存在",
        provider.provider_code,
        len(results),
        sum(1 for r in results if r.already_exists),
    )
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_default_model(
    session: Session, provider_id: int, *, exclude_id: int | None = None
) -> None:
    """清除指定供应商下其他模型的 is_default 标记。

    使用单条 ``UPDATE ... SET is_default=0`` 批量清除，
    避免逐行 Python 更新。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        exclude_id: 排除的模型 ID（不清除该模型的 default 标记）。
    """
    stmt = (
        update(LlmModel)
        .where(
            LlmModel.provider_id == provider_id,
            LlmModel.is_default == True,  # noqa: E712
            LlmModel.is_deleted == False,  # noqa: E712
        )
        .values(is_default=False)
    )
    if exclude_id is not None:
        stmt = stmt.where(LlmModel.id != exclude_id)

    session.execute(stmt)
