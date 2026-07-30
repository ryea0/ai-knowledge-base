"""LLM 调用适配层。

将 ``chat_completion``（无重试版）封装为适配层函数 ``chat_for_analysis``，
按 ``LlmCallError.error_type`` 将不可重试的 LLM 错误转换为
``NonRetryableLlmError``，使外层 ``with_retry`` 装饰器能按类型区分重试/不重试。

调用链: ``analyze()`` -> ``@with_retry`` 装饰的 ``chat_for_analysis()``
-> ``chat_completion()`` -> ``litellm.completion()``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.llm.client import LlmCallError, LLMResponse, chat_completion
from src.llm.retry_decorator import RETRYABLE_LLM_ERROR_TYPES, NonRetryableLlmError
from src.llm.router import select_first_available

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def chat_for_analysis(
    prompt: str,
    session: Session,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    node_name: str = "unknown",
) -> str:
    """调用 LLM 进行分析（无内置重试，由外层 ``with_retry`` 装饰器控制重试）。

    自动从 DB 中选取最优供应商和默认模型（按优先级 + 健康状态路由）。
    内部调用 :func:`chat_completion`（无重试版），不调用
    :func:`chat_completion_with_retry`，避免双重重试。

    当 ``chat_completion`` 抛出 ``LlmCallError`` 时，按 ``error_type`` 分类:
        - ``TIMEOUT`` / ``RATE_LIMITED`` / ``NETWORK`` / ``SERVER_ERROR``
          -> 原样抛出（匹配外层 ``retry_on``）
        - ``AUTH_FAILED`` / ``CLIENT_ERROR`` / ``UNKNOWN``
          -> 转换为 ``NonRetryableLlmError``（不匹配 ``retry_on``）

    ``BudgetExceededError`` 由 ``chat_completion`` 内 ``BudgetGuard.check_pre_call``
    抛出，本函数不捕获，原样穿透。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session（用于查询供应商/模型 + 健康联动）。
        system_prompt: 可选的 system 消息，用于设定角色或上下文。
        temperature: 采样温度，默认 0.7。
        max_tokens: 最大输出 tokens，None 则使用模型默认值。
        node_name: 发起调用的节点名称，透传给 :func:`chat_completion` 用于成本追踪。

    Returns:
        LLM 生成的回复文本。

    Raises:
        LlmCallError: 可重试的 LLM 调用失败（TIMEOUT / RATE_LIMITED / NETWORK / SERVER_ERROR）。
        NonRetryableLlmError: 不可重试的 LLM 调用失败（AUTH_FAILED / CLIENT_ERROR / UNKNOWN）。
        RuntimeError: 无可用供应商-模型组合。
        BudgetExceededError: 预算超限（原样穿透，不捕获）。
    """
    pair = select_first_available(session)
    if pair is None:
        raise RuntimeError("无可用 LLM 供应商-模型组合")

    provider, model = pair

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = chat_completion(
            provider,
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            session=session,
            node_name=node_name,
        )
    except LlmCallError as exc:
        if exc.error_type in RETRYABLE_LLM_ERROR_TYPES:
            raise
        raise NonRetryableLlmError(exc) from exc

    return response.content if isinstance(response, LLMResponse) else str(response)


__all__ = ["chat_for_analysis"]
