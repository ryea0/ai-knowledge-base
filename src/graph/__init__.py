"""LangGraph 工作流定义模块。

编排采集 -> 分析 -> 整理 -> 审核 -> 保存/人工标记的状态机流程。
工作流定义见 AGENTS.md §5。

子模块：
    - ``state``: 工作流状态定义
    - ``nodes``: 图节点（采集/分析/整理/审核/保存/人工标记）
    - ``reviser``: 修订节点（根据审核反馈批量改写 analyses）
    - ``graph``: LangGraph 图构建与编译
"""

from src.graph.graph import build_graph
from src.graph.state import KBState

__all__ = ["KBState", "build_graph"]
