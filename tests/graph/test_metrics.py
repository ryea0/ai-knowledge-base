"""src.graph.metrics 模块的单元测试。

测试覆盖：
- MetricsCollector: on_workflow_start / on_node_end / on_workflow_end / persist
- with_metrics 装饰器: 正常执行 / 异常传播 / 无 collector 时透传
- ContextVar 注入: set / get / reset
- _compute_summary: 各终态的汇总计算
- _extract_node_cost: cost_tracker 提取
- 端到端: build_graph + with_metrics + mock 节点
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from src.graph.metrics import (
    MetricsCollector,
    NodeMetricRecord,
    get_metrics_collector,
    metrics_collector_var,
    set_metrics_collector,
    with_metrics,
)

# ---------------------------------------------------------------------------
# MetricsCollector 基础测试
# ---------------------------------------------------------------------------


class TestMetricsCollectorLifecycle:
    """MetricsCollector 生命周期测试。"""

    def test_on_workflow_start_sets_started_at(self) -> None:
        """on_workflow_start 设置 started_at。"""
        collector = MetricsCollector(trace_id="abcd1234")
        assert collector.started_at is None

        collector.on_workflow_start()
        assert collector.started_at is not None

    def test_on_workflow_end_sets_ended_at(self) -> None:
        """on_workflow_end 设置 ended_at。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})
        assert collector.ended_at is not None

    def test_on_node_end_appends_record(self) -> None:
        """on_node_end 追加一条节点记录。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_node_end(
            node_name="collect",
            output={"sources": [{"title": "t"}]},
            duration_ms=100.5,
        )
        assert len(collector.node_records) == 1
        record = collector.node_records[0]
        assert record.node_name == "collect"
        assert record.duration_ms == 100.5
        assert record.error is None
        assert record.output == {"sources": [{"title": "t"}]}

    def test_on_node_end_with_error(self) -> None:
        """on_node_end 记录异常。"""
        collector = MetricsCollector(trace_id="abcd1234")
        exc = RuntimeError("boom")
        collector.on_node_end(
            node_name="analyze",
            output={},
            duration_ms=50.0,
            error=exc,
        )
        assert collector.node_records[0].error is exc

    def test_on_node_end_failure_does_not_raise(self) -> None:
        """on_node_end 内部异常不传播（C6）。"""
        collector = MetricsCollector(trace_id="abcd1234")

        # 传入不可序列化的 output，触发内部异常
        collector.on_node_end(
            node_name="bad",
            output=None,  # type: ignore[arg-type]
            duration_ms=10.0,
        )
        # 不应抛异常，记录可能或可能不追加，但不应崩溃


class TestComputeSummary:
    """_compute_summary 汇总计算测试。"""

    def test_success_status(self) -> None:
        """review_passed=True -> status=success。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})
        summary = collector._compute_summary({
            "review_passed": True,
            "iteration": 2,
            "sources": [{"title": "a"}, {"title": "b"}],
            "analyses": [{"title": "a"}],
            "articles": [{"article_id": "kb-1"}],
            "saved_count": 1,
        })
        assert summary["status"] == "success"
        assert summary["source_count"] == 2
        assert summary["analysis_count"] == 1
        assert summary["article_count"] == 1
        assert summary["saved_count"] == 1
        assert summary["human_flagged"] is False
        assert summary["review_passed"] is True
        assert summary["iteration"] == 2

    def test_human_flagged_status(self) -> None:
        """human_flagged=True -> status=human_flagged。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})
        summary = collector._compute_summary({
            "human_flagged": True,
            "review_passed": False,
            "iteration": 3,
        })
        assert summary["status"] == "human_flagged"
        assert summary["human_flagged"] is True

    def test_error_status_when_not_ended(self) -> None:
        """未调用 on_workflow_end -> status=error。"""
        collector = MetricsCollector(trace_id="abcd1234")
        summary = collector._compute_summary({})
        assert summary["status"] == "error"

    def test_cost_extraction(self) -> None:
        """从 cost_tracker 计算 total_cost_yuan。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})
        summary = collector._compute_summary({
            "cost_tracker": {
                "analyze": {
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 500_000,
                    "total_tokens": 1_500_000,
                },
            },
        })
        # 1M prompt * 1.0/M + 500K completion * 2.0/M = 1.0 + 1.0 = 2.0
        assert summary["total_cost_yuan"] == 2.0

    def test_empty_cost_tracker(self) -> None:
        """空 cost_tracker -> total_cost_yuan=0。"""
        collector = MetricsCollector(trace_id="abcd1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})
        summary = collector._compute_summary({})
        assert summary["total_cost_yuan"] == 0.0


class TestExtractNodeCost:
    """_extract_node_cost 测试。"""

    def test_extract_existing_node(self) -> None:
        """从节点 output 的 cost_tracker 提取该节点的成本。"""
        record = NodeMetricRecord(
            node_name="analyze",
            duration_ms=100.0,
            output={
                "cost_tracker": {
                    "analyze": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                },
            },
            error=None,
            timestamp="2026-07-30T00:00:00Z",
        )
        collector = MetricsCollector(trace_id="abcd1234")
        cost = collector._extract_node_cost(record)
        assert cost is not None
        assert cost["prompt_tokens"] == 100
        assert cost["completion_tokens"] == 50
        assert cost["total_tokens"] == 150

    def test_extract_no_cost_tracker(self) -> None:
        """output 中无 cost_tracker -> None。"""
        record = NodeMetricRecord(
            node_name="collect",
            duration_ms=50.0,
            output={"sources": []},
            error=None,
            timestamp="2026-07-30T00:00:00Z",
        )
        collector = MetricsCollector(trace_id="abcd1234")
        cost = collector._extract_node_cost(record)
        assert cost is None

    def test_extract_node_not_in_tracker(self) -> None:
        """cost_tracker 中无该节点 -> None。"""
        record = NodeMetricRecord(
            node_name="save",
            duration_ms=10.0,
            output={
                "cost_tracker": {
                    "analyze": {"prompt_tokens": 100, "completion_tokens": 50},
                },
            },
            error=None,
            timestamp="2026-07-30T00:00:00Z",
        )
        collector = MetricsCollector(trace_id="abcd1234")
        cost = collector._extract_node_cost(record)
        assert cost is None


# ---------------------------------------------------------------------------
# with_metrics 装饰器测试
# ---------------------------------------------------------------------------


class TestWithMetricsDecorator:
    """with_metrics 装饰器测试。"""

    def test_decorator_preserves_return_value(self) -> None:
        """装饰器不改变原函数返回值。"""
        def fake_node(state: dict) -> dict:
            return {"sources": [{"title": "test"}]}

        wrapped = with_metrics(fake_node, "collect")
        result = wrapped({})
        assert result == {"sources": [{"title": "test"}]}

    def test_decorator_records_metrics(self) -> None:
        """装饰器在有 collector 时记录指标。"""
        collector = MetricsCollector(trace_id="test1234")
        token = set_metrics_collector(collector)
        try:
            def fake_node(state: dict) -> dict:
                return {"analyses": [{"title": "t"}]}

            wrapped = with_metrics(fake_node, "analyze")
            wrapped({})

            assert len(collector.node_records) == 1
            assert collector.node_records[0].node_name == "analyze"
            assert collector.node_records[0].error is None
        finally:
            metrics_collector_var.reset(token)

    def test_decorator_propagates_exception(self) -> None:
        """装饰器传播原函数异常。"""
        collector = MetricsCollector(trace_id="test1234")
        token = set_metrics_collector(collector)
        try:
            def boom_node(state: dict) -> dict:
                raise RuntimeError("boom")

            wrapped = with_metrics(boom_node, "review")
            try:
                wrapped({})
                raise AssertionError("应抛出 RuntimeError")
            except RuntimeError as e:
                assert str(e) == "boom"

            assert len(collector.node_records) == 1
            assert collector.node_records[0].error is not None
        finally:
            metrics_collector_var.reset(token)

    def test_decorator_without_collector(self) -> None:
        """无 collector 时装饰器透传，不记录。"""
        token = set_metrics_collector(None)
        try:
            def fake_node(state: dict) -> dict:
                return {"saved_count": 1}

            wrapped = with_metrics(fake_node, "save")
            result = wrapped({})
            assert result == {"saved_count": 1}
        finally:
            metrics_collector_var.reset(token)

    def test_decorator_records_duration(self) -> None:
        """装饰器记录的耗时大于 0。"""
        collector = MetricsCollector(trace_id="test1234")
        token = set_metrics_collector(collector)
        try:
            def slow_node(state: dict) -> dict:
                time.sleep(0.01)
                return {}

            wrapped = with_metrics(slow_node, "organize")
            wrapped({})

            assert collector.node_records[0].duration_ms > 0
        finally:
            metrics_collector_var.reset(token)


# ---------------------------------------------------------------------------
# ContextVar 测试
# ---------------------------------------------------------------------------


class TestContextVar:
    """ContextVar 注入测试。"""

    def test_set_and_get(self) -> None:
        """set 后 get 返回设置的实例。"""
        collector = MetricsCollector(trace_id="ctx1234")
        token = set_metrics_collector(collector)
        try:
            assert get_metrics_collector() is collector
        finally:
            metrics_collector_var.reset(token)

    def test_default_is_none(self) -> None:
        """未设置时 get 返回 None。"""
        assert get_metrics_collector() is None

    def test_reset_restores_previous(self) -> None:
        """reset 恢复之前的值。"""
        assert get_metrics_collector() is None

        collector1 = MetricsCollector(trace_id="first1234")
        token1 = set_metrics_collector(collector1)
        assert get_metrics_collector() is collector1

        collector2 = MetricsCollector(trace_id="sec12345")
        token2 = set_metrics_collector(collector2)
        assert get_metrics_collector() is collector2

        metrics_collector_var.reset(token2)
        assert get_metrics_collector() is collector1

        metrics_collector_var.reset(token1)
        assert get_metrics_collector() is None


# ---------------------------------------------------------------------------
# persist 测试（mock session_scope）
# ---------------------------------------------------------------------------


class TestPersist:
    """persist 持久化测试。"""

    def test_persist_writes_run_and_metrics(self) -> None:
        """persist 写入 PipelineRun 和 NodeMetric。"""
        collector = MetricsCollector(trace_id="pers1234")
        collector.on_workflow_start()
        collector.on_node_end(
            node_name="collect",
            output={"sources": [{"title": "t"}]},
            duration_ms=100.0,
        )
        collector.on_node_end(
            node_name="analyze",
            output={
                "analyses": [{"title": "t"}],
                "cost_tracker": {
                    "analyze": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                },
            },
            duration_ms=200.0,
        )
        collector.on_node_end(
            node_name="review",
            output={"review_passed": True, "iteration": 1},
            duration_ms=50.0,
        )
        collector.on_workflow_end({})

        mock_session = MagicMock()

        def _add_side_effect(obj: object) -> None:
            obj.id = 42

        mock_session.add.side_effect = _add_side_effect
        mock_session.flush.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda self: mock_session
        mock_ctx.__exit__ = lambda self, *args: False
        mock_scope = MagicMock(return_value=mock_ctx)

        final_state = {
            "review_passed": True,
            "iteration": 1,
            "sources": [{"title": "t"}],
            "analyses": [{"title": "t"}],
            "articles": [{"article_id": "kb-1"}],
            "saved_count": 1,
        }

        with patch("src.graph.metrics.session_scope", mock_scope):
            collector.persist(final_state)

        # PipelineRun 写入 1 次
        assert mock_session.add.call_count == 4  # 1 run + 3 metrics
        # flush 调用 1 次（run flush 后拿 id）
        mock_session.flush.assert_called_once()

    def test_persist_failure_does_not_raise(self) -> None:
        """persist 持久化失败不传播（C6）。"""
        collector = MetricsCollector(trace_id="fail1234")
        collector.on_workflow_start()
        collector.on_workflow_end({})

        mock_scope = MagicMock(side_effect=RuntimeError("DB down"))

        with patch("src.graph.metrics.session_scope", mock_scope):
            collector.persist({})  # 不应抛异常

    def test_persist_review_node_extracts_review_fields(self) -> None:
        """persist 从 review 节点记录提取 review_passed 和 iteration。"""
        collector = MetricsCollector(trace_id="rev12345")
        collector.on_workflow_start()
        collector.on_node_end(
            node_name="review",
            output={"review_passed": False, "iteration": 2},
            duration_ms=50.0,
        )
        collector.on_workflow_end({})

        added_objects: list[object] = []

        mock_session = MagicMock()

        def _add_side_effect(obj: object) -> None:
            obj.id = 1
            added_objects.append(obj)

        mock_session.add.side_effect = _add_side_effect
        mock_session.flush.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda self: mock_session
        mock_ctx.__exit__ = lambda self, *args: False
        mock_scope = MagicMock(return_value=mock_ctx)

        with patch("src.graph.metrics.session_scope", mock_scope):
            collector.persist({"review_passed": False, "iteration": 2})

        # 第二个 add 的对象是 NodeMetric
        node_metric = added_objects[1]
        assert node_metric.node_name == "review"
        assert node_metric.review_passed is False
        assert node_metric.iteration == 2


# ---------------------------------------------------------------------------
# 端到端集成测试（build_graph + with_metrics + mock 节点）
# ---------------------------------------------------------------------------


class TestGraphWithMetrics:
    """build_graph 集成 with_metrics 的端到端测试。"""

    def test_graph_pass_path_with_metrics(self) -> None:
        """审核通过路径：指标采集器记录全部节点。"""
        collector = MetricsCollector(trace_id="e2e12345")
        metrics_token = set_metrics_collector(collector)
        collector.on_workflow_start()

        try:
            with (
                patch("src.graph.graph.collect_node") as mock_collect,
                patch("src.graph.graph.analyze_node") as mock_analyze,
                patch("src.graph.graph.review_node") as mock_review,
                patch("src.graph.graph.organize_node") as mock_organize,
                patch("src.graph.graph.revise_node"),
                patch("src.graph.graph.save_node") as mock_save,
                patch("src.graph.graph.human_flag_node"),
            ):
                mock_collect.return_value = {"sources": [{"title": "t"}]}
                mock_analyze.return_value = {
                    "analyses": [{"title": "t", "score": 8}]
                }
                mock_review.return_value = {
                    "review_passed": True,
                    "review_feedback": "",
                    "iteration": 1,
                }
                mock_organize.return_value = {
                    "articles": [{"article_id": "kb-1"}]
                }
                mock_save.return_value = {"saved_count": 1}

                from src.graph.graph import build_graph

                app = build_graph()
                result = app.invoke({})

                assert result["review_passed"] is True
                assert result["saved_count"] == 1

            collector.on_workflow_end(result)

            # 验证指标记录
            node_names = [r.node_name for r in collector.node_records]
            assert "collect" in node_names
            assert "analyze" in node_names
            assert "review" in node_names
            assert "organize" in node_names
            assert "save" in node_names
            assert "revise" not in node_names
            assert "human_flag" not in node_names

            # review 节点的记录应包含 review_passed=True
            review_records = [
                r for r in collector.node_records if r.node_name == "review"
            ]
            assert len(review_records) == 1
            assert review_records[0].output.get("review_passed") is True

        finally:
            metrics_collector_var.reset(metrics_token)

    def test_graph_revise_loop_with_metrics(self) -> None:
        """审核循环路径：review 出现两次，revise 出现一次。"""
        collector = MetricsCollector(trace_id="lop12345")
        metrics_token = set_metrics_collector(collector)
        collector.on_workflow_start()

        try:
            call_count = {"review": 0}

            def mock_review_fn(state: dict) -> dict:
                call_count["review"] += 1
                if call_count["review"] == 1:
                    return {
                        "review_passed": False,
                        "review_feedback": "需要改进",
                        "iteration": 1,
                    }
                return {
                    "review_passed": True,
                    "review_feedback": "",
                    "iteration": 2,
                }

            with (
                patch("src.graph.graph.collect_node") as mock_collect,
                patch("src.graph.graph.analyze_node") as mock_analyze,
                patch("src.graph.graph.review_node", side_effect=mock_review_fn),
                patch("src.graph.graph.revise_node") as mock_revise,
                patch("src.graph.graph.organize_node") as mock_organize,
                patch("src.graph.graph.save_node") as mock_save,
                patch("src.graph.graph.human_flag_node"),
            ):
                mock_collect.return_value = {"sources": [{"title": "t"}]}
                mock_analyze.return_value = {"analyses": [{"title": "t"}]}
                mock_revise.return_value = {
                    "analyses": [{"title": "t", "score": 9}]
                }
                mock_organize.return_value = {
                    "articles": [{"article_id": "kb-1"}]
                }
                mock_save.return_value = {"saved_count": 1}

                from src.graph.graph import build_graph

                app = build_graph()
                result = app.invoke({})

            collector.on_workflow_end(result)

            # review 出现 2 次，revise 出现 1 次
            review_records = [
                r for r in collector.node_records if r.node_name == "review"
            ]
            revise_records = [
                r for r in collector.node_records if r.node_name == "revise"
            ]
            assert len(review_records) == 2
            assert len(revise_records) == 1

        finally:
            metrics_collector_var.reset(metrics_token)
