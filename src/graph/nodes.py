"""LangGraph 图节点定义。

每个节点对应工作流的一个阶段（采集/分析/整理/分发），
接收 :class:`~src.graph.state.WorkflowState` 并返回更新后的状态。
"""

from __future__ import annotations

import logging
from typing import Any

from src.graph.state import WorkflowState

logger = logging.getLogger(__name__)


def collect_node(state: WorkflowState) -> dict[str, Any]:
    """采集节点：从数据源获取候选条目。

    Args:
        state: 当前工作流状态。

    Returns:
        状态更新 dict，包含 ``candidates`` 和 ``stage``。
    """
    logger.info("采集节点启动")
    return {"stage": "collect", "candidates": [], "errors": []}


def analyze_node(state: WorkflowState) -> dict[str, Any]:
    """分析节点：对候选条目执行 AI 分析。

    Args:
        state: 当前工作流状态，须包含 ``candidates``。

    Returns:
        状态更新 dict，包含 ``analysis_results`` 和 ``stage``。
    """
    logger.info("分析节点启动，候选条目数: %d", len(state.get("candidates", [])))
    return {"stage": "analyze", "analysis_results": []}


def curate_node(state: WorkflowState) -> dict[str, Any]:
    """整理节点：去重、格式化、存盘。

    Args:
        state: 当前工作流状态，须包含 ``analysis_results``。

    Returns:
        状态更新 dict，包含 ``articles`` 和 ``stage``。
    """
    logger.info("整理节点启动，分析结果数: %d", len(state.get("analysis_results", [])))
    return {"stage": "curate", "articles": []}


def distribute_node(state: WorkflowState) -> dict[str, Any]:
    """分发节点：推送至多渠道。

    Args:
        state: 当前工作流状态，须包含 ``articles``。

    Returns:
        状态更新 dict，包含 ``distribution_results`` 和 ``stage``。
    """
    logger.info("分发节点启动，待分发条目数: %d", len(state.get("articles", [])))
    return {"stage": "distribute", "distribution_results": []}
