"""LLM 模型健康状态管理服务。

实现模型级类熔断器状态机：
    healthy -> degraded -> unhealthy

状态转换规则（CAS 乐观锁，见 docs/specs/llm-provider.md §9.2）：
    - 调用成功：``consecutive_failures`` 归零，状态转 ``healthy``
    - 调用失败：``consecutive_failures`` 递增
        - 达到 ``failure_threshold``：转 ``unhealthy``
        - 未达阈值：转 ``degraded``
    - unhealthy 模型被路由跳过，需定时健康检查恢复

健康状态存储于 ``kb_llm_health`` 表（模型级，upsert 语义），
每个模型至多一行。

所有状态更新使用 CAS（``WHERE model_id=? AND health_status=?``）保证并发安全。

事务约定：
    本模块所有函数**不调用** ``session.commit()``，仅执行 ``session.flush()``
    以确保 UPDATE 生效。事务提交/回滚由调用方控制。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.llm.orm import LlmHealth
from src.models.enums import LlmHealthStatus

if TYPE_CHECKING:
    from src.llm.orm import LlmModel, LlmProvider

logger = logging.getLogger(__name__)


def record_success(
    session: Session,
    provider_id: int,
    model_id: int,
    *,
    latency_ms: int | None = None,
) -> None:
    """记录一次成功的 LLM 调用，更新模型健康状态为 healthy。

    使用 CAS 更新：仅当当前状态为非 healthy 时才转换（避免无谓写）。
    ``consecutive_failures`` 归零，``last_success_at`` 更新。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        model_id: 被调用的模型 ID。
        latency_ms: 响应延迟毫秒（可选）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    values: dict[str, object] = {
        "consecutive_failures": 0,
        "last_success_at": now,
        "last_error": None,
    }
    if latency_ms is not None:
        values["last_latency_ms"] = latency_ms

    # CAS 更新：非 healthy 状态 -> healthy（排除软删除）
    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
            LlmHealth.health_status != LlmHealthStatus.HEALTHY,
        )
        .values(health_status=LlmHealthStatus.HEALTHY, **values)
    )
    session.flush()

    logger.debug(
        "模型 %d 健康状态更新为 healthy",
        model_id,
    )


def record_failure(
    session: Session,
    provider_id: int,
    model_id: int,
    error_msg: str,
) -> None:
    """记录一次失败的 LLM 调用，递增失败计数并可能转换状态。

    CAS 更新逻辑：
        - ``consecutive_failures`` +1
        - 达到 ``failure_threshold``：状态转 ``unhealthy``
        - 未达阈值：状态转 ``degraded``
        - ``last_failure_at`` 和 ``last_error`` 更新
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        model_id: 被调用的模型 ID。
        error_msg: 错误信息（须脱敏，禁止含 API Key）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    sanitized = error_msg[:500]

    # 读取当前 health 行获取 failure_threshold（排除软删除）
    health = session.execute(
        select(LlmHealth).where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if health is None:
        logger.error("模型 %d 无健康状态行，无法记录失败", model_id)
        return

    new_failures = health.consecutive_failures + 1
    new_status = (
        LlmHealthStatus.UNHEALTHY
        if new_failures >= health.failure_threshold
        else LlmHealthStatus.DEGRADED
    )

    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
        .values(
            health_status=new_status,
            consecutive_failures=new_failures,
            last_failure_at=now,
            last_error=sanitized,
        )
    )
    session.flush()

    logger.warning(
        "模型 %d 健康状态更新为 %s，连续失败 %d/%d",
        model_id,
        new_status.to_json_str(),
        new_failures,
        health.failure_threshold,
    )


def check_model_health(
    session: Session,
    provider: LlmProvider,
    model: LlmModel,
) -> bool:
    """执行一次模型级健康检查并更新状态。

    检查方式：调用 :func:`src.llm.connectivity.test_connectivity` 测试供应商连通性，
    按 ``litellm_provider`` 分派到不同探测端点（OpenAI / Anthropic / Ollama）。
    检查结果更新 ``kb_llm_health`` 表中该模型的当前状态。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider: 供应商 ORM 对象。
        model: 模型 ORM 对象。

    Returns:
        True 表示健康检查成功，False 表示失败。
    """
    # 检查该模型的 health 行是否存在且启用健康检查
    health = session.execute(
        select(LlmHealth).where(
            LlmHealth.model_id == model.id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if health is None:
        logger.warning("模型 %d 无健康状态行，跳过检查", model.id)
        return True

    if not health.health_check_enabled:
        logger.debug("模型 %d 健康检查已禁用，跳过", model.id)
        return True

    from src.llm.connectivity import test_connectivity

    now = datetime.now(UTC).replace(tzinfo=None)
    result = test_connectivity(provider)

    # 更新 kb_llm_health 当前状态
    new_failures = 0 if result.success else health.consecutive_failures + 1
    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model.id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
        .values(
            last_check_at=now,
            last_latency_ms=result.latency_ms,
            health_status=(
                LlmHealthStatus.HEALTHY
                if result.success
                else LlmHealthStatus.DEGRADED
            ),
            consecutive_failures=new_failures,
            last_success_at=now if result.success else health.last_success_at,
            last_failure_at=now if not result.success else health.last_failure_at,
            last_error=None if result.success else result.error,
        )
    )
    session.flush()

    if not result.success:
        logger.warning(
            "模型 %d 健康检查失败: %s",
            model.id,
            result.error,
        )

    return result.success


def reset_health(session: Session, model_id: int) -> None:
    """重置模型健康状态为 unknown。

    用于管理后台手动重置，让被熔断的模型重新进入检测。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        model_id: 模型 ID。
    """
    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
        .values(
            health_status=LlmHealthStatus.UNKNOWN,
            consecutive_failures=0,
            last_error=None,
        )
    )
    session.flush()

    logger.info("模型 %d 健康状态已重置为 unknown", model_id)
