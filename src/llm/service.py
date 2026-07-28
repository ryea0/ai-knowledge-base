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
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.crypto import encrypt
from src.llm.orm import LlmModel, LlmProvider
from src.llm.schemas import (
    DiscoveredModel,
    ModelCreate,
    ModelResponse,
    ModelUpdate,
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)
from src.models.enums import LlmAuthType, LlmModelSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------


def create_provider(
    session: Session, data: ProviderCreate
) -> ProviderResponse:
    """创建供应商。

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
    if data.auth_type != LlmAuthType.NONE and data.api_key:
        encrypted_key = encrypt(data.api_key)

    provider = LlmProvider(
        provider_code=data.provider_code,
        display_name=data.display_name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        litellm_provider=data.litellm_provider,
        auth_type=data.auth_type,
        api_key_encrypted=encrypted_key,
        auth_config=data.auth_config,
        is_enabled=data.is_enabled,
        priority=data.priority,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
        rpm_limit=data.rpm_limit,
        health_check_enabled=data.health_check_enabled,
        failure_threshold=data.failure_threshold,
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


def list_providers(session: Session) -> list[ProviderResponse]:
    """查询所有供应商（不含软删除），按优先级排序。"""
    stmt = (
        select(LlmProvider)
        .where(LlmProvider.is_deleted == False)  # noqa: E712
        .order_by(LlmProvider.priority, LlmProvider.id)
    )
    providers = list(session.execute(stmt).scalars().all())
    return [ProviderResponse.model_validate(p) for p in providers]


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

    # 单独处理 api_key：非 None 则加密存储
    api_key = update_fields.pop("api_key", None)
    if api_key is not None:
        provider.api_key_encrypted = encrypt(api_key)

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
        input_price_per_1m=data.input_price_per_1m,
        output_price_per_1m=data.output_price_per_1m,
        is_enabled=data.is_enabled,
        is_default=data.is_default,
        source=LlmModelSource.MANUAL,
    )
    session.add(model)
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

    # Step 1: 调用 /v1/models
    headers: dict[str, str] = {"Accept": "application/json"}

    if provider.api_key_encrypted:
        from src.llm.crypto import decrypt

        api_key = decrypt(provider.api_key_encrypted)
        if provider.auth_type == LlmAuthType.HEADER:
            header_name = (
                provider.auth_config.get("header_name", "x-api-key")
                if provider.auth_config
                else "x-api-key"
            )
            headers[header_name] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    url = provider.base_url.rstrip("/") + "/models"

    try:
        resp = httpx.get(url, headers=headers, timeout=provider.timeout_seconds)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("供应商 %s 模型发现失败: %s", provider.provider_code, exc)
        raise RuntimeError(
            f"无法获取供应商 {provider.provider_code} 的模型列表: {exc}"
        ) from exc

    raw_models: list[dict[str, Any]] = resp.json().get("data", [])

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

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        exclude_id: 排除的模型 ID（不清除该模型的 default 标记）。
    """
    stmt = select(LlmModel).where(
        LlmModel.provider_id == provider_id,
        LlmModel.is_default == True,  # noqa: E712
        LlmModel.is_deleted == False,  # noqa: E712
    )
    if exclude_id is not None:
        stmt = stmt.where(LlmModel.id != exclude_id)

    for model in session.execute(stmt).scalars().all():
        model.is_default = False
