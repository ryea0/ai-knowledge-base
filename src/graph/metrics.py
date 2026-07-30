"""工作流指标采集器 -- 观察者模式装饰器注入。

为 LangGraph 工作流提供节点级指标采集，不修改节点函数本身。
通过 ``_with_metrics`` 装饰器在 ``build_graph()`` 中包裹节点函数，
采集 M1-M5 指标（PRD: prd-pipeline-metrics.md）。

架构决策见 ``_bmad-output/planning-artifacts/arch-pipeline-metrics.md`` 方案 B。

指标覆盖：
    - M1 Pipeline 运行结果: ``on_workflow_end`` 记录终态
    - M2 节点级耗时: 装饰器 ``monotonic`` 打点
    - M3 审核通过率与轮次: 从 review 节点 output 提取
    - M4 各节点 LLM 成本: 从节点 output 的 cost_tracker 增量提取
    - M5 转化漏斗: 累积 sources / analyses / articles / saved_count

线程安全：``MetricsCollector`` 内部使用 ``threading.Lock``，
``analyze_node`` 的 ``ThreadPoolExecutor`` 子线程通过 ContextVar 快照访问。

采集失败不影响 pipeline 执行（C6）：所有采集方法内部 try/except，
异常仅记日志。
"""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.common.base_entity import _utc_now
from src.config.database import session_scope
from src.models.metrics import NodeMetric, PipelineRun

logger = logging.getLogger(__name__)

metrics_collector_var: contextvars.ContextVar[MetricsCollector | None] = contextvars.ContextVar(
    "metrics_collector", default=None
)


@dataclass
class NodeMetricRecord:
    """单节点指标记录。

    Attributes:
        node_name: 节点名称（如 "collect" / "analyze" / "review"）。
        duration_ms: 节点 wall-clock 耗时（毫秒）。
        output: 节点返回的 partial state（用于提取 cost_tracker / review_passed 等）。
        error: 节点抛出的异常，正常执行时为 None。
        timestamp: 记录时间戳。
    """

    node_name: str
    duration_ms: float
    output: dict[str, Any]
    error: Exception | None
    timestamp: str


@dataclass
class MetricsCollector:
    """工作流指标采集器。

    通过 :data:`metrics_collector_var` ContextVar 注入，工作流入口
    调用 :func:`set_metrics_collector` 设置，装饰器内通过
    :func:`get_metrics_collector` 获取。

    生命周期：
        1. ``on_workflow_start`` -- 工作流入口调用
        2. ``on_node_end`` -- 每个节点完成后由装饰器调用（可多次，含循环）
        3. ``on_workflow_end`` -- 工作流出口调用
        4. ``persist`` -- 将指标写入 DB

    Attributes:
        trace_id: 链路追踪 ID。
        node_records: 所有节点指标记录列表。
        started_at: 工作流开始时间。
        ended_at: 工作流结束时间。
    """

    trace_id: str
    node_records: list[NodeMetricRecord] = field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def on_workflow_start(self) -> None:
        """记录工作流开始时间。"""
        self.started_at = _utc_now()
        logger.debug("MetricsCollector: 工作流开始, trace_id=%s", self.trace_id)

    def on_node_end(
        self,
        node_name: str,
        output: dict[str, Any],
        duration_ms: float,
        error: Exception | None = None,
    ) -> None:
        """记录单节点执行指标。

        线程安全：内部加锁保护 ``node_records`` 追加操作。

        Args:
            node_name: 节点名称。
            output: 节点返回的 partial state dict。
            duration_ms: 节点耗时（毫秒）。
            error: 节点抛出的异常，正常执行时为 None。
        """
        try:
            record = NodeMetricRecord(
                node_name=node_name,
                duration_ms=round(duration_ms, 2),
                output=dict(output) if output else {},
                error=error,
                timestamp=datetime.now(UTC).isoformat(),
            )
            with self._lock:
                self.node_records.append(record)
            logger.debug(
                "MetricsCollector: 节点 %s 完成, 耗时 %.1fms, error=%s",
                node_name,
                duration_ms,
                error is not None,
            )
        except Exception:
            logger.warning(
                "MetricsCollector.on_node_end 采集失败 (node=%s), 已忽略",
                node_name,
                exc_info=True,
            )

    def on_workflow_end(self, final_state: dict[str, Any]) -> None:
        """记录工作流结束时间并提取汇总指标。

        Args:
            final_state: 工作流最终状态 dict。
        """
        self.ended_at = _utc_now()
        logger.debug(
            "MetricsCollector: 工作流结束, trace_id=%s, 节点记录数=%d",
            self.trace_id,
            len(self.node_records),
        )

    def _compute_summary(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """从节点记录和最终状态计算汇总指标。

        Args:
            final_state: 工作流最终状态 dict。

        Returns:
            汇总指标字典，包含 status / source_count / analysis_count /
            article_count / saved_count / human_flagged / review_passed /
            iteration / total_cost_yuan。
        """
        human_flagged = bool(final_state.get("human_flagged", False))
        review_passed = bool(final_state.get("review_passed", False))
        iteration = int(final_state.get("iteration", 0))

        if self.ended_at is not None and self.started_at is not None:
            status = "success"
            if human_flagged or not review_passed and iteration >= 3:
                status = "human_flagged"
        else:
            status = "error"

        total_cost_yuan = 0.0
        cost_tracker = final_state.get("cost_tracker", {})
        if isinstance(cost_tracker, dict):
            for node_data in cost_tracker.values():
                if isinstance(node_data, dict):
                    prompt = int(node_data.get("prompt_tokens", 0))
                    completion = int(node_data.get("completion_tokens", 0))
                    total_cost_yuan += (
                        prompt * 1.0 / 1_000_000 + completion * 2.0 / 1_000_000
                    )

        return {
            "status": status,
            "source_count": len(final_state.get("sources", [])),
            "analysis_count": len(final_state.get("analyses", [])),
            "article_count": len(final_state.get("articles", [])),
            "saved_count": int(final_state.get("saved_count", 0)),
            "human_flagged": human_flagged,
            "review_passed": review_passed,
            "iteration": iteration,
            "total_cost_yuan": round(total_cost_yuan, 6),
        }

    def _extract_node_cost(
        self, record: NodeMetricRecord
    ) -> dict[str, Any] | None:
        """从节点记录的 output 中提取 cost_tracker 增量。

        每个节点的 output 可能包含 ``cost_tracker`` 字段，
        其中包含该节点累加后的全量 cost_tracker。
        本方法提取该节点对应的分量的增量值。

        Args:
            record: 节点指标记录。

        Returns:
            节点成本数据 dict（prompt_tokens / completion_tokens /
            total_tokens），无成本数据时为 None。
        """
        cost_tracker = record.output.get("cost_tracker")
        if not isinstance(cost_tracker, dict):
            return None
        node_cost = cost_tracker.get(record.node_name)
        if not isinstance(node_cost, dict):
            return None
        return {
            "prompt_tokens": int(node_cost.get("prompt_tokens", 0)),
            "completion_tokens": int(node_cost.get("completion_tokens", 0)),
            "total_tokens": int(node_cost.get("total_tokens", 0)),
        }

    def persist(self, final_state: dict[str, Any]) -> None:
        """将指标持久化到 DB（kb_pipeline_run + kb_node_metric）。

        采集失败不影响 pipeline：内部 try/except，异常仅记日志（C6）。

        Args:
            final_state: 工作流最终状态 dict。
        """
        try:
            summary = self._compute_summary(final_state)
            with session_scope() as session:
                run = self._create_pipeline_run(session, summary)
                self._create_node_metrics(session, run.id)
            logger.info(
                "MetricsCollector: 指标已持久化, trace_id=%s, "
                "status=%s, 节点数=%d",
                self.trace_id,
                summary["status"],
                len(self.node_records),
            )
        except Exception:
            logger.warning(
                "MetricsCollector.persist 持久化失败, 已忽略 (C6)",
                exc_info=True,
            )

    def _create_pipeline_run(
        self,
        session: Session,
        summary: dict[str, Any],
    ) -> PipelineRun:
        """创建 kb_pipeline_run 记录。

        Args:
            session: SQLAlchemy Session。
            summary: 汇总指标字典。

        Returns:
            已 flush 的 PipelineRun ORM 实例（含 id）。
        """
        duration_ms: int | None = None
        if self.started_at is not None and self.ended_at is not None:
            delta = self.ended_at - self.started_at
            duration_ms = int(delta.total_seconds() * 1000)

        run = PipelineRun(
            trace_id=self.trace_id,
            status=summary["status"],
            started_at=self.started_at,
            ended_at=self.ended_at,
            duration_ms=duration_ms,
            source_count=summary["source_count"],
            analysis_count=summary["analysis_count"],
            article_count=summary["article_count"],
            saved_count=summary["saved_count"],
            human_flagged=summary["human_flagged"],
            review_passed=summary["review_passed"],
            iteration=summary["iteration"],
            total_cost_yuan=summary["total_cost_yuan"],
        )
        session.add(run)
        session.flush()
        return run

    def _create_node_metrics(
        self,
        session: Session,
        run_id: int,
    ) -> None:
        """批量创建 kb_node_metric 记录。

        Args:
            session: SQLAlchemy Session。
            run_id: 关联的 kb_pipeline_run.id。
        """
        for record in self.node_records:
            cost_data = self._extract_node_cost(record)
            error_msg = ""
            if record.error is not None:
                error_msg = str(record.error)[:500]

            review_passed: bool | None = None
            iteration: int | None = None
            if record.node_name == "review":
                review_passed = record.output.get("review_passed")
                iteration = record.output.get("iteration")

            metric = NodeMetric(
                run_id=run_id,
                trace_id=self.trace_id,
                node_name=record.node_name,
                duration_ms=int(record.duration_ms),
                cost_data=cost_data,
                review_passed=review_passed,
                iteration=iteration,
                error=error_msg,
            )
            session.add(metric)


def set_metrics_collector(
    collector: MetricsCollector | None,
) -> contextvars.Token[MetricsCollector | None]:
    """设置当前上下文的 MetricsCollector 实例。

    在工作流入口调用，装饰器内通过 :func:`get_metrics_collector` 获取。

    Args:
        collector: MetricsCollector 实例，传 None 可清除。

    Returns:
        ContextVar Token，可用于恢复原值。
    """
    return metrics_collector_var.set(collector)


def get_metrics_collector() -> MetricsCollector | None:
    """获取当前上下文的 MetricsCollector 实例。

    Returns:
        当前 MetricsCollector 实例，未设置时返回 None。
    """
    return metrics_collector_var.get()


def with_metrics(
    node_fn: Callable[..., dict[str, Any]],
    node_name: str,
) -> Callable[..., dict[str, Any]]:
    """装饰器：为节点函数注入指标采集。

    包裹节点函数，在执行前后打点采集耗时和输出。
    采集失败不影响节点执行（C6）：采集逻辑内部 try/except。

    用法::

        graph.add_node("collect", with_metrics(collect_node, "collect"))

    Args:
        node_fn: 原始节点函数 ``(state) -> dict``。
        node_name: 节点名称，用于指标记录。

    Returns:
        包裹后的节点函数，签名与原始函数一致。
    """

    @functools.wraps(node_fn)
    def wrapper(state: Any) -> dict[str, Any]:
        collector = get_metrics_collector()
        if collector is None:
            return node_fn(state)

        t0 = time.monotonic()
        try:
            result = node_fn(state)
            duration_ms = (time.monotonic() - t0) * 1000
            collector.on_node_end(
                node_name=node_name,
                output=result if isinstance(result, dict) else {},
                duration_ms=duration_ms,
                error=None,
            )
            return result
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            collector.on_node_end(
                node_name=node_name,
                output={},
                duration_ms=duration_ms,
                error=exc,
            )
            raise

    return wrapper


__all__ = [
    "MetricsCollector",
    "NodeMetricRecord",
    "get_metrics_collector",
    "metrics_collector_var",
    "set_metrics_collector",
    "with_metrics",
]
