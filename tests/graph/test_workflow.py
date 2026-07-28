"""src.graph 模块的单元测试。

测试覆盖：
- WorkflowState TypedDict 结构
- 图节点函数返回正确的状态更新
- build_workflow 编译后的图可执行
"""

from __future__ import annotations

from src.graph.nodes import analyze_node, collect_node, curate_node, distribute_node
from src.graph.state import WorkflowState
from src.graph.workflow import build_workflow


class TestWorkflowState:
    """WorkflowState 类型结构测试。"""

    def test_state_can_be_created(self) -> None:
        """WorkflowState 可以用部分字段创建。"""
        state: WorkflowState = {"stage": "collect"}
        assert state["stage"] == "collect"

    def test_state_with_all_fields(self) -> None:
        """WorkflowState 可以包含所有字段。"""
        state: WorkflowState = {
            "stage": "distribute",
            "candidates": [{"title": "test"}],
            "analysis_results": [{"summary": "test"}],
            "articles": [{"article_id": "kb-20260728-0001"}],
            "distribution_results": [{"status": "success"}],
            "errors": [],
        }
        assert state["stage"] == "distribute"
        assert len(state["candidates"]) == 1  # type: ignore[arg-type]


class TestGraphNodes:
    """图节点函数测试。"""

    def test_collect_node(self) -> None:
        """collect_node 返回 stage=collect 和空 candidates。"""
        result = collect_node({"stage": ""})
        assert result["stage"] == "collect"
        assert result["candidates"] == []
        assert result["errors"] == []

    def test_analyze_node(self) -> None:
        """analyze_node 返回 stage=analyze。"""
        result = analyze_node({"candidates": [{"title": "test"}]})
        assert result["stage"] == "analyze"
        assert result["analysis_results"] == []

    def test_curate_node(self) -> None:
        """curate_node 返回 stage=curate。"""
        result = curate_node({"analysis_results": [{"summary": "test"}]})
        assert result["stage"] == "curate"
        assert result["articles"] == []

    def test_distribute_node(self) -> None:
        """distribute_node 返回 stage=distribute。"""
        result = distribute_node({"articles": [{"article_id": "kb-test"}]})
        assert result["stage"] == "distribute"
        assert result["distribution_results"] == []


class TestBuildWorkflow:
    """build_workflow 编译测试。"""

    def test_workflow_compiles(self) -> None:
        """工作流可以编译成功。"""
        workflow = build_workflow()
        assert workflow is not None

    def test_workflow_executes(self) -> None:
        """工作流可以执行完整流程。"""
        workflow = build_workflow()
        initial_state: WorkflowState = {"stage": ""}
        result = workflow.invoke(initial_state)
        assert result["stage"] == "distribute"
        assert "candidates" in result
        assert "analysis_results" in result
        assert "articles" in result
        assert "distribution_results" in result
