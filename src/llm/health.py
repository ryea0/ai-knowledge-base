"""LLM 模型健康状态管理服务。

实现模型级类熔断器状态机：
    healthy -> degraded -> unhealthy

状态转换规则（CAS 乐观锁，见 docs/specs/llm-provider.md §9.2）：
    - 调用成功：``consecutive_failures`` 归零，状态转 ``healthy``，
      更新 ``last_success_at`` / ``last_latency_ms``
    - 调用失败：``consecutive_failures`` 递增
        - 达到 ``failure_threshold``：转 ``unhealthy``
        - 未达阈值：转 ``degraded``
    - unhealthy 模型被路由跳过，需定时健康检查恢复

健康状态存储于 ``kb_llm_health`` 表（模型级，upsert 语义），
每个模型至多一行。

所有状态更新使用原子 SQL（``UPDATE ... SET consecutive_failures =
consecutive_failures + 1 ...``）保证并发安全，避免读-写竞态。

事务约定：
    本模块所有函数**不调用** ``session.commit()``，仅执行 ``session.flush()``
    以确保 UPDATE 生效。事务提交/回滚由调用方控制。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import case, select, update
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

    始终更新 ``consecutive_failures`` 归零、``last_success_at``、
    ``last_error`` 清空。若传入 ``latency_ms`` 则更新 ``last_latency_ms``。
    ``last_success_at`` 在所有状态下都更新（包括已 healthy 的模型）。

    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID（用于日志，不参与查询）。
        model_id: 被调用的模型 ID。
        latency_ms: 响应延迟毫秒（可选）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    values: dict[str, object] = {
        "consecutive_failures": 0,
        "health_status": LlmHealthStatus.HEALTHY,
        "last_success_at": now,
        "last_error": None,
    }
    if latency_ms is not None:
        values["last_latency_ms"] = latency_ms

    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model_id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
        .values(**values)
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

    原子更新逻辑（单条 SQL，无读-写竞态）：
        - ``consecutive_failures`` = ``consecutive_failures + 1``
        - 若 ``consecutive_failures + 1 >= failure_threshold``：
          状态转 ``unhealthy``
        - 否则：状态转 ``degraded``
        - ``last_failure_at`` 和 ``last_error`` 更新

    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID（用于日志，不参与查询）。
        model_id: 被调用的模型 ID。
        error_msg: 错误信息（须脱敏，禁止含 API Key）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    sanitized = error_msg[:500]

    new_failures = LlmHealth.consecutive_failures + 1

    # 使用 SQL CASE 表达式在单条 UPDATE 中原子判断状态转换
    new_status = case(
        (
            new_failures >= LlmHealth.failure_threshold,
            LlmHealthStatus.UNHEALTHY.value,
        ),
        else_=LlmHealthStatus.DEGRADED.value,
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
        "模型 %d 记录失败，连续失败计数已递增",
        model_id,
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

    状态转换规则：
        - 成功：转 ``healthy``，``consecutive_failures`` 归零
        - 失败且已达 ``failure_threshold``：保持 ``unhealthy``
        - 失败且未达阈值：转 ``degraded``

    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider: 供应商 ORM 对象。
        model: 模型 ORM 对象。

    Returns:
        True 表示健康检查成功，False 表示失败。
    """
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

    if result.success:
        new_failures = 0
        new_status = LlmHealthStatus.HEALTHY
        new_success_at: datetime | None = now
        new_failure_at: datetime | None = health.last_failure_at
        new_error: str | None = None
    else:
        new_failures = health.consecutive_failures + 1
        new_status = (
            LlmHealthStatus.UNHEALTHY
            if new_failures >= health.failure_threshold
            else LlmHealthStatus.DEGRADED
        )
        new_success_at = health.last_success_at
        new_failure_at = now
        new_error = result.error

    session.execute(
        update(LlmHealth)
        .where(
            LlmHealth.model_id == model.id,
            LlmHealth.is_deleted == False,  # noqa: E712
        )
        .values(
            last_check_at=now,
            last_latency_ms=result.latency_ms,
            health_status=new_status,
            consecutive_failures=new_failures,
            last_success_at=new_success_at,
            last_failure_at=new_failure_at,
            last_error=new_error,
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
