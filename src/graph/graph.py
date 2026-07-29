"""LangGraph 工作流构建与编译。

构建采集 -> 分析 -> 整理 -> 审核 -> 保存的状态机图。
审核节点根据结果决定走向：

- ``review_passed=True``  -> 保存节点 -> END
- ``review_passed=False`` -> 回到整理节点修正（带反馈，最多 3 轮）

图结构见 AGENTS.md §5 工作流。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from src.common.trace import generate_trace_id
from src.graph.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from src.graph.state import KBState

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 3
_RECURSION_LIMIT = 15


def _route_after_review(state: KBState) -> str:
    """审核后路由函数：通过 -> save，不通过 -> organize。

    当 ``iteration`` 达到上限时也强制走向 save，作为安全网，
    防止 review_node 异常未设置 ``review_passed`` 时无限循环。

    Args:
        state: 当前工作流状态。

    Returns:
        下一节点名称（``"save"`` 或 ``"organize"``）。
    """
    if state.get("review_passed", False):
        return "save"
    if state.get("iteration", 0) >= _MAX_ITERATIONS:
        return "save"
    return "organize"


def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    图结构::

        START -> collect -> analyze -> organize -> review ──passed──> save -> END
                                                 └─not passed─> organize

    审核循环最多 3 轮（由 review_node 内 ``iteration >= 3`` 强制通过保证）。
    编译时设置 ``recursion_limit=15`` 防止异常情况下无限循环。

    Returns:
        编译后的 LangGraph 可执行图，调用 ``.invoke(state)`` 执行。
    """
    graph = StateGraph(KBState)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")
    graph.add_conditional_edges(
        "review",
        _route_after_review,
        {"save": "save", "organize": "organize"},
    )
    graph.add_edge("save", END)

    compiled = graph.compile()
    logger.info("LangGraph 工作流编译完成（带审核循环, recursion_limit=%d）", _RECURSION_LIMIT)
    return compiled


def run_workflow() -> dict[str, Any]:
    """构建并执行工作流，返回最终状态。

    在工作流入口生成 ``trace_id`` 并注入初始状态，
    各节点通过 ``state["trace_id"]`` 传播链路追踪 ID。

    Returns:
        工作流最终状态 dict。
    """
    trace_id = generate_trace_id()
    app = build_graph()
    initial_state: KBState = {"trace_id": trace_id}
    result: dict[str, Any] = dict(
        app.invoke(
            initial_state,
            config={"recursion_limit": _RECURSION_LIMIT},
        )
    )
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s",
    )

    from src.common.trace import TraceIdFilter

    handler = logging.StreamHandler()
    handler.addFilter(TraceIdFilter())
    logging.getLogger().addHandler(handler)

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
    if "cost_tracker" in final_state:
        tracker = final_state["cost_tracker"]
        for node, usage in tracker.items():
            logger.info(
                "%s: prompt=%d, completion=%d",
                node,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
    if final_state.get("errors"):
        logger.warning("工作流执行中有 %d 个错误", len(final_state["errors"]))

    logger.info("=" * 60)
    logger.info("工作流执行完成")
    logger.info("=" * 60)
