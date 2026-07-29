"""LLM 调用 Token 消耗估算与成本计算。

根据 LiteLLM 响应中的 ``usage`` 字段和模型的定价信息，
计算单次调用的 Token 消耗和预估成本。

定价单位为"每百万 token"的价格（与 ORM ``LlmModel`` 的
``input_price_per_1m`` / ``output_price_per_1m`` 字段一致），
币种由 ``LlmModel.currency`` 字段决定（CNY / USD）。

使用方式::

    from src.llm.cost import estimate_cost

    cost = estimate_cost(response, model)
    print(cost.total_cost)  # 0.0023
    print(cost.currency)    # "CNY"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.orm import LlmModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    """Token 用量统计。

    Attributes:
        prompt_tokens: 输入（prompt）token 数。
        completion_tokens: 输出（completion）token 数。
        total_tokens: 总 token 数（prompt + completion）。
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class CostEstimate:
    """单次 LLM 调用的成本估算结果。

    Attributes:
        usage: Token 用量统计。
        input_cost: 输入 token 成本。
        output_cost: 输出 token 成本。
        total_cost: 总成本。
        currency: 币种（CNY / USD），来自模型配置。
    """

    usage: TokenUsage
    input_cost: float
    output_cost: float
    total_cost: float
    currency: str = "CNY"


def extract_usage(response: dict[str, object] | object) -> TokenUsage | None:
    """从 LiteLLM 响应中提取 Token 用量。

    兼容两种响应形态：
        - ``dict``: ``chat_completion`` 返回的 ``dict(response)`` 形态
        - ``ModelResponse``: LiteLLM 原生 Pydantic 对象

    Args:
        response: LiteLLM 响应对象或字典。

    Returns:
        :class:`TokenUsage` 实例，若响应中无 ``usage`` 字段则返回 None。
    """
    usage: object = None

    if isinstance(response, dict):
        usage = response.get("usage")
    else:
        usage = getattr(response, "usage", None)

    if usage is None:
        return None

    prompt_tokens = _get_int_field(usage, "prompt_tokens")
    completion_tokens = _get_int_field(usage, "completion_tokens")
    total_tokens = _get_int_field(usage, "total_tokens")

    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def estimate_cost(
    response: dict[str, object] | object,
    model: LlmModel,
) -> CostEstimate:
    """根据 LLM 响应和模型定价计算成本。

    定价取自 ``model.input_price_per_1m`` / ``model.output_price_per_1m``
    （每百万 token 的价格），币种取自 ``model.currency``（CNY / USD）。

    若响应中无 ``usage`` 字段，返回零成本估算。

    Args:
        response: LiteLLM 响应对象或字典。
        model: 模型 ORM 对象（含定价字段）。

    Returns:
        :class:`CostEstimate` 成本估算结果。
    """
    usage = extract_usage(response)

    currency = getattr(model, "currency", "CNY") or "CNY"

    if usage is None:
        logger.debug(
            "模型 %s 响应中无 usage 字段，返回零成本",
            getattr(model, "model_code", "unknown"),
        )
        return CostEstimate(
            usage=TokenUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
            input_cost=0.0,
            output_cost=0.0,
            total_cost=0.0,
            currency=currency,
        )

    input_price = float(model.input_price_per_1m)
    output_price = float(model.output_price_per_1m)

    input_cost = (usage.prompt_tokens / 1_000_000) * input_price
    output_cost = (usage.completion_tokens / 1_000_000) * output_price
    total_cost = input_cost + output_cost

    return CostEstimate(
        usage=usage,
        input_cost=round(input_cost, 6),
        output_cost=round(output_cost, 6),
        total_cost=round(total_cost, 6),
        currency=currency,
    )


def _get_int_field(obj: object, field_name: str) -> int:
    """从对象或字典中安全提取整数字段。

    Args:
        obj: 可能是 dict 或 Pydantic model 的对象。
        field_name: 字段名。

    Returns:
        字段值，不存在或非整数时返回 0。
    """
    val = obj.get(field_name, 0) if isinstance(obj, dict) else getattr(obj, field_name, 0)

    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CostEstimate",
    "TokenUsage",
    "estimate_cost",
    "extract_usage",
]
