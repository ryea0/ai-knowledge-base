"""src.common.cost_guard 的单元测试。

测试覆盖：
- CostRecord: 字段与默认值
- CostGuard.record: token 追踪 / 成本计算 / 多次累计
- CostGuard.check: ok / warning / BudgetExceededError
- CostGuard.get_report: 按节点分组 / 空状态
- CostGuard.save_report: 文件写入与回读 / 默认路径
- BudgetExceededError: 属性 / str
- ContextVar 注入: set_cost_guard / get_cost_guard
- 线程安全: ThreadPoolExecutor 并发 record + check
"""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.common.cost_guard import (
    BudgetExceededError,
    CostGuard,
    CostRecord,
    cost_guard_var,
    get_cost_guard,
    set_cost_guard,
)

# ---------------------------------------------------------------------------
# CostRecord 测试
# ---------------------------------------------------------------------------


class TestCostRecord:
    """CostRecord 数据类测试。"""

    def test_fields(self) -> None:
        """CostRecord 所有字段正确赋值。"""
        rec = CostRecord(
            timestamp="2026-07-30T12:00:00",
            node_name="analyze",
            prompt_tokens=100,
            completion_tokens=50,
            cost_yuan=0.0002,
            model="doubao-pro",
        )
        assert rec.timestamp == "2026-07-30T12:00:00"
        assert rec.node_name == "analyze"
        assert rec.prompt_tokens == 100
        assert rec.completion_tokens == 50
        assert rec.cost_yuan == 0.0002
        assert rec.model == "doubao-pro"

    def test_default_model(self) -> None:
        """model 默认为空字符串。"""
        rec = CostRecord(
            timestamp="t",
            node_name="n",
            prompt_tokens=0,
            completion_tokens=0,
            cost_yuan=0.0,
        )
        assert rec.model == ""


# ---------------------------------------------------------------------------
# CostGuard.record 测试
# ---------------------------------------------------------------------------


class TestRecord:
    """CostGuard.record 方法测试。"""

    def test_record_basic(self) -> None:
        """record 正确记录 token 和成本。"""
        guard = CostGuard(
            budget_yuan=10.0,
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        rec = guard.record(
            "analyze",
            {"prompt_tokens": 500_000, "completion_tokens": 100_000},
            model="doubao-pro",
        )
        # input: 500000/1M * 1.0 = 0.5
        # output: 100000/1M * 2.0 = 0.2
        assert rec.prompt_tokens == 500_000
        assert rec.completion_tokens == 100_000
        assert abs(rec.cost_yuan - 0.7) < 1e-9
        assert rec.node_name == "analyze"
        assert rec.model == "doubao-pro"

    def test_record_accumulates_totals(self) -> None:
        """多次 record 正确累计 totals。"""
        guard = CostGuard(budget_yuan=100.0)
        guard.record("analyze", {"prompt_tokens": 100, "completion_tokens": 50})
        guard.record("review", {"prompt_tokens": 200, "completion_tokens": 100})
        assert guard.total_prompt_tokens == 300
        assert guard.total_completion_tokens == 150
        assert len(guard.records) == 2

    def test_record_missing_keys(self) -> None:
        """usage 缺少 key 时按 0 处理。"""
        guard = CostGuard(budget_yuan=10.0)
        rec = guard.record("test", {})
        assert rec.prompt_tokens == 0
        assert rec.completion_tokens == 0
        assert rec.cost_yuan == 0.0

    def test_cost_calculation_precision(self) -> None:
        """成本计算保留 6 位小数。"""
        guard = CostGuard(
            budget_yuan=10.0,
            input_price_per_million=3.5,
            output_price_per_million=7.0,
        )
        rec = guard.record(
            "test",
            {"prompt_tokens": 333_333, "completion_tokens": 142_857},
        )
        # input: 333333/1M * 3.5 = 1.1666655
        # output: 142857/1M * 7.0 = 0.999999
        # total = 2.1666645 -> round 6 = 2.166665
        assert rec.cost_yuan == round(333_333 / 1_000_000 * 3.5 + 142_857 / 1_000_000 * 7.0, 6)


# ---------------------------------------------------------------------------
# CostGuard.check 测试
# ---------------------------------------------------------------------------


class TestCheck:
    """CostGuard.check 方法测试。"""

    def test_check_ok(self) -> None:
        """累计成本低于阈值时返回 ok。"""
        guard = CostGuard(
            budget_yuan=1.0,
            alert_threshold=0.8,
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        guard.record("analyze", {"prompt_tokens": 100_000, "completion_tokens": 0})
        # cost = 0.1, ratio = 0.1 < 0.8
        status = guard.check()
        assert status["status"] == "ok"
        assert abs(status["usage_ratio"] - 0.1) < 1e-9

    def test_check_warning(self) -> None:
        """累计成本超过 alert_threshold 但未超预算时返回 warning。"""
        guard = CostGuard(
            budget_yuan=1.0,
            alert_threshold=0.8,
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        guard.record("analyze", {"prompt_tokens": 500_000, "completion_tokens": 200_000})
        # cost = 0.5 + 0.4 = 0.9, ratio = 0.9 >= 0.8
        status = guard.check()
        assert status["status"] == "warning"
        assert "预警" in status["message"]

    def test_check_exceeded_raises(self) -> None:
        """累计成本超预算时抛出 BudgetExceededError。"""
        guard = CostGuard(
            budget_yuan=0.5,
            alert_threshold=0.8,
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        guard.record("analyze", {"prompt_tokens": 500_000, "completion_tokens": 100_000})
        # cost = 0.7 > 0.5
        with pytest.raises(BudgetExceededError) as exc_info:
            guard.check()
        assert abs(exc_info.value.total_cost - 0.7) < 1e-9
        assert abs(exc_info.value.budget - 0.5) < 1e-9
        assert "超限" in str(exc_info.value)

    def test_check_empty_guard(self) -> None:
        """空状态 check 返回 ok。"""
        guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
        status = guard.check()
        assert status["status"] == "ok"
        assert status["total_cost"] == 0.0

    def test_check_zero_budget(self) -> None:
        """预算为 0 时 usage_ratio 为 0（避免除零）。"""
        guard = CostGuard(budget_yuan=0.0, alert_threshold=0.8)
        guard.record("test", {"prompt_tokens": 100, "completion_tokens": 50})
        # total_cost >= budget (0) -> 应抛 BudgetExceededError
        with pytest.raises(BudgetExceededError):
            guard.check()


# ---------------------------------------------------------------------------
# CostGuard.get_report 测试
# ---------------------------------------------------------------------------


class TestGetReport:
    """CostGuard.get_report 方法测试。"""

    def test_report_grouped_by_node(self) -> None:
        """报告按节点分组统计。"""
        guard = CostGuard(budget_yuan=100.0)
        guard.record("analyze", {"prompt_tokens": 100, "completion_tokens": 50}, model="m1")
        guard.record("analyze", {"prompt_tokens": 200, "completion_tokens": 100}, model="m2")
        guard.record("review", {"prompt_tokens": 300, "completion_tokens": 150}, model="m1")

        report = guard.get_report()
        assert report["summary"]["call_count"] == 3
        assert report["summary"]["total_prompt_tokens"] == 600
        assert report["summary"]["total_completion_tokens"] == 300
        assert "analyze" in report["by_node"]
        assert "review" in report["by_node"]
        assert report["by_node"]["analyze"]["call_count"] == 2
        assert report["by_node"]["analyze"]["prompt_tokens"] == 300
        assert report["by_node"]["review"]["call_count"] == 1
        assert len(report["records"]) == 3

    def test_report_empty(self) -> None:
        """空状态报告。"""
        guard = CostGuard(budget_yuan=10.0)
        report = guard.get_report()
        assert report["summary"]["call_count"] == 0
        assert len(report["by_node"]) == 0
        assert len(report["records"]) == 0

    def test_report_usage_ratio(self) -> None:
        """报告 usage_ratio 正确计算。"""
        guard = CostGuard(
            budget_yuan=1.0,
            input_price_per_million=1.0,
            output_price_per_million=0.0,
        )
        guard.record("test", {"prompt_tokens": 500_000, "completion_tokens": 0})
        # cost = 0.5, ratio = 0.5
        report = guard.get_report()
        assert abs(report["summary"]["usage_ratio"] - 0.5) < 1e-4

    def test_report_records_have_all_fields(self) -> None:
        """records 列表每条包含所有 CostRecord 字段。"""
        guard = CostGuard(budget_yuan=10.0)
        guard.record("test", {"prompt_tokens": 10, "completion_tokens": 5}, model="m")
        report = guard.get_report()
        rec = report["records"][0]
        assert "timestamp" in rec
        assert "node_name" in rec
        assert "prompt_tokens" in rec
        assert "completion_tokens" in rec
        assert "cost_yuan" in rec
        assert "model" in rec


# ---------------------------------------------------------------------------
# CostGuard.save_report 测试
# ---------------------------------------------------------------------------


class TestSaveReport:
    """CostGuard.save_report 方法测试。"""

    def test_save_to_path(self, tmp_path: Path) -> None:
        """保存到指定路径。"""
        guard = CostGuard(budget_yuan=10.0)
        guard.record("analyze", {"prompt_tokens": 100, "completion_tokens": 50})
        report_path = guard.save_report(tmp_path / "report.json")
        assert report_path.exists()
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        assert loaded["summary"]["call_count"] == 1
        assert "by_node" in loaded
        assert "records" in loaded

    def test_save_default_path(self) -> None:
        """默认路径保存到 knowledge/ 目录。"""
        guard = CostGuard(budget_yuan=10.0)
        guard.record("test", {"prompt_tokens": 10, "completion_tokens": 5})
        with patch("src.common.cost_guard.Path") as mock_path_cls:
            mock_path = mock_path_cls.return_value
            mock_path.parent.mkdir.return_value = None
            mock_path.write_text.return_value = None
            result = guard.save_report(None)
            _ = result  # 验证不抛异常即可

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """保存时自动创建父目录。"""
        guard = CostGuard(budget_yuan=10.0)
        guard.record("test", {"prompt_tokens": 10, "completion_tokens": 5})
        nested = tmp_path / "a" / "b" / "report.json"
        report_path = guard.save_report(nested)
        assert report_path.exists()


# ---------------------------------------------------------------------------
# BudgetExceededError 测试
# ---------------------------------------------------------------------------


class TestBudgetExceededError:
    """BudgetExceededError 异常测试。"""

    def test_attributes(self) -> None:
        """异常属性正确传递。"""
        err = BudgetExceededError(total_cost=1.5, budget=1.0)
        assert err.total_cost == 1.5
        assert err.budget == 1.0
        assert "超限" in err.message

    def test_custom_message(self) -> None:
        """自定义消息。"""
        err = BudgetExceededError(
            total_cost=2.0, budget=1.0, message="自定义"
        )
        assert err.message == "自定义"
        assert str(err) == "自定义"

    def test_default_message_format(self) -> None:
        """默认消息包含成本和预算值。"""
        err = BudgetExceededError(total_cost=0.7, budget=0.5)
        s = str(err)
        assert "0.7" in s
        assert "0.5" in s

    def test_is_exception(self) -> None:
        """BudgetExceededError 是 Exception 子类。"""
        assert issubclass(BudgetExceededError, Exception)


# ---------------------------------------------------------------------------
# ContextVar 注入测试
# ---------------------------------------------------------------------------


class TestContextVarInjection:
    """set_cost_guard / get_cost_guard 测试。"""

    def test_set_and_get(self) -> None:
        """set 后 get 返回同一实例。"""
        guard = CostGuard(budget_yuan=5.0)
        token = set_cost_guard(guard)
        try:
            assert get_cost_guard() is guard
        finally:
            cost_guard_var.reset(token)

    def test_get_default_none(self) -> None:
        """未 set 时 get 返回 None。"""
        assert get_cost_guard() is None

    def test_reset_restores_previous(self) -> None:
        """reset 恢复之前的值。"""
        assert get_cost_guard() is None
        guard1 = CostGuard(budget_yuan=1.0)
        token = set_cost_guard(guard1)
        guard2 = CostGuard(budget_yuan=2.0)
        token2 = set_cost_guard(guard2)
        try:
            assert get_cost_guard() is guard2
        finally:
            cost_guard_var.reset(token2)
            assert get_cost_guard() is guard1
            cost_guard_var.reset(token)


# ---------------------------------------------------------------------------
# 线程安全测试
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """CostGuard 线程安全测试。"""

    def test_concurrent_record(self) -> None:
        """多线程并发 record 不丢数据。"""
        guard = CostGuard(
            budget_yuan=10000.0,
            input_price_per_million=1.0,
            output_price_per_million=1.0,
        )
        n_threads = 10
        n_per_thread = 100
        prompt_per_call = 1000
        completion_per_call = 500

        def _worker() -> None:
            for _ in range(n_per_thread):
                guard.record(
                    "analyze",
                    {
                        "prompt_tokens": prompt_per_call,
                        "completion_tokens": completion_per_call,
                    },
                )

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total_calls = n_threads * n_per_thread
        assert len(guard.records) == total_calls
        assert guard.total_prompt_tokens == total_calls * prompt_per_call
        assert guard.total_completion_tokens == total_calls * completion_per_call

    def test_concurrent_check_and_record(self) -> None:
        """并发 record + check 不出竞态。"""
        guard = CostGuard(
            budget_yuan=100.0,
            alert_threshold=0.5,
            input_price_per_million=1.0,
            output_price_per_million=1.0,
        )
        errors: list[Exception] = []

        def _recorder() -> None:
            try:
                for _ in range(50):
                    guard.record(
                        "test",
                        {"prompt_tokens": 10_000, "completion_tokens": 5_000},
                    )
            except Exception as exc:
                errors.append(exc)

        def _checker() -> None:
            try:
                for _ in range(50):
                    with contextlib.suppress(BudgetExceededError):
                        guard.check()
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_recorder),
            threading.Thread(target=_recorder),
            threading.Thread(target=_checker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不应有非 BudgetExceededError 的异常
        assert errors == []


# ---------------------------------------------------------------------------
# _compute_cost 测试
# ---------------------------------------------------------------------------


class TestComputeCost:
    """CostGuard._compute_cost 方法测试。"""

    def test_basic_cost(self) -> None:
        """基本成本计算。"""
        guard = CostGuard(
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        # 100000/1M * 1.0 + 50000/1M * 2.0 = 0.1 + 0.1 = 0.2
        cost = guard._compute_cost(100_000, 50_000)
        assert abs(cost - 0.2) < 1e-9

    def test_zero_tokens(self) -> None:
        """零 token 零成本。"""
        guard = CostGuard(
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        )
        assert guard._compute_cost(0, 0) == 0.0

    def test_rounding(self) -> None:
        """结果保留 6 位小数。"""
        guard = CostGuard(
            input_price_per_million=3.0,
            output_price_per_million=7.0,
        )
        cost = guard._compute_cost(1, 1)
        # 1/1M * 3 + 1/1M * 7 = 0.00001 -> round 6 = 0.00001
        assert cost == round(3.0 / 1_000_000 + 7.0 / 1_000_000, 6)
