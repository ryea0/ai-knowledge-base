"""LLM 调用日志写入服务。

在 :func:`src.llm.client.chat_completion` 成功/失败后调用，
将 token 用量、成本、延迟等信息写入 ``kb_llm_call_log`` 表。

事务约定：
    本模块不调用 ``session.commit()``，仅 ``session.add()`` + ``session.flush()``。
    事务提交/回滚由调用方控制（CLI / FastAPI 端点）。

Usage::

    from src.llm.log_call import write_call_log

    # 成功调用
    write_call_log(
        session,
        provider_id=1,
        model_id=2,
        is_success=True,
        usage=llm_response.usage,
        cost=llm_response.cost,
        latency_ms=1234,
    )

    # 失败调用
    write_call_log(
        session,
        provider_id=1,
        model_id=2,
        is_success=False,
        latency_ms=500,
        error_msg="timeout",
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.common.trace import get_trace_id
from src.llm.orm import LlmCallLog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.llm.cost import CostEstimate, TokenUsage

logger = logging.getLogger(__name__)


def write_call_log(
    session: Session,
    *,
    provider_id: int,
    model_id: int,
    is_success: bool,
    latency_ms: int | None = None,
    usage: TokenUsage | None = None,
    cost: CostEstimate | None = None,
    error_msg: str | None = None,
) -> None:
    """写入一条 LLM 调用计量日志。

    成功时记录 token 用量和成本，失败时记录错误信息。
    trace_id 从 :func:`src.common.trace.get_trace_id` 获取，
    未设置时使用 ``"-"``。

    事务由调用方管理，本函数仅 ``add`` + ``flush``。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        model_id: 模型 ID。
        is_success: 调用是否成功。
        latency_ms: 响应延迟毫秒。
        usage: Token 用量统计（成功时传入）。
        cost: 成本估算（成功时传入）。
        error_msg: 失败原因（脱敏后，失败时传入）。
    """
    trace_id = get_trace_id()

    input_tokens = usage.prompt_tokens if usage else None
    output_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None
    cost_amount = cost.total_cost if cost else None
    cost_currency = cost.currency if cost else None

    log = LlmCallLog(
        trace_id=trace_id,
        provider_id=provider_id,
        model_id=model_id,
        is_success=is_success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        latency_ms=latency_ms,
        error_msg=error_msg,
    )
    session.add(log)
    session.flush()

    logger.debug(
        "call_log 写入: provider_id=%d model_id=%d success=%s "
        "tokens=%s cost=%s %s latency=%sms",
        provider_id,
        model_id,
        is_success,
        total_tokens,
        cost_amount,
        cost_currency,
        latency_ms,
    )


__all__ = ["write_call_log"]
