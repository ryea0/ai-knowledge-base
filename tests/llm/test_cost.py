"""src.llm.cost 的单元测试。

测试覆盖：
- extract_usage: 从 dict / Pydantic 对象提取 TokenUsage
- estimate_cost: 成本计算（正常 / 无 usage / 零定价）
- TokenUsage / CostEstimate dataclass 属性
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.llm.cost import (
    CostEstimate,
    TokenUsage,
    estimate_cost,
    extract_usage,
)

# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------


def _make_model(
    *,
    input_price: float = 1.0,
    output_price: float = 2.0,
    model_code: str = "test-model",
    currency: str = "CNY",
) -> MagicMock:
    """构造 model mock，含定价字段。"""
    model = MagicMock()
    model.input_price_per_1m = input_price
    model.output_price_per_1m = output_price
    model.model_code = model_code
    model.currency = currency
    return model


def _make_dict_response(
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int | None = 150,
) -> dict[str, object]:
    """构造 dict 形态的 LiteLLM 响应。"""
    usage: dict[str, int] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if total_tokens is not None:
        usage["total_tokens"] = total_tokens
    return {
        "choices": [{"message": {"content": "hello"}}],
        "usage": usage,
    }


def _make_obj_response(
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
) -> SimpleNamespace:
    """构造 Pydantic-like 对象形态的 LiteLLM 响应。"""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


# ---------------------------------------------------------------------------
# TokenUsage dataclass 测试
# ---------------------------------------------------------------------------


class TestTokenUsage:
    """TokenUsage dataclass 测试。"""

    def test_fields(self) -> None:
        """字段正确赋值。"""
        usage = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_frozen(self) -> None:
        """frozen=True，不可变。"""
        usage = TokenUsage(100, 50, 150)
        with pytest.raises(AttributeError):
            usage.prompt_tokens = 200  # type: ignore[misc]


class TestCostEstimate:
    """CostEstimate dataclass 测试。"""

    def test_fields(self) -> None:
        """字段正确赋值。"""
        usage = TokenUsage(100, 50, 150)
        cost = CostEstimate(
            usage=usage,
            input_cost=0.1,
            output_cost=0.1,
            total_cost=0.2,
            currency="CNY",
        )
        assert cost.usage is usage
        assert cost.input_cost == 0.1
        assert cost.output_cost == 0.1
        assert cost.total_cost == 0.2
        assert cost.currency == "CNY"

    def test_frozen(self) -> None:
        """frozen=True，不可变。"""
        usage = TokenUsage(100, 50, 150)
        cost = CostEstimate(usage, 0.1, 0.1, 0.2, "CNY")
        with pytest.raises(AttributeError):
            cost.total_cost = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# extract_usage 测试
# ---------------------------------------------------------------------------


class TestExtractUsage:
    """extract_usage 测试。"""

    def test_extract_from_dict(self) -> None:
        """从 dict 响应提取 usage。"""
        resp = _make_dict_response(100, 50, 150)
        usage = extract_usage(resp)
        assert usage is not None
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_extract_from_object(self) -> None:
        """从 Pydantic-like 对象提取 usage。"""
        resp = _make_obj_response(200, 80, 280)
        usage = extract_usage(resp)
        assert usage is not None
        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 80
        assert usage.total_tokens == 280

    def test_extract_no_usage_dict(self) -> None:
        """dict 响应无 usage 字段返回 None。"""
        resp: dict[str, object] = {"choices": []}
        assert extract_usage(resp) is None

    def test_extract_no_usage_object(self) -> None:
        """对象响应无 usage 属性返回 None。"""
        resp = SimpleNamespace(choices=[])
        assert extract_usage(resp) is None

    def test_extract_total_tokens_auto_calc(self) -> None:
        """total_tokens 缺失时自动求和。"""
        resp = _make_dict_response(120, 30, total_tokens=None)
        usage = extract_usage(resp)
        assert usage is not None
        assert usage.total_tokens == 150

    def test_extract_zero_tokens(self) -> None:
        """全零 token 正常返回。"""
        resp = _make_dict_response(0, 0, 0)
        usage = extract_usage(resp)
        assert usage is not None
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# estimate_cost 测试
# ---------------------------------------------------------------------------


class TestEstimateCost:
    """estimate_cost 测试。"""

    def test_basic_calculation(self) -> None:
        """基础成本计算。

        model 定价: input=1/1M, output=2/1M (CNY)
        usage: prompt=100, completion=50
        input_cost = 100/1_000_000 * 1 = 0.0001
        output_cost = 50/1_000_000 * 2 = 0.0001
        total = 0.0002
        """
        model = _make_model(input_price=1.0, output_price=2.0)
        resp = _make_dict_response(100, 50, 150)

        cost = estimate_cost(resp, model)

        assert cost.usage.prompt_tokens == 100
        assert cost.usage.completion_tokens == 50
        assert cost.usage.total_tokens == 150
        assert cost.input_cost == pytest.approx(0.0001)
        assert cost.output_cost == pytest.approx(0.0001)
        assert cost.total_cost == pytest.approx(0.0002)
        assert cost.currency == "CNY"

    def test_zero_price_model(self) -> None:
        """零定价模型成本为零。"""
        model = _make_model(input_price=0.0, output_price=0.0)
        resp = _make_dict_response(1000, 500, 1500)

        cost = estimate_cost(resp, model)

        assert cost.input_cost == 0.0
        assert cost.output_cost == 0.0
        assert cost.total_cost == 0.0

    def test_no_usage_in_response(self) -> None:
        """响应无 usage 字段返回零成本。"""
        model = _make_model(input_price=1.0, output_price=2.0)
        resp: dict[str, object] = {"choices": []}

        cost = estimate_cost(resp, model)

        assert cost.usage.prompt_tokens == 0
        assert cost.usage.completion_tokens == 0
        assert cost.usage.total_tokens == 0
        assert cost.total_cost == 0.0

    def test_object_response(self) -> None:
        """Pydantic 对象形态响应计算正确。"""
        model = _make_model(input_price=3.0, output_price=6.0)
        resp = _make_obj_response(1000, 500, 1500)

        cost = estimate_cost(resp, model)

        assert cost.usage.prompt_tokens == 1000
        assert cost.usage.completion_tokens == 500
        assert cost.input_cost == pytest.approx(0.003)
        assert cost.output_cost == pytest.approx(0.003)
        assert cost.total_cost == pytest.approx(0.006)

    def test_large_token_count(self) -> None:
        """大 token 数量计算正确。"""
        model = _make_model(input_price=0.5, output_price=1.5)
        resp = _make_dict_response(1_000_000, 500_000, 1_500_000)

        cost = estimate_cost(resp, model)

        assert cost.input_cost == pytest.approx(0.5)
        assert cost.output_cost == pytest.approx(0.75)
        assert cost.total_cost == pytest.approx(1.25)

    def test_cost_rounded_to_6_decimals(self) -> None:
        """成本四舍五入至 6 位小数。"""
        model = _make_model(input_price=0.001, output_price=0.001)
        resp = _make_dict_response(1, 1, 2)

        cost = estimate_cost(resp, model)

        assert cost.input_cost == round(0.001 / 1_000_000, 6)
        assert cost.output_cost == round(0.001 / 1_000_000, 6)

    def test_partial_usage_no_total(self) -> None:
        """usage 缺少 total_tokens 时自动求和后计算。"""
        model = _make_model(input_price=1.0, output_price=1.0)
        resp = _make_dict_response(100, 50, total_tokens=None)

        cost = estimate_cost(resp, model)

        assert cost.usage.total_tokens == 150
        assert cost.total_cost == pytest.approx(0.00015)

    def test_usd_currency(self) -> None:
        """USD 币种的模型成本计算。"""
        model = _make_model(input_price=0.15, output_price=0.6, currency="USD")
        resp = _make_dict_response(1_000_000, 500_000, 1_500_000)

        cost = estimate_cost(resp, model)

        assert cost.input_cost == pytest.approx(0.15)
        assert cost.output_cost == pytest.approx(0.3)
        assert cost.total_cost == pytest.approx(0.45)
        assert cost.currency == "USD"

    def test_currency_from_model(self) -> None:
        """币种从 model.currency 读取。"""
        model = _make_model(currency="USD")
        resp = _make_dict_response(100, 50, 150)

        cost = estimate_cost(resp, model)

        assert cost.currency == "USD"

    def test_no_usage_carries_currency(self) -> None:
        """无 usage 时仍携带币种信息。"""
        model = _make_model(currency="USD")
        resp: dict[str, object] = {"choices": []}

        cost = estimate_cost(resp, model)

        assert cost.currency == "USD"
        assert cost.total_cost == 0.0
