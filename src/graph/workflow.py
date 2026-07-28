"""LangGraph 工作流构建与编译。

构建采集 -> 分析 -> 整理 -> 分发的线性状态机图。
图结构见 AGENTS.md §5 工作流。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import analyze_node, collect_node, curate_node, distribute_node
from src.graph.state import WorkflowState

logger = logging.getLogger(__name__)


def build_workflow() -> Any:
    """构建并编译 LangGraph 工作流。

    图结构：``START -> collect -> analyze -> curate -> distribute -> END``。

    Returns:
        编译后的 LangGraph 可执行图，调用 ``.invoke(state)`` 执行。
    """
    graph = StateGraph(WorkflowState)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("curate", curate_node)
    graph.add_node("distribute", distribute_node)

    graph.add_edge(START, "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "curate")
    graph.add_edge("curate", "distribute")
    graph.add_edge("distribute", END)

    compiled = graph.compile()
    logger.info("LangGraph 工作流编译完成")
    return compiled
