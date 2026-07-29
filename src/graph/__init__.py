"""LangGraph 工作流定义模块。

编排采集 -> 分析 -> 整理 -> 分发的多步状态机流程。
工作流定义见 AGENTS.md §5。

子模块：
    - ``state``: 工作流状态定义
    - ``nodes``: 图节点（采集/分析/整理/分发）
    - ``workflow``: LangGraph 图构建与编译
"""

from src.graph.state import KBState, WorkflowState
from src.graph.workflow import build_workflow

__all__ = ["KBState", "WorkflowState", "build_workflow"]
