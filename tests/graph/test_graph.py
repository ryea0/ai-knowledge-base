"""src.graph.graph 模块的单元测试。

测试覆盖：
- KBState TypedDict 结构
- build_graph 编译后的图可执行（mock 节点）
- 审核通过路径（review -> save -> END）
- 审核不通过路径（review -> organize 循环）
- iteration 安全网路由（iteration >= 3 时强制走向 save）
"""

from __future__ import annotations

from unittest.mock import patch

from src.graph.graph import build_graph
from src.graph.state import KBState


class TestKBStateStructure:
    """KBState 类型结构测试。"""

    def test_state_can_be_created(self) -> None:
        """KBState 可以用部分字段创建。"""
        state: KBState = {"iteration": 1}
        assert state["iteration"] == 1

    def test_state_with_all_fields(self) -> None:
        """KBState 可以包含所有字段。"""
        state: KBState = {
            "trace_id": "a1b2c3d4",
            "sources": [{"title": "test"}],
            "analyses": [{"summary": "test"}],
            "articles": [{"article_id": "kb-20260728-0001"}],
            "review_feedback": "",
            "review_passed": False,
            "iteration": 1,
            "cost_tracker": {},
            "errors": [],
        }
        assert state["review_passed"] is False
        assert len(state["sources"]) == 1
        assert state["trace_id"] == "a1b2c3d4"


class TestBuildGraph:
    """build_graph 编译测试。"""

    def test_graph_compiles(self) -> None:
        """工作流可以编译成功。"""
        app = build_graph()
        assert app is not None

    def test_graph_pass_path(self) -> None:
        """审核通过路径：collect -> analyze -> organize -> review -> save。"""
        with (
            patch("src.graph.graph.collect_node") as mock_collect,
            patch("src.graph.graph.analyze_node") as mock_analyze,
            patch("src.graph.graph.organize_node") as mock_organize,
            patch("src.graph.graph.review_node") as mock_review,
            patch("src.graph.graph.save_node") as mock_save,
        ):
            mock_collect.return_value = {"sources": [{"title": "t"}]}
            mock_analyze.return_value = {"analyses": [{"title": "t", "score": 0.8}]}
            mock_organize.return_value = {"articles": [{"article_id": "kb-1"}]}
            mock_review.return_value = {
                "review_passed": True,
                "review_feedback": "",
                "iteration": 1,
            }
            mock_save.return_value = {"saved_count": 1}

            app = build_graph()
            result = app.invoke({})

            assert result["review_passed"] is True
            assert result["saved_count"] == 1
            mock_save.assert_called_once()

    def test_graph_fail_then_pass(self) -> None:
        """审核不通过 -> 回到 organize -> 再审核通过。"""
        call_count = {"organize": 0, "review": 0}

        def mock_organize_fn(state: KBState) -> dict:
            call_count["organize"] += 1
            return {"articles": [{"article_id": "kb-1"}]}

        def mock_review_fn(state: KBState) -> dict:
            call_count["review"] += 1
            if call_count["review"] == 1:
                return {
                    "review_passed": False,
                    "review_feedback": "需要改进",
                    "iteration": 1,
                }
            return {
                "review_passed": True,
                "review_feedback": "",
                "iteration": 2,
            }

        with (
            patch("src.graph.graph.collect_node") as mock_collect,
            patch("src.graph.graph.analyze_node") as mock_analyze,
            patch("src.graph.graph.organize_node", side_effect=mock_organize_fn),
            patch("src.graph.graph.review_node", side_effect=mock_review_fn),
            patch("src.graph.graph.save_node") as mock_save,
        ):
            mock_collect.return_value = {"sources": [{"title": "t"}]}
            mock_analyze.return_value = {"analyses": [{"title": "t"}]}
            mock_save.return_value = {"saved_count": 1}

            app = build_graph()
            result = app.invoke({})

            assert call_count["organize"] == 2
            assert call_count["review"] == 2
            assert result["review_passed"] is True
            assert result["saved_count"] == 1

    def test_graph_iteration_safety_net(self) -> None:
        """iteration >= 3 时即使 review 未通过也强制走向 save。"""
        with (
            patch("src.graph.graph.collect_node") as mock_collect,
            patch("src.graph.graph.analyze_node") as mock_analyze,
            patch("src.graph.graph.organize_node") as mock_organize,
            patch("src.graph.graph.review_node") as mock_review,
            patch("src.graph.graph.save_node") as mock_save,
        ):
            mock_collect.return_value = {"sources": [{"title": "t"}]}
            mock_analyze.return_value = {"analyses": [{"title": "t"}]}
            mock_organize.return_value = {"articles": [{"article_id": "kb-1"}]}
            # review 未通过但 iteration 达到上限
            mock_review.return_value = {
                "review_passed": False,
                "review_feedback": "仍需改进",
                "iteration": 3,
            }
            mock_save.return_value = {"saved_count": 1}

            app = build_graph()
            result = app.invoke({})

            assert result["review_passed"] is False
            assert result["saved_count"] == 1
            mock_save.assert_called_once()
