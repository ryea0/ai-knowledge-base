"""LangGraph 工作流构建与编译。

构建采集 -> 分析 -> 审核 -> 整理/修订/人工标记的状态机图。
审核节点根据结果决定走向：

- ``review_passed=True``               -> 整理节点 -> 保存 -> END
- ``review_passed=False`` 且未达上限   -> 修订节点 -> 回到审核（循环）
- ``review_passed=False`` 且达上限     -> 人工标记节点 -> END

图结构见 AGENTS.md §5 工作流。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from src.common.cost_guard import CostGuard, cost_guard_var, set_cost_guard
from src.common.trace import generate_trace_id
from src.graph.metrics import (
    MetricsCollector,
    metrics_collector_var,
    set_metrics_collector,
    with_metrics,
)
from src.graph.nodes import (
    analyze_node,
    collect_node,
    human_flag_node,
    organize_node,
    review_node,
    save_node,
)
from src.graph.reviser import revise_node
from src.graph.state import KBState

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 3
_RECURSION_LIMIT = 20

# 预算守卫默认配置
_DEFAULT_BUDGET_YUAN = 10.0
_DEFAULT_ALERT_THRESHOLD = 0.8
_DEFAULT_INPUT_PRICE = 1.0
_DEFAULT_OUTPUT_PRICE = 2.0


def route_after_review(state: KBState) -> str:
    """审核后路由函数：通过 -> organize，未通过且达上限 -> human_flag，否则 -> revise。

    Args:
        state: 当前工作流状态。

    Returns:
        下一节点名称（``"organize"`` / ``"revise"`` / ``"human_flag"``）。
    """
    if state.get("review_passed", False):
        return "organize"
    if state.get("iteration", 0) >= _MAX_ITERATIONS:
        return "human_flag"
    return "revise"


def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    图结构::

        START -> collect -> analyze -> review ──passed──> organize -> save -> END
                                         ├─not passed, < max──> revise -> review
                                         └─not passed, >= max──> human_flag -> END

    审核循环最多 3 轮。审核通过后进入整理节点格式化，再保存。
    达上限仍未通过时进入人工标记节点，条目被隔离到 ``knowledge/flagged/``。
    编译时设置 ``recursion_limit=20`` 防止异常情况下无限循环。

    Returns:
        编译后的 LangGraph 可执行图，调用 ``.invoke(state)`` 执行。
    """
    graph = StateGraph(KBState)
    graph.add_node("collect", with_metrics(collect_node, "collect"))
    graph.add_node("analyze", with_metrics(analyze_node, "analyze"))
    graph.add_node("review", with_metrics(review_node, "review"))
    graph.add_node("organize", with_metrics(organize_node, "organize"))
    graph.add_node("revise", with_metrics(revise_node, "revise"))
    graph.add_node("save", with_metrics(save_node, "save"))
    graph.add_node("human_flag", with_metrics(human_flag_node, "human_flag"))

    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )
    graph.add_edge("revise", "review")
    graph.add_edge("organize", "save")
    graph.add_edge("save", END)
    graph.add_edge("human_flag", END)

    compiled = graph.compile()
    logger.info(
        "LangGraph 工作流编译完成（带审核-修订循环+人工标记, recursion_limit=%d）",
        _RECURSION_LIMIT,
    )
    return compiled


def run_workflow(
    *,
    budget_yuan: float = _DEFAULT_BUDGET_YUAN,
    alert_threshold: float = _DEFAULT_ALERT_THRESHOLD,
) -> dict[str, Any]:
    """构建并执行工作流，返回最终状态。

    在工作流入口生成 ``trace_id`` 并注入初始状态，
    各节点通过 ``state["trace_id"]`` 传播链路追踪 ID。

    同时创建 :class:`CostGuard` 和 :class:`MetricsCollector`，
    分别通过 ContextVar 注入。``chat_completion`` 在每次 LLM 调用后
    自动执行成本记录与预算检查；``with_metrics`` 装饰器在节点执行
    前后自动采集耗时与产出。工作流结束后保存成本报告到
    ``knowledge/cost_report_{timestamp}.json``，并将指标持久化到
    ``kb_pipeline_run`` + ``kb_node_metric`` 表。
    guard 实例放入返回状态的 ``"cost_guard"`` 键供调用方查看。

    Args:
        budget_yuan: 预算上限（元）。
        alert_threshold: 预警阈值（0~1）。

    Returns:
        工作流最终状态 dict（含 ``"cost_guard"`` 键）。
    """
    trace_id = generate_trace_id()

    # 创建并注入预算守卫
    guard = CostGuard(
        budget_yuan=budget_yuan,
        alert_threshold=alert_threshold,
        input_price_per_million=_DEFAULT_INPUT_PRICE,
        output_price_per_million=_DEFAULT_OUTPUT_PRICE,
    )
    token = set_cost_guard(guard)

    # 创建并注入指标采集器
    collector = MetricsCollector(trace_id=trace_id)
    collector.on_workflow_start()
    metrics_token = set_metrics_collector(collector)

    result: dict[str, Any] = {}
    try:
        app = build_graph()
        initial_state: KBState = {"trace_id": trace_id}
        result = dict(
            app.invoke(
                initial_state,
                config={"recursion_limit": _RECURSION_LIMIT},
            )
        )
        # 将 CostGuard 放入结果，供调用方查看成本报告
        # （ContextVar 在 finally 中会被 reset，外部无法再通过 get_cost_guard 获取）
        result["cost_guard"] = guard
    finally:
        # 记录工作流结束并持久化指标（采集失败不影响 pipeline, C6）
        try:
            collector.on_workflow_end(result)
            collector.persist(result)
        except Exception:
            logger.warning("指标持久化失败, 已忽略 (C6)", exc_info=True)
        # 工作流结束后保存成本报告
        try:
            guard.save_report()
        except Exception:
            logger.warning("保存成本报告失败", exc_info=True)
        # 恢复 ContextVar 原值
        cost_guard_var.reset(token)
        metrics_collector_var.reset(metrics_token)

    return result


if __name__ == "__main__":
    from src.common.trace import TraceIdFilter, generate_trace_id, set_trace_id

    # 设置 trace_id，确保 __main__ 块的日志也能输出 trace_id
    _main_trace_id = generate_trace_id()
    set_trace_id(_main_trace_id)

    handler = logging.StreamHandler()
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
        )
    )
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    logger.info("=" * 60)
    logger.info("LangGraph 工作流启动")
    logger.info("-" * 60)

    final_state = run_workflow()

    if "sources" in final_state:
        logger.info("采集条目数: %d", len(final_state["sources"]))
    if "analyses" in final_state:
        logger.info("分析结果数: %d", len(final_state["analyses"]))
    if "articles" in final_state:
        logger.info("知识条目数: %d", len(final_state["articles"]))
    if "review_passed" in final_state:
        logger.info("审核通过: %s", final_state["review_passed"])
        logger.info("iteration: %s", final_state.get("iteration", "?"))
    if final_state.get("review_feedback"):
        logger.info("反馈: %s", final_state["review_feedback"][:120])
    if "saved_count" in final_state:
        logger.info("保存条目数: %d", final_state["saved_count"])
    if final_state.get("human_flagged"):
        logger.warning("条目被人工标记, 未进入主知识库")
    if "cost_tracker" in final_state:
        tracker = final_state["cost_tracker"]
        for node, usage in tracker.items():
            logger.info(
                "%s: prompt=%d, completion=%d",
                node,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
    from src.common.cost_guard import CostGuard

    guard: CostGuard | None = final_state.get("cost_guard")
    if guard is not None and guard.records:
        report = guard.get_report()
        summary = report["summary"]
        logger.info(
            "成本报告: 总费用 %.6f 元 / 预算 %.2f 元 (%.1f%%), 调用 %d 次",
            summary["total_cost_yuan"],
            summary["budget_yuan"],
            summary["usage_ratio"] * 100,
            summary["call_count"],
        )
        for node, stats in report["by_node"].items():
            logger.info(
                "  %s: %d 次调用, %.6f 元",
                node,
                stats["call_count"],
                stats["cost_yuan"],
            )
    if final_state.get("errors"):
        logger.warning("工作流执行中有 %d 个错误", len(final_state["errors"]))

    logger.info("=" * 60)
    logger.info("工作流执行完成")
    logger.info("=" * 60)
