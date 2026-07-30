"""src.api.metrics_service 的单元测试。

测试覆盖：
- list_runs: 分页、日期过滤、状态过滤、空结果
- get_run_detail: 含节点指标、无节点指标、不存在
- get_summary: 默认 7 天、30 天、空日期补零、参数校验
- get_llm_cost: 有数据分组、无数据、CNY/USD 分离
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.api.metrics_service import (
    get_llm_cost,
    get_run_detail,
    get_summary,
    list_runs,
)
from src.common.exceptions import BizException, ErrorCode
from src.llm.orm import Base, LlmCallLog, LlmModel, LlmProvider
from src.models.enums import LlmAuthType, LlmModelSource, LlmProviderType
from src.models.metrics import NodeMetric, PipelineRun


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_run(
    *,
    trace_id: str = "trace001",
    status: str = "success",
    started_at: datetime | None = None,
    source_count: int = 10,
    article_count: int = 5,
    saved_count: int = 3,
    review_passed: bool = True,
    iteration: int = 1,
    total_cost_yuan: float = 0.5,
) -> PipelineRun:
    """创建 PipelineRun 实例。"""
    return PipelineRun(
        trace_id=trace_id,
        status=status,
        started_at=started_at or datetime.now(UTC).replace(tzinfo=None),
        ended_at=started_at or datetime.now(UTC).replace(tzinfo=None),
        duration_ms=1000,
        source_count=source_count,
        analysis_count=8,
        article_count=article_count,
        saved_count=saved_count,
        human_flagged=0,
        review_passed=review_passed,
        iteration=iteration,
        total_cost_yuan=total_cost_yuan,
    )


def _create_node_metric(
    run_id: int,
    *,
    node_name: str = "collect",
    duration_ms: int = 500,
) -> NodeMetric:
    """创建 NodeMetric 实例。"""
    return NodeMetric(
        run_id=run_id,
        trace_id="trace001",
        node_name=node_name,
        duration_ms=duration_ms,
        cost_data={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        review_passed=None,
        iteration=None,
        error="",
    )


def _create_provider(code: str = "test") -> LlmProvider:
    """创建 LlmProvider 实例。"""
    return LlmProvider(
        provider_code=code,
        display_name=code.title(),
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        is_enabled=True,
        priority=100,
        timeout_seconds=30,
        max_retries=3,
        rpm_limit=0,
    )


def _create_model(provider_id: int, code: str = "test-model") -> LlmModel:
    """创建 LlmModel 实例。"""
    return LlmModel(
        provider_id=provider_id,
        model_code=code,
        litellm_model=f"openai/{code}",
        display_name=code,
        context_window=4096,
        max_output_tokens=4096,
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
        supports_reasoning=False,
        input_price_per_1m=1.0,
        output_price_per_1m=2.0,
        currency="CNY",
        is_enabled=True,
        is_default=True,
        source=LlmModelSource.PRESET,
    )


def _create_call_log(
    provider_id: int,
    model_id: int,
    *,
    is_success: bool = True,
    cost_amount: float = 0.01,
    cost_currency: str = "CNY",
    input_tokens: int = 100,
    output_tokens: int = 50,
    total_tokens: int = 150,
) -> LlmCallLog:
    """创建 LlmCallLog 实例。"""
    return LlmCallLog(
        trace_id="trace001",
        provider_id=provider_id,
        model_id=model_id,
        is_success=is_success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        latency_ms=500,
        error_msg=None,
    )


# ---------------------------------------------------------------------------
# list_runs 测试
# ---------------------------------------------------------------------------


class TestListRuns:
    """list_runs 测试。"""

    def test_list_runs_default_pagination(self, session: Session) -> None:
        """默认分页返回第一页。"""
        for i in range(25):
            now = datetime.now(UTC).replace(tzinfo=None)
            session.add(
                _create_run(
                    trace_id=f"trace{i:03d}",
                    started_at=now - timedelta(minutes=i),
                )
            )
            session.flush()

        items, total = list_runs(session, page=1, size=20)
        assert total == 25
        assert len(items) == 20

    def test_list_runs_second_page(self, session: Session) -> None:
        """第二页返回剩余条目。"""
        for i in range(25):
            now = datetime.now(UTC).replace(tzinfo=None)
            session.add(
                _create_run(
                    trace_id=f"trace{i:03d}",
                    started_at=now - timedelta(minutes=i),
                )
            )
        session.flush()

        items, total = list_runs(session, page=2, size=20)
        assert total == 25
        assert len(items) == 5

    def test_list_runs_status_filter(self, session: Session) -> None:
        """状态过滤。"""
        session.add(_create_run(trace_id="t1", status="success"))
        session.add(_create_run(trace_id="t2", status="error"))
        session.add(_create_run(trace_id="t3", status="success"))
        session.flush()

        items, total = list_runs(session, page=1, size=20, status="error")
        assert total == 1
        assert items[0].trace_id == "t2"

    def test_list_runs_date_filter(self, session: Session) -> None:
        """日期过滤。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(_create_run(trace_id="old", started_at=now - timedelta(days=10)))
        session.add(_create_run(trace_id="new", started_at=now - timedelta(days=1)))
        session.flush()

        start = now - timedelta(days=2)
        items, total = list_runs(session, page=1, size=20, start_date=start)
        assert total == 1
        assert items[0].trace_id == "new"

    def test_list_runs_empty(self, session: Session) -> None:
        """空结果。"""
        items, total = list_runs(session, page=1, size=20)
        assert total == 0
        assert items == []

    def test_list_runs_invalid_page(self, session: Session) -> None:
        """page < 1 抛出 PARAM_ERROR。"""
        with pytest.raises(BizException) as exc_info:
            list_runs(session, page=0, size=20)
        assert exc_info.value.error_code == ErrorCode.PARAM_ERROR

    def test_list_runs_invalid_size(self, session: Session) -> None:
        """size > 100 抛出 PARAM_ERROR。"""
        with pytest.raises(BizException) as exc_info:
            list_runs(session, page=1, size=200)
        assert exc_info.value.error_code == ErrorCode.PARAM_ERROR


# ---------------------------------------------------------------------------
# get_run_detail 测试
# ---------------------------------------------------------------------------


class TestGetRunDetail:
    """get_run_detail 测试。"""

    def test_get_run_detail_with_nodes(self, session: Session) -> None:
        """含节点指标的运行详情。"""
        run = _create_run()
        session.add(run)
        session.flush()

        session.add(_create_node_metric(run.id, node_name="collect", duration_ms=100))
        session.add(_create_node_metric(run.id, node_name="analyze", duration_ms=200))
        session.flush()

        detail = get_run_detail(session, run.id)
        assert detail.id == run.id
        assert len(detail.nodes) == 2
        assert detail.nodes[0].node_name == "collect"
        assert detail.nodes[1].node_name == "analyze"

    def test_get_run_detail_no_nodes(self, session: Session) -> None:
        """无节点指标的运行详情。"""
        run = _create_run()
        session.add(run)
        session.flush()

        detail = get_run_detail(session, run.id)
        assert detail.id == run.id
        assert detail.nodes == []

    def test_get_run_detail_not_found(self, session: Session) -> None:
        """不存在的运行抛出 NOT_FOUND。"""
        with pytest.raises(BizException) as exc_info:
            get_run_detail(session, 9999)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND


# ---------------------------------------------------------------------------
# get_summary 测试
# ---------------------------------------------------------------------------


class TestGetSummary:
    """get_summary 测试。"""

    def test_get_summary_default_7_days(self, session: Session) -> None:
        """默认 7 天汇总。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            _create_run(
                trace_id="t1",
                status="success",
                started_at=now - timedelta(days=1),
                article_count=5,
                saved_count=3,
                review_passed=True,
            )
        )
        session.flush()

        result = get_summary(session, days=7)
        assert len(result.daily) == 7
        assert result.totals.total_runs == 1
        assert result.totals.total_success == 1
        assert result.totals.total_article_count == 5

    def test_get_summary_30_days(self, session: Session) -> None:
        """30 天汇总。"""
        result = get_summary(session, days=30)
        assert len(result.daily) == 30

    def test_get_summary_day_with_no_runs(self, session: Session) -> None:
        """无运行的日期补零。"""
        result = get_summary(session, days=7)
        assert len(result.daily) == 7
        for d in result.daily:
            assert d.run_count == 0
            assert d.total_cost_yuan == 0.0

    def test_get_summary_days_zero_raises(self, session: Session) -> None:
        """days=0 抛出 PARAM_ERROR。"""
        with pytest.raises(BizException) as exc_info:
            get_summary(session, days=0)
        assert exc_info.value.error_code == ErrorCode.PARAM_ERROR

    def test_get_summary_days_capped_at_90(self, session: Session) -> None:
        """days=120 截断为 90。"""
        result = get_summary(session, days=120)
        assert len(result.daily) == 90

    def test_get_summary_avg_pass_rate(self, session: Session) -> None:
        """审核通过率计算。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            _create_run(
                trace_id="t1",
                status="success",
                started_at=now - timedelta(days=1),
                review_passed=True,
            )
        )
        session.add(
            _create_run(
                trace_id="t2",
                status="human_flagged",
                started_at=now - timedelta(days=1),
                review_passed=False,
            )
        )
        session.flush()

        result = get_summary(session, days=7)
        assert result.totals.total_runs == 2
        assert result.totals.avg_review_pass_rate == 0.5


# ---------------------------------------------------------------------------
# get_llm_cost 测试
# ---------------------------------------------------------------------------


class TestGetLlmCost:
    """get_llm_cost 测试。"""

    def test_get_llm_cost_with_data(self, session: Session) -> None:
        """有数据的成本 breakdown。"""
        provider = _create_provider("deepseek")
        session.add(provider)
        session.flush()

        model = _create_model(provider.id, "deepseek-chat")
        session.add(model)
        session.flush()

        session.add(_create_call_log(provider.id, model.id, cost_amount=0.01, cost_currency="CNY"))
        session.add(_create_call_log(provider.id, model.id, cost_amount=0.02, cost_currency="CNY"))
        session.flush()

        result = get_llm_cost(session, days=7)
        assert len(result.items) == 1
        item = result.items[0]
        assert item.provider_code == "deepseek"
        assert item.model_code == "deepseek-chat"
        assert item.call_count == 2
        assert item.total_cost == pytest.approx(0.03)
        assert result.grand_total.total_cost_cny == pytest.approx(0.03)
        assert result.grand_total.total_calls == 2

    def test_get_llm_cost_no_data(self, session: Session) -> None:
        """无数据返回空列表和零总计。"""
        result = get_llm_cost(session, days=7)
        assert result.items == []
        assert result.grand_total.total_cost_cny == 0.0
        assert result.grand_total.total_cost_usd == 0.0
        assert result.grand_total.total_calls == 0

    def test_get_llm_cost_currency_split(self, session: Session) -> None:
        """CNY/USD 分离。"""
        provider = _create_provider("openai")
        session.add(provider)
        session.flush()

        model_cny = _create_model(provider.id, "model-cny")
        model_cny.currency = "CNY"
        session.add(model_cny)
        session.flush()

        model_usd = _create_model(provider.id, "model-usd")
        model_usd.currency = "USD"
        session.add(model_usd)
        session.flush()

        session.add(
            _create_call_log(
                provider.id, model_cny.id, cost_amount=0.5, cost_currency="CNY"
            )
        )
        session.add(
            _create_call_log(
                provider.id, model_usd.id, cost_amount=0.3, cost_currency="USD"
            )
        )
        session.flush()

        result = get_llm_cost(session, days=7)
        assert len(result.items) == 2
        assert result.grand_total.total_cost_cny == pytest.approx(0.5)
        assert result.grand_total.total_cost_usd == pytest.approx(0.3)

    def test_get_llm_cost_sorted_desc(self, session: Session) -> None:
        """按 total_cost 降序排序。"""
        provider = _create_provider("test")
        session.add(provider)
        session.flush()

        model_cheap = _create_model(provider.id, "cheap")
        session.add(model_cheap)
        session.flush()

        model_expensive = _create_model(provider.id, "expensive")
        session.add(model_expensive)
        session.flush()

        session.add(_create_call_log(provider.id, model_cheap.id, cost_amount=0.01))
        session.add(_create_call_log(provider.id, model_expensive.id, cost_amount=1.0))
        session.flush()

        result = get_llm_cost(session, days=7)
        assert len(result.items) == 2
        assert result.items[0].total_cost > result.items[1].total_cost
