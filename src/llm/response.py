"""LLM 调用统一返回体。

将 LiteLLM 原始响应封装为 :class:`LLMResponse`，统一暴露
``content`` / ``usage`` / ``cost`` 等字段，调用方无需再分别调用
``extract_content`` 和 ``estimate_cost``。

使用方式::

    from src.llm.client import chat_completion_with_retry

    resp = chat_completion_with_retry(provider, model, messages)
    print(resp.content)           # "你好！"
    print(resp.usage.total_tokens)    # 128
    print(resp.cost.total_cost)       # 0.000123
    print(resp.cost.currency)         # "CNY"

对于流式调用（``stream=True``），返回原始 LiteLLM 响应对象，
不封装为 :class:`LLMResponse`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.llm.cost import CostEstimate, TokenUsage, estimate_cost
from src.llm.response_extractor import extract_content

if TYPE_CHECKING:
    from src.llm.orm import LlmModel

__all__ = ["LLMResponse"]


@dataclass(frozen=True)
class LLMResponse:
    """LLM 调用统一返回体。

    封装 LiteLLM 响应，提供已提取的回复文本、Token 用量和成本估算，
    同时保留原始响应供高级用途（如解析 tool_calls）。

    Attributes:
        content: 已提取的回复文本（按模型类型自动选择提取策略）。
        usage: Token 用量统计，无 ``usage`` 字段时为零值。
        cost: 成本估算，无定价时为零值。
        model_code: 模型代码，用于日志定位。
        provider_code: 供应商代码，用于日志定位。
        latency_ms: 调用耗时（毫秒）。
        raw: 原始 LiteLLM 响应对象，供高级用途使用。
    """

    content: str
    usage: TokenUsage
    cost: CostEstimate
    model_code: str
    provider_code: str
    latency_ms: int
    raw: dict[str, Any] | object

    @classmethod
    def from_litellm_response(
        cls,
        response: dict[str, Any] | object,
        model: LlmModel,
        *,
        provider_code: str = "",
        latency_ms: int = 0,
    ) -> LLMResponse:
        """从 LiteLLM 响应构造 :class:`LLMResponse`。

        内部自动调用 :func:`extract_content` 和 :func:`estimate_cost`，
        调用方无需关心提取逻辑。

        Args:
            response: LiteLLM 响应对象或字典。
            model: 模型 ORM 对象（含 ``supports_reasoning`` / 定价字段）。
            provider_code: 供应商代码。
            latency_ms: 调用耗时（毫秒）。

        Returns:
            :class:`LLMResponse` 实例。
        """
        content = extract_content(response, model)
        cost = estimate_cost(response, model)
        usage = cost.usage if cost.usage is not None else TokenUsage(0, 0, 0)

        return cls(
            content=content,
            usage=usage,
            cost=cost,
            model_code=getattr(model, "model_code", ""),
            provider_code=provider_code,
            latency_ms=latency_ms,
            raw=response,
        )
