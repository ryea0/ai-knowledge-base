"""LLM 调用适配层。

将 ``chat_completion``（无重试版）封装为适配层函数 ``chat_for_analysis``，
按 ``LlmCallError.error_type`` 将不可重试的 LLM 错误转换为
``NonRetryableLlmError``，使外层 ``with_retry`` 装饰器能按类型区分重试/不重试。

调用链: ``analyze()`` -> ``@with_retry`` 装饰的 ``chat_for_analysis()``
-> ``chat_completion()`` -> ``litellm.completion()``

供应商 fallback：
    当首选供应商调用失败（``LlmCallError``）时，自动尝试路由链中的下一个供应商，
    直到成功或全部失败。``BudgetExceededError`` 不触发 fallback（预算超限应立即终止）。
    最终全部失败时，抛出最后一个 ``LlmCallError``（可重试类型）或
    ``NonRetryableLlmError``（不可重试类型）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.llm.client import LlmCallError, LLMResponse, chat_completion
from src.llm.retry_decorator import RETRYABLE_LLM_ERROR_TYPES, NonRetryableLlmError
from src.llm.router import get_routable_chain

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

    自动从 DB 中获取路由链（按优先级 + 健康状态排序），依次尝试每个供应商，
    首个成功即返回。全部失败时抛出最后一个错误。

    当 ``chat_completion`` 抛出 ``LlmCallError`` 时，按 ``error_type`` 分类:
        - ``TIMEOUT`` / ``RATE_LIMITED`` / ``NETWORK`` / ``SERVER_ERROR``
          -> 可重试，触发 fallback 尝试下一个供应商
        - ``AUTH_FAILED`` / ``CLIENT_ERROR`` / ``UNKNOWN``
          -> 不可重试，触发 fallback 尝试下一个供应商

    全部供应商失败后：
        - 最后一个错误为可重试类型 -> 原样抛出 ``LlmCallError``
        - 最后一个错误为不可重试类型 -> 转换为 ``NonRetryableLlmError``

    ``BudgetExceededError`` 由 ``chat_completion`` 内 ``BudgetGuard.check_pre_call``
    抛出，本函数不捕获，原样穿透（不触发 fallback）。

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
        LlmCallError: 所有供应商均失败，且最后一次错误为可重试类型。
        NonRetryableLlmError: 所有供应商均失败，且最后一次错误为不可重试类型。
        RuntimeError: 无可用供应商-模型组合。
        BudgetExceededError: 预算超限（原样穿透，不触发 fallback）。
    """
    chain = get_routable_chain(session)
    if not chain:
        raise RuntimeError("无可用 LLM 供应商-模型组合")

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_exc: LlmCallError | None = None

    for provider, model in chain:
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
            last_exc = exc
            logger.warning(
                "供应商 %s 模型 %s 调用失败 (%s)，尝试下一个供应商",
                provider.provider_code,
                model.model_code,
                exc.error_type.value,
            )
            continue

        return response.content if isinstance(response, LLMResponse) else str(response)

    if last_exc is not None:
        if last_exc.error_type in RETRYABLE_LLM_ERROR_TYPES:
            raise last_exc
        raise NonRetryableLlmError(last_exc) from last_exc

    raise RuntimeError("无可用 LLM 供应商-模型组合")


__all__ = ["chat_for_analysis"]
