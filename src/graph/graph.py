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

from src.graph.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from src.graph.state import KBState

logger = logging.getLogger(__name__)


def _route_after_review(state: KBState) -> str:
    """审核后路由函数：通过 -> save，不通过 -> organize。

    Args:
        state: 当前工作流状态。

    Returns:
        下一节点名称（``"save"`` 或 ``"organize"``）。
    """
    if state.get("review_passed", False):
        return "save"
    return "organize"


def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    图结构::

        START -> collect -> analyze -> organize -> review ──passed──> save -> END
                                                 └─not passed─> organize

    审核循环最多 3 轮（由 review_node 内 ``iteration >= 3`` 强制通过保证）。

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
    logger.info("LangGraph 工作流编译完成（带审核循环）")
    return compiled


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = build_graph()
    print("=" * 60)
    print("LangGraph 工作流启动")
    print("-" * 60)

    for event in app.stream({}):
        for node_name, node_output in event.items():
            print(f"\n[{node_name}] 输出:")
            if "sources" in node_output:
                print(f"  采集条目数: {len(node_output['sources'])}")
            if "analyses" in node_output:
                print(f"  分析结果数: {len(node_output['analyses'])}")
            if "articles" in node_output:
                print(f"  知识条目数: {len(node_output['articles'])}")
            if "review_passed" in node_output:
                print(f"  审核通过: {node_output['review_passed']}")
                print(f"  iteration: {node_output.get('iteration', '?')}")
            if "review_feedback" in node_output and node_output.get("review_feedback"):
                print(f"  反馈: {node_output['review_feedback'][:120]}")
            if "saved_count" in node_output:
                print(f"  保存条目数: {node_output['saved_count']}")
            if "cost_tracker" in node_output:
                tracker = node_output["cost_tracker"]
                for node, usage in tracker.items():
                    print(
                        f"  {node}: prompt={usage.get('prompt_tokens', 0)}, "
                        f"completion={usage.get('completion_tokens', 0)}"
                    )

    print("\n" + "=" * 60)
    print("工作流执行完成")
    print("=" * 60)
