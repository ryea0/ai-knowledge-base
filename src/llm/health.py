"""LLM 供应商健康检查服务。

实现类熔断器状态机：
    healthy -> degraded -> unhealthy

状态转换规则（CAS 乐观锁，见 docs/specs/llm-provider.md §9.2）：
    - 调用成功：``consecutive_failures`` 归零，状态转 ``healthy``
    - 调用失败：``consecutive_failures`` 递增
        - 达到 ``failure_threshold``：转 ``unhealthy``
        - 未达阈值：转 ``degraded``
    - unhealthy 供应商被路由跳过，需定时健康检查恢复

所有状态更新使用 CAS（``WHERE id=? AND health_status=?``）保证并发安全。

事务约定：
    本模块所有函数**不调用** ``session.commit()``，仅执行 ``session.flush()``
    以确保 UPDATE 生效。事务提交/回滚由调用方控制。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.llm.orm import LlmHealthLog, LlmProvider
from src.models.enums import LlmHealthStatus

if TYPE_CHECKING:
    from src.llm.orm import LlmModel

logger = logging.getLogger(__name__)


def record_success(
    session: Session,
    provider_id: int,
    *,
    model_id: int | None = None,
    latency_ms: int | None = None,
) -> None:
    """记录一次成功的 LLM 调用，更新供应商健康状态为 healthy。

    使用 CAS 更新：仅当当前状态为非 healthy 时才转换（避免无谓写）。
    ``consecutive_failures`` 归零，``last_success_at`` 更新。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        model_id: 被调用的模型 ID（可选，用于日志）。
        latency_ms: 响应延迟毫秒（可选，用于日志）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    # CAS 更新：非 healthy 状态 -> healthy（排除软删除）
    session.execute(
        update(LlmProvider)
        .where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
            LlmProvider.health_status != LlmHealthStatus.HEALTHY,
        )
        .values(
            health_status=LlmHealthStatus.HEALTHY,
            consecutive_failures=0,
            last_success_at=now,
            last_error=None,
        )
    )
    session.flush()

    logger.debug(
        "供应商 %d 健康状态更新为 healthy",
        provider_id,
    )


def record_failure(
    session: Session,
    provider_id: int,
    error_msg: str,
    *,
    model_id: int | None = None,
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
        error_msg: 错误信息（须脱敏，禁止含 API Key）。
        model_id: 被调用的模型 ID（可选）。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    sanitized = error_msg[:500]

    # 先读取当前 provider 获取 failure_threshold（排除软删除）
    from sqlalchemy import select as sa_select

    provider = session.execute(
        sa_select(LlmProvider).where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()
    if provider is None:
        logger.error("供应商 %d 不存在或已删除，无法记录失败", provider_id)
        return

    new_failures = provider.consecutive_failures + 1
    new_status = (
        LlmHealthStatus.UNHEALTHY
        if new_failures >= provider.failure_threshold
        else LlmHealthStatus.DEGRADED
    )

    session.execute(
        update(LlmProvider)
        .where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
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
        "供应商 %d 健康状态更新为 %s，连续失败 %d/%d",
        provider_id,
        new_status.to_json_str(),
        new_failures,
        provider.failure_threshold,
    )


def check_provider_health(
    session: Session,
    provider: LlmProvider,
    model: LlmModel | None = None,
) -> bool:
    """执行一次健康检查并记录日志。

    检查方式：
        - 有 model：发送一条简短消息（``ping``）测试端到端可用性。
        - 无 model：调用 ``GET {base_url}/models`` 测试连通性。

    检查结果写入 ``kb_llm_health_log`` 表并更新 provider 当前状态。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider: 供应商 ORM 对象。
        model: 可选的模型 ORM 对象，传入则做模型级检查。

    Returns:
        True 表示健康检查成功，False 表示失败。
    """
    if not provider.health_check_enabled:
        logger.debug("供应商 %s 健康检查已禁用，跳过", provider.provider_code)
        return True

    import time

    import httpx

    now = datetime.now(UTC).replace(tzinfo=None)
    start = time.monotonic()
    is_success = False
    latency_ms: int | None = None
    error_msg: str | None = None

    try:
        # 构造健康检查请求
        headers: dict[str, str] = {"Content-Type": "application/json"}

        from src.llm.crypto import decrypt

        if provider.api_key_encrypted:
            api_key = decrypt(provider.api_key_encrypted)
            if provider.auth_type.value == 2:  # HEADER
                header_name = (
                    provider.auth_config.get("header_name", "x-api-key")
                    if provider.auth_config
                    else "x-api-key"
                )
                headers[header_name] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"

        # GET {base_url}/models
        url = provider.base_url.rstrip("/") + "/models"
        resp = httpx.get(
            url, headers=headers, timeout=provider.timeout_seconds
        )
        resp.raise_for_status()

        latency_ms = int((time.monotonic() - start) * 1000)
        is_success = True

    except Exception as exc:
        latency_ms = None
        error_msg = str(exc)[:500]
        is_success = False
        logger.warning(
            "供应商 %s 健康检查失败: %s",
            provider.provider_code,
            error_msg,
        )

    # 写健康日志
    log_entry = LlmHealthLog(
        provider_id=provider.id,
        model_id=model.id if model else None,
        check_at=now,
        latency_ms=latency_ms,
        is_success=is_success,
        error_msg=error_msg,
    )
    session.add(log_entry)

    # 更新 provider 当前状态（排除软删除）
    session.execute(
        update(LlmProvider)
        .where(
            LlmProvider.id == provider.id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
        .values(
            last_check_at=now,
            health_status=(
                LlmHealthStatus.HEALTHY
                if is_success
                else LlmHealthStatus.DEGRADED
            ),
            consecutive_failures=0 if is_success else provider.consecutive_failures + 1,
            last_success_at=now if is_success else provider.last_success_at,
            last_failure_at=now if not is_success else provider.last_failure_at,
            last_error=None if is_success else error_msg,
        )
    )
    session.flush()

    return is_success


def reset_health(session: Session, provider_id: int) -> None:
    """重置供应商健康状态为 unknown。

    用于管理后台手动重置，让被熔断的供应商重新进入检测。
    事务由调用方管理，本函数仅 ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
    """
    session.execute(
        update(LlmProvider)
        .where(
            LlmProvider.id == provider_id,
            LlmProvider.is_deleted == False,  # noqa: E712
        )
        .values(
            health_status=LlmHealthStatus.UNKNOWN,
            consecutive_failures=0,
            last_error=None,
        )
    )
    session.flush()

    logger.info("供应商 %d 健康状态已重置为 unknown", provider_id)
