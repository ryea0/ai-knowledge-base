"""LangGraph 工作流状态定义。

定义工作流的全局状态结构，在各节点间传递。
工作流阶段：采集 -> 分析 -> 整理 -> 分发（见 AGENTS.md §5）。
"""

from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    """工作流全局状态。

    在采集/分析/整理/分发各节点间传递的共享状态。

    Attributes:
        stage: 当前工作流阶段（collect/analyze/curate/distribute）。
        candidates: 采集阶段产出的候选条目列表。
        analysis_results: 分析阶段产出的分析结果列表。
        articles: 整理阶段产出的标准知识条目列表。
        distribution_results: 分发阶段产出的分发结果列表。
        errors: 工作流执行中累积的错误信息列表。
    """

    stage: str
    candidates: list[dict[str, Any]]
    analysis_results: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    distribution_results: list[dict[str, Any]]
    errors: list[str]
