"""src.llm.budget 的单元测试。

测试覆盖：
- BudgetConfig: get_daily_limit / get_per_call_limit / convert
- BudgetGuard.check_pre_call: 每日上限阻止 / 未超限放行 / 不限速放行 / 多币种
- BudgetGuard.check_post_call: 单次超限告警 / 每日累计告警 / 不限速跳过
- BudgetExceededError: 属性传递
- 汇率换算
- 边界场景：零成本 / 无日志记录 / 未知币种
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.budget import BudgetConfig, BudgetExceededError, BudgetGuard
from src.llm.cost import CostEstimate, TokenUsage
from src.llm.orm import Base, LlmCallLog, LlmModel
from src.models.enums import LlmModelSource


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_model(
    *,
    currency: str = "CNY",
    input_price: float = 1.0,
    output_price: float = 2.0,
    context_window: int = 4096,
    max_output_tokens: int = 4096,
    model_code: str = "test-model",
) -> LlmModel:
    """构造测试用 LlmModel 实例（不持久化）。"""
    return LlmModel(
        provider_id=1,
        model_code=model_code,
        litellm_model=f"openai/{model_code}",
        display_name=model_code,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        input_price_per_1m=input_price,
        output_price_per_1m=output_price,
        currency=currency,
        is_enabled=True,
        is_default=True,
        source=LlmModelSource.PRESET,
    )


def _insert_call_log(
    session: Session,
    *,
    cost_amount: float,
    cost_currency: str,
    days_ago: int = 0,
) -> None:
    """向 kb_llm_call_log 插入一条成功调用日志。"""
    from datetime import timedelta

    called_at = datetime.utcnow() - timedelta(days=days_ago)
    log = LlmCallLog(
        trace_id="test",
        provider_id=1,
        model_id=1,
        is_success=True,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        total_tokens=100,
        input_tokens=60,
        output_tokens=40,
        latency_ms=500,
        called_at=called_at,
    )
    session.add(log)
    session.flush()


class TestBudgetConfig:
    """BudgetConfig 配置测试。"""

    def test_get_daily_limit_cny(self) -> None:
        """获取 CNY 每日上限。"""
        config = BudgetConfig(daily_limit_cny=0.50, daily_limit_usd=0.10)
        assert config.get_daily_limit("CNY") == 0.50

    def test_get_daily_limit_usd(self) -> None:
        """获取 USD 每日上限。"""
        config = BudgetConfig(daily_limit_cny=0.50, daily_limit_usd=0.10)
        assert config.get_daily_limit("USD") == 0.10

    def test_get_daily_limit_unknown_currency(self) -> None:
        """未知币种返回 0。"""
        config = BudgetConfig(daily_limit_cny=0.50)
        assert config.get_daily_limit("EUR") == 0.0

    def test_get_per_call_limit_cny(self) -> None:
        """获取 CNY 单次上限。"""
        config = BudgetConfig(per_call_limit_cny=0.10)
        assert config.get_per_call_limit("CNY") == 0.10

    def test_get_per_call_limit_usd(self) -> None:
        """获取 USD 单次上限。"""
        config = BudgetConfig(per_call_limit_usd=0.05)
        assert config.get_per_call_limit("USD") == 0.05

    def test_get_per_call_limit_unknown_currency(self) -> None:
        """未知币种返回 0。"""
        config = BudgetConfig(per_call_limit_cny=0.10)
        assert config.get_per_call_limit("EUR") == 0.0

    def test_convert_same_currency(self) -> None:
        """相同币种不换算。"""
        config = BudgetConfig()
        assert config.convert(1.5, "CNY", "CNY") == 1.5

    def test_convert_usd_to_cny(self) -> None:
        """USD -> CNY 换算。"""
        config = BudgetConfig()
        assert config.convert(1.0, "USD", "CNY") == pytest.approx(7.2)

    def test_convert_cny_to_usd(self) -> None:
        """CNY -> USD 换算。"""
        config = BudgetConfig()
        assert config.convert(7.2, "CNY", "USD") == pytest.approx(1.0)

    def test_convert_unknown_rate(self) -> None:
        """未知汇率返回 0。"""
        config = BudgetConfig()
        assert config.convert(1.0, "EUR", "CNY") == 0.0

    def test_convert_custom_fx_rates(self) -> None:
        """自定义汇率表。"""
        config = BudgetConfig(
            fx_rates={"USD_TO_CNY": 7.0, "CNY_TO_USD": 1.0 / 7.0},
        )
        assert config.convert(1.0, "USD", "CNY") == pytest.approx(7.0)


class TestCheckPreCall:
    """BudgetGuard.check_pre_call 测试。"""

    def test_no_limit_passes(self, session: Session) -> None:
        """每日上限为 0（不限）时直接放行。"""
        config = BudgetConfig(daily_limit_cny=0.0)
        guard = BudgetGuard(session, config)
        model = _make_model()
        guard.check_pre_call(model)  # 不抛异常

    def test_under_limit_passes(self, session: Session) -> None:
        """当日消耗 + 预估 < 上限时放行。"""
        _insert_call_log(session, cost_amount=0.10, cost_currency="CNY")
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=1.0, output_price=2.0)
        # 预估: (4096/1M)*1 + (4096/1M)*2 = 0.004096 + 0.008192 = 0.012288
        # 已消耗 0.10 + 预估 0.012288 = 0.112288 < 0.50
        guard.check_pre_call(model)

    def test_over_limit_raises(self, session: Session) -> None:
        """当日消耗 + 预估 > 上限时抛 BudgetExceededError。"""
        _insert_call_log(session, cost_amount=0.49, cost_currency="CNY")
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=100.0, output_price=200.0)
        # 预估: (4096/1M)*100 + (4096/1M)*200 = 0.4096 + 0.8192 = 1.2288
        # 已消耗 0.49 + 预估 1.2288 = 1.7188 > 0.50
        with pytest.raises(BudgetExceededError) as exc_info:
            guard.check_pre_call(model)
        assert exc_info.value.daily_limit == 0.50
        assert exc_info.value.daily_spent == pytest.approx(0.49)
        assert exc_info.value.currency == "CNY"

    def test_usd_limit(self, session: Session) -> None:
        """USD 币种的每日上限检查。"""
        _insert_call_log(session, cost_amount=0.05, cost_currency="USD")
        config = BudgetConfig(daily_limit_usd=0.10)
        guard = BudgetGuard(session, config)
        model = _make_model(
            currency="USD",
            input_price=100.0,
            output_price=200.0,
        )
        # 预估: (4096/1M)*100 + (4096/1M)*200 = 1.2288
        # 已消耗 0.05 + 预估 1.2288 = 1.2788 > 0.10
        with pytest.raises(BudgetExceededError) as exc_info:
            guard.check_pre_call(model)
        assert exc_info.value.currency == "USD"
        assert exc_info.value.daily_limit == 0.10

    def test_cny_logs_not_counted_for_usd(self, session: Session) -> None:
        """CNY 消耗不计入 USD 上限。"""
        _insert_call_log(session, cost_amount=100.0, cost_currency="CNY")
        config = BudgetConfig(daily_limit_usd=0.10)
        guard = BudgetGuard(session, config)
        model = _make_model(currency="USD", input_price=1.0, output_price=2.0)
        # USD 已消耗 0 + 预估 0.012288 < 0.10
        guard.check_pre_call(model)

    def test_old_logs_not_counted(self, session: Session) -> None:
        """历史日期的日志不计入当日消耗。"""
        _insert_call_log(session, cost_amount=10.0, cost_currency="CNY", days_ago=1)
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=1.0, output_price=2.0)
        # 当日消耗 0 + 预估 0.012288 < 0.50
        guard.check_pre_call(model)

    def test_failed_calls_not_counted(self, session: Session) -> None:
        """失败调用（is_success=False）不计入消耗。"""

        log = LlmCallLog(
            trace_id="test",
            provider_id=1,
            model_id=1,
            is_success=False,
            cost_amount=10.0,
            cost_currency="CNY",
            called_at=datetime.utcnow(),
        )
        session.add(log)
        session.flush()
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=1.0, output_price=2.0)
        guard.check_pre_call(model)

    def test_zero_price_model_passes(self, session: Session) -> None:
        """定价为 0 的模型预估成本为 0，不会超限。"""
        _insert_call_log(session, cost_amount=0.49, cost_currency="CNY")
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=0.0, output_price=0.0)
        # 预估 0 + 已消耗 0.49 < 0.50
        guard.check_pre_call(model)


class TestCheckPostCall:
    """BudgetGuard.check_post_call 测试。"""

    def test_no_limit_skips(self, session: Session) -> None:
        """所有上限为 0 时跳过检查。"""
        config = BudgetConfig()
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100, 50, 150),
            input_cost=0.001,
            output_cost=0.002,
            total_cost=0.003,
            currency="CNY",
        )
        guard.check_post_call(cost)  # 不抛异常

    def test_per_call_under_limit(self, session: Session) -> None:
        """单次成本低于上限时不告警。"""
        config = BudgetConfig(per_call_limit_cny=0.10)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100, 50, 150),
            input_cost=0.001,
            output_cost=0.002,
            total_cost=0.003,
            currency="CNY",
        )
        guard.check_post_call(cost)

    def test_per_call_over_limit_warns(self, session: Session) -> None:
        """单次成本超过上限时记录 WARNING。"""
        config = BudgetConfig(per_call_limit_cny=0.01)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100000, 50000, 150000),
            input_cost=0.05,
            output_cost=0.10,
            total_cost=0.15,
            currency="CNY",
        )
        with patch("src.llm.budget.logger") as mock_logger:
            guard.check_post_call(cost)
            mock_logger.warning.assert_any_call(
                "单次调用成本超限告警: %.4f %s > 单次上限 %.4f %s",
                0.15,
                "CNY",
                0.01,
                "CNY",
            )

    def test_daily_over_limit_warns(self, session: Session) -> None:
        """每日累计超过上限时记录 WARNING。"""
        _insert_call_log(session, cost_amount=0.48, cost_currency="CNY")
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100, 50, 150),
            input_cost=0.01,
            output_cost=0.02,
            total_cost=0.03,
            currency="CNY",
        )
        # 本次写入 call_log 后累计 = 0.48 + 0.03 = 0.51 > 0.50
        # 但 check_post_call 查的是 DB 中已有日志（不含本次，因为本次可能还没 flush）
        # 所以这里测试的是：DB 中已有 0.48，本次 cost 0.03，
        # check_post_call 查 DB 得到 0.48（不含本次），不超限
        # 改为：先插入足够多的日志使其超限
        _insert_call_log(session, cost_amount=0.50, cost_currency="CNY")
        with patch("src.llm.budget.logger") as mock_logger:
            guard.check_post_call(cost)
            mock_logger.warning.assert_any_call(
                "每日成本超限告警: 当日累计 %.4f %s > 每日上限 %.4f %s",
                pytest.approx(0.98),
                "CNY",
                0.50,
                "CNY",
            )

    def test_usd_per_call_over_limit(self, session: Session) -> None:
        """USD 单次超限告警。"""
        config = BudgetConfig(per_call_limit_usd=0.01)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100000, 50000, 150000),
            input_cost=0.05,
            output_cost=0.10,
            total_cost=0.15,
            currency="USD",
        )
        with patch("src.llm.budget.logger") as mock_logger:
            guard.check_post_call(cost)
            mock_logger.warning.assert_any_call(
                "单次调用成本超限告警: %.4f %s > 单次上限 %.4f %s",
                0.15,
                "USD",
                0.01,
                "USD",
            )

    def test_both_limits_checked(self, session: Session) -> None:
        """单次和每日上限同时检查。"""
        _insert_call_log(session, cost_amount=0.60, cost_currency="CNY")
        config = BudgetConfig(daily_limit_cny=0.50, per_call_limit_cny=0.01)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100000, 50000, 150000),
            input_cost=0.05,
            output_cost=0.10,
            total_cost=0.15,
            currency="CNY",
        )
        with patch("src.llm.budget.logger") as mock_logger:
            guard.check_post_call(cost)
            assert mock_logger.warning.call_count == 2

    def test_empty_db(self, session: Session) -> None:
        """空数据库时每日检查不报错。"""
        config = BudgetConfig(daily_limit_cny=0.50)
        guard = BudgetGuard(session, config)
        cost = CostEstimate(
            usage=TokenUsage(100, 50, 150),
            input_cost=0.001,
            output_cost=0.002,
            total_cost=0.003,
            currency="CNY",
        )
        # DB 为空，当日消耗 0 < 0.50，无告警
        with patch("src.llm.budget.logger") as mock_logger:
            guard.check_post_call(cost)
            mock_logger.warning.assert_not_called()


class TestBudgetExceededError:
    """BudgetExceededError 异常测试。"""

    def test_attributes(self) -> None:
        """异常属性正确传递。"""
        err = BudgetExceededError(
            "test",
            daily_limit=0.50,
            daily_spent=0.30,
            estimated_cost=0.25,
            currency="CNY",
        )
        assert err.daily_limit == 0.50
        assert err.daily_spent == 0.30
        assert err.estimated_cost == 0.25
        assert err.currency == "CNY"

    def test_str_representation(self) -> None:
        """异常字符串包含关键信息。"""
        err = BudgetExceededError(
            "test",
            daily_limit=0.50,
            daily_spent=0.30,
            estimated_cost=0.25,
            currency="CNY",
        )
        s = str(err)
        assert "0.3000" in s
        assert "0.2500" in s
        assert "0.5000" in s
        assert "CNY" in s


class TestEstimateMaxCallCost:
    """BudgetGuard._estimate_max_call_cost 测试。"""

    def test_basic_estimation(self, session: Session) -> None:
        """基本成本估算。"""
        config = BudgetConfig()
        guard = BudgetGuard(session, config)
        model = _make_model(
            input_price=1.0,
            output_price=2.0,
            context_window=4096,
            max_output_tokens=4096,
        )
        # (4096/1M)*1 + (4096/1M)*2 = 0.004096 + 0.008192 = 0.012288
        cost = guard._estimate_max_call_cost(model)
        assert cost == pytest.approx(0.012288)

    def test_zero_price(self, session: Session) -> None:
        """零定价模型估算为 0。"""
        config = BudgetConfig()
        guard = BudgetGuard(session, config)
        model = _make_model(input_price=0.0, output_price=0.0)
        cost = guard._estimate_max_call_cost(model)
        assert cost == 0.0

    def test_large_context(self, session: Session) -> None:
        """大上下文窗口模型估算。"""
        config = BudgetConfig()
        guard = BudgetGuard(session, config)
        model = _make_model(
            input_price=0.5,
            output_price=1.0,
            context_window=128000,
            max_output_tokens=4096,
        )
        # (128000/1M)*0.5 + (4096/1M)*1.0 = 0.064 + 0.004096 = 0.068096
        cost = guard._estimate_max_call_cost(model)
        assert cost == pytest.approx(0.068096)
