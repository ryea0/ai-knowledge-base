"""LLM 供应商路由模块。

按优先级 + 模型健康状态选择可用供应商和模型。
支持 fallback 链：首选供应商的默认模型不可用时自动降级到次优。

路由查询逻辑：
    1. 筛选 ``is_enabled=1`` 且 ``is_deleted=0`` 的供应商。
    2. JOIN ``kb_llm_model`` 取 ``is_default=1`` 且 ``is_enabled=1`` 的模型。
    3. JOIN ``kb_llm_health`` 过滤 ``health_status != unhealthy`` 的模型。
    4. 按 ``priority`` 升序排序，同优先级按 ``id`` 升序。
    5. 返回 (provider, model) 元组列表，调用方按顺序尝试。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.orm import LlmHealth, LlmModel, LlmProvider
from src.models.enums import LlmHealthStatus

logger = logging.getLogger(__name__)


def get_routable_chain(
    session: Session,
    *,
    exclude_degraded: bool = False,
) -> list[tuple[LlmProvider, LlmModel]]:
    """获取完整的路由链 (provider, model) 元组列表。

    按 provider.priority 升序、provider.id 升序排列。
    unhealthy 模型始终排除；degraded 可选排除。
    无可用模型（仅有 provider 但无 enabled default model 或 health 行缺失）
    的供应商被跳过。

    Args:
        session: SQLAlchemy Session。
        exclude_degraded: 是否排除 degraded 状态的模型，默认 False。

    Returns:
        (provider, model) 元组列表，按优先级排序。可能为空。
    """
    stmt = (
        select(LlmProvider, LlmModel)
        .join(LlmModel, LlmModel.provider_id == LlmProvider.id)
        .join(LlmHealth, LlmHealth.model_id == LlmModel.id)
        .where(
            LlmProvider.is_enabled == True,  # noqa: E712
            LlmProvider.is_deleted == False,  # noqa: E712
            LlmModel.is_default == True,  # noqa: E712
            LlmModel.is_enabled == True,  # noqa: E712
            LlmModel.is_deleted == False,  # noqa: E712
            LlmHealth.is_deleted == False,  # noqa: E712
            LlmHealth.health_status != LlmHealthStatus.UNHEALTHY,
        )
    )

    if exclude_degraded:
        stmt = stmt.where(LlmHealth.health_status == LlmHealthStatus.HEALTHY)

    stmt = stmt.order_by(LlmProvider.priority, LlmProvider.id)

    results = list(session.execute(stmt).all())
    chain: list[tuple[LlmProvider, LlmModel]] = [
        (row[0], row[1]) for row in results
    ]

    if not chain:
        logger.warning("无可用 LLM 供应商-模型路由链")

    for provider, model in chain:
        logger.debug(
            "路由候选: provider=%s model=%s priority=%d",
            provider.provider_code,
            model.model_code,
            provider.priority,
        )

    return chain


def select_first_available(
    session: Session,
) -> tuple[LlmProvider, LlmModel] | None:
    """选择第一个可用的 (provider, model) 组合。

    等价于 ``get_routable_chain(session)[0]``，但更简洁。
    用于不需要 fallback 的简单场景。

    Args:
        session: SQLAlchemy Session。

    Returns:
        (provider, model) 元组，无可用时返回 None。
    """
    chain = get_routable_chain(session)
    return chain[0] if chain else None


def get_all_enabled_providers(session: Session) -> Sequence[LlmProvider]:
    """查询所有启用的供应商（含 unhealthy），用于管理面板展示。

    不同于 :func:`get_routable_chain`，此函数不排除 unhealthy 供应商，
    也不 JOIN 模型和健康状态。

    Args:
        session: SQLAlchemy Session。

    Returns:
        所有启用供应商列表，按优先级排序。
    """
    stmt = (
        select(LlmProvider)
        .where(
            LlmProvider.is_enabled == True,  # noqa: E712
            LlmProvider.is_deleted == False,  # noqa: E712
        )
        .order_by(LlmProvider.priority, LlmProvider.id)
    )
    return list(session.execute(stmt).scalars().all())
