"""LLM 供应商路由模块。

按优先级 + 健康状态选择可用供应商和模型。
支持 fallback 链：首选供应商不可用时自动降级到次优。

路由查询逻辑：
    1. 筛选 ``is_enabled=1`` 且 ``health_status != unhealthy`` 的供应商。
    2. 按 ``priority`` 升序排序，同优先级按 ``id`` 升序。
    3. 对每个供应商取 ``is_default=1`` 且 ``is_enabled=1`` 的模型。
    4. 返回 (provider, model) 元组列表，调用方按顺序尝试。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.orm import LlmModel, LlmProvider
from src.models.enums import LlmHealthStatus

logger = logging.getLogger(__name__)


def get_routable_providers(
    session: Session,
    *,
    exclude_degraded: bool = False,
) -> list[LlmProvider]:
    """查询可路由的供应商列表。

    按 ``priority`` 升序、``id`` 升序排列。
    unhealthy 供应商始终排除；degraded 可选排除。

    Args:
        session: SQLAlchemy Session。
        exclude_degraded: 是否排除 degraded 状态的供应商，默认 False（degraded 仍可尝试）。

    Returns:
        可用供应商列表，按优先级排序。
    """
    stmt = select(LlmProvider).where(
        LlmProvider.is_enabled == True,  # noqa: E712
        LlmProvider.is_deleted == False,  # noqa: E712
    )

    if exclude_degraded:
        stmt = stmt.where(LlmProvider.health_status == LlmHealthStatus.HEALTHY)
    else:
        stmt = stmt.where(
            LlmProvider.health_status != LlmHealthStatus.UNHEALTHY
        )

    stmt = stmt.order_by(LlmProvider.priority, LlmProvider.id)
    return list(session.execute(stmt).scalars().all())


def get_default_model(session: Session, provider_id: int) -> LlmModel | None:
    """获取供应商的默认模型。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。

    Returns:
        默认模型 ORM 对象，不存在则返回 None。
    """
    stmt = select(LlmModel).where(
        LlmModel.provider_id == provider_id,
        LlmModel.is_default == True,  # noqa: E712
        LlmModel.is_enabled == True,  # noqa: E712
        LlmModel.is_deleted == False,  # noqa: E712
    )
    return session.execute(stmt).scalars().first()


def get_routable_chain(
    session: Session,
    *,
    exclude_degraded: bool = False,
) -> list[tuple[LlmProvider, LlmModel]]:
    """获取完整的路由链 (provider, model) 元组列表。

    调用方按列表顺序依次尝试，首个成功即返回。
    无可用模型（仅有 provider 但无 enabled model）的供应商被跳过。

    Args:
        session: SQLAlchemy Session。
        exclude_degraded: 是否排除 degraded 供应商。

    Returns:
        (provider, model) 元组列表，按优先级排序。可能为空。
    """
    providers = get_routable_providers(
        session, exclude_degraded=exclude_degraded
    )
    chain: list[tuple[LlmProvider, LlmModel]] = []

    for provider in providers:
        model = get_default_model(session, provider.id)
        if model is not None:
            chain.append((provider, model))
        else:
            logger.warning(
                "供应商 %s 无可用默认模型，跳过",
                provider.provider_code,
            )

    if not chain:
        logger.warning("无可用 LLM 供应商-模型路由链")
    return chain


def select_first_available(
    session: Session,
) -> tuple[LlmProvider, LlmModel] | None:
    """选择第一个可用的 (provider, model) 组合。

    等价于 ``get_routable_chain()[0]``，但更简洁。
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

    不同于 :func:`get_routable_providers`，此函数不排除 unhealthy 供应商。

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
