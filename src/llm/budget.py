"""LLM 调用预算控制 Hook。

在 :func:`src.llm.client.chat_completion` 调用前后执行预算检查：

- **调用前（pre-call）**：查询当日已消耗成本，若加上预估成本后会超过每日上限，
  则阻止调用并抛出 :class:`BudgetExceededError`。
- **调用后（post-call）**：检查单次调用成本是否超过单次上限，超过则发出告警日志。
  同时检查当日累计成本是否达到每日上限，达到则发出告警日志。

预算上限通过 :class:`BudgetConfig` 配置，支持多币种（CNY / USD）分别设限。
未配置的币种上限默认为 0（不限速）。

汇率处理：
    当调用成本币种与预算币种不一致时，使用 :class:`BudgetConfig` 中的
    ``fx_rates`` 进行换算。默认汇率仅作估算，可通过环境变量覆盖。

使用方式::

    from src.llm.budget import BudgetGuard, BudgetConfig

    guard = BudgetGuard(session, config)
    guard.check_pre_call(model)          # 超限抛 BudgetExceededError
    resp = chat_completion(provider, model, messages, session=session)
    guard.check_post_call(resp.cost)     # 超限告警（不抛异常）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.llm.cost import CostEstimate
from src.llm.orm import LlmCallLog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.llm.orm import LlmModel

logger = logging.getLogger(__name__)

# 默认汇率（1 USD -> X CNY），仅供参考，可通过 BudgetConfig.fx_rates 覆盖
_DEFAULT_FX_RATES: dict[str, float] = {
    "USD_TO_CNY": 7.2,
    "CNY_TO_USD": 1.0 / 7.2,
}


class BudgetExceededError(Exception):
    """预算超限异常，调用前检查不通过时抛出。

    Attributes:
        daily_limit: 每日上限金额（预算币种）。
        daily_spent: 当日已消耗金额（预算币种）。
        estimated_cost: 本次调用预估成本（预算币种）。
        currency: 预算币种。
    """

    def __init__(
        self,
        message: str,
        *,
        daily_limit: float,
        daily_spent: float,
        estimated_cost: float,
        currency: str,
    ) -> None:
        """初始化预算超限异常。

        Args:
            message: 异常消息。
            daily_limit: 每日上限金额。
            daily_spent: 当日已消耗金额。
            estimated_cost: 本次调用预估成本。
            currency: 预算币种。
        """
        super().__init__(message)
        self.daily_limit = daily_limit
        self.daily_spent = daily_spent
        self.estimated_cost = estimated_cost
        self.currency = currency

    def __str__(self) -> str:
        """返回包含预算详情的异常描述。"""
        return (
            f"预算超限: 当日已消耗 {self.daily_spent:.4f} {self.currency} "
            f"+ 预估 {self.estimated_cost:.4f} {self.currency} "
            f"> 每日上限 {self.daily_limit:.4f} {self.currency}"
        )


@dataclass(frozen=True)
class BudgetConfig:
    """预算控制配置。

    通过环境变量加载，详见 :func:`src.config.settings.get_settings`。

    Attributes:
        daily_limit_cny: 每日成本上限（人民币），0 表示不限。
        daily_limit_usd: 每日成本上限（美元），0 表示不限。
        per_call_limit_cny: 单次调用成本上限（人民币），0 表示不限。
        per_call_limit_usd: 单次调用成本上限（美元），0 表示不限。
        fx_rates: 汇率表，键格式为 ``"USD_TO_CNY"``，值为汇率。
    """

    daily_limit_cny: float = 0.0
    daily_limit_usd: float = 0.0
    per_call_limit_cny: float = 0.0
    per_call_limit_usd: float = 0.0
    fx_rates: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_FX_RATES))

    def get_daily_limit(self, currency: str) -> float:
        """获取指定币种的每日上限。

        Args:
            currency: 币种代码（CNY / USD）。

        Returns:
            每日上限金额，0 表示不限。
        """
        if currency == "CNY":
            return self.daily_limit_cny
        if currency == "USD":
            return self.daily_limit_usd
        return 0.0

    def get_per_call_limit(self, currency: str) -> float:
        """获取指定币种的单次调用上限。

        Args:
            currency: 币种代码（CNY / USD）。

        Returns:
            单次上限金额，0 表示不限。
        """
        if currency == "CNY":
            return self.per_call_limit_cny
        if currency == "USD":
            return self.per_call_limit_usd
        return 0.0

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """将金额从一种币种换算为另一种。

        若两端币种相同则直接返回。否则查 ``fx_rates`` 表换算。

        Args:
            amount: 待换算金额。
            from_currency: 源币种代码。
            to_currency: 目标币种代码。

        Returns:
            换算后的金额。若无对应汇率，返回 0 并记录告警。
        """
        if from_currency == to_currency:
            return amount

        key = f"{from_currency}_TO_{to_currency}"
        rate = self.fx_rates.get(key)
        if rate is None:
            logger.warning(
                "无 %s -> %s 汇率，成本换算返回 0",
                from_currency,
                to_currency,
            )
            return 0.0
        return amount * rate


class BudgetGuard:
    """预算控制守卫，在 LLM 调用前后执行预算检查。

    预算币种：以调用方传入的模型 ``currency`` 为基准。若模型为 CNY 计费，
    则检查 CNY 上限；若为 USD 计费，则检查 USD 上限。

    每日消耗查询：从 ``kb_llm_call_log`` 表汇总当日所有成功调用的
    ``cost_amount``（按 ``cost_currency`` 分组），不区分供应商/模型。

    Attributes:
        session: SQLAlchemy Session，用于查询当日消耗。
        config: 预算配置。
    """

    def __init__(self, session: Session, config: BudgetConfig) -> None:
        """初始化预算守卫。

        Args:
            session: SQLAlchemy Session。
            config: 预算配置。
        """
        self._session = session
        self._config = config

    def check_pre_call(self, model: LlmModel) -> None:
        """调用前检查：预估本次调用成本是否会超过每日上限。

        由于调用前无法得知实际 token 消耗，使用模型定价的「单次最大输入+输出」
        作为保守预估：``max_output_tokens`` 的 token 成本 + 一个假设的
        ``context_window`` 满载输入成本。若该预估值 + 当日已消耗 > 每日上限，
        则抛出 :class:`BudgetExceededError`。

        若该币种的每日上限为 0（不限），直接返回。

        Args:
            model: 即将调用的模型 ORM 对象（含定价和币种信息）。

        Raises:
            BudgetExceededError: 预估后超出每日上限。
        """
        currency = getattr(model, "currency", "CNY") or "CNY"
        daily_limit = self._config.get_daily_limit(currency)
        if daily_limit <= 0:
            return

        estimated_cost = self._estimate_max_call_cost(model)
        daily_spent = self._get_daily_spent(currency)

        if daily_spent + estimated_cost > daily_limit:
            logger.warning(
                "预算超限（pre-call）: 当日已消耗 %.4f %s + 预估 %.4f %s "
                "> 上限 %.4f %s，阻止调用 model=%s",
                daily_spent,
                currency,
                estimated_cost,
                currency,
                daily_limit,
                currency,
                getattr(model, "model_code", "unknown"),
            )
            raise BudgetExceededError(
                str(self),
                daily_limit=daily_limit,
                daily_spent=daily_spent,
                estimated_cost=estimated_cost,
                currency=currency,
            )

    def check_post_call(self, cost: CostEstimate) -> None:
        """调用后检查：单次超限告警 + 每日累计告警。

        本方法**不抛异常**，仅记录 ``WARNING`` 级别日志，供运维监控。

        检查项：
            1. 单次调用成本 > 单次上限 -> 告警
            2. 当日累计成本 > 每日上限 -> 告警

        若对应币种的上限为 0（不限），跳过检查。

        Args:
            cost: 本次调用的成本估算结果。
        """
        currency = cost.currency
        spent = cost.total_cost

        # 单次上限检查
        per_call_limit = self._config.get_per_call_limit(currency)
        if per_call_limit > 0 and spent > per_call_limit:
            logger.warning(
                "单次调用成本超限告警: %.4f %s > 单次上限 %.4f %s",
                spent,
                currency,
                per_call_limit,
                currency,
            )

        # 每日累计检查（含本次调用）
        daily_limit = self._config.get_daily_limit(currency)
        if daily_limit > 0:
            daily_spent = self._get_daily_spent(currency)
            if daily_spent > daily_limit:
                logger.warning(
                    "每日成本超限告警: 当日累计 %.4f %s > 每日上限 %.4f %s",
                    daily_spent,
                    currency,
                    daily_limit,
                    currency,
                )

    def _get_daily_spent(self, currency: str) -> float:
        """查询当日指定币种的已消耗总成本。

        从 ``kb_llm_call_log`` 表汇总当日（UTC 日期）所有成功调用，
        按 ``cost_currency = currency`` 过滤，对 ``cost_amount`` 求和。

        Args:
            currency: 币种代码。

        Returns:
            当日已消耗总成本。无记录时返回 0.0。
        """
        today = datetime.utcnow().date()
        stmt = (
            select(func.coalesce(func.sum(LlmCallLog.cost_amount), 0.0))
            .where(
                LlmCallLog.is_deleted == False,  # noqa: E712
                LlmCallLog.is_success == True,  # noqa: E712
                LlmCallLog.cost_currency == currency,
                func.date(LlmCallLog.called_at) == today,
            )
        )
        result = self._session.execute(stmt).scalar()
        return float(result) if result is not None else 0.0

    def _estimate_max_call_cost(self, model: LlmModel) -> float:
        """估算单次调用的最大可能成本。

        使用模型的 ``context_window`` 作为最大输入 token 数，
        ``max_output_tokens`` 作为最大输出 token 数，按定价计算成本。

        Args:
            model: 模型 ORM 对象。

        Returns:
            预估最大成本（模型币种）。
        """
        max_input = getattr(model, "context_window", 4096)
        max_output = getattr(model, "max_output_tokens", 4096)
        input_price = float(getattr(model, "input_price_per_1m", 0.0))
        output_price = float(getattr(model, "output_price_per_1m", 0.0))

        input_cost = (max_input / 1_000_000) * input_price
        output_cost = (max_output / 1_000_000) * output_price
        return round(input_cost + output_cost, 6)


__all__ = [
    "BudgetConfig",
    "BudgetExceededError",
    "BudgetGuard",
]
