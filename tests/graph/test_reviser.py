"""src.graph.reviser 模块的单元测试。

测试覆盖：
- revise_node: 跳过条件 / LLM 调用成功 / LLM 失败回退 / 长度不一致回退 / cost_tracker 累加
- _parse_json_array: 干净数组 / 带前缀后缀 / code fence / 非数组异常
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.graph.reviser import (
    _parse_json_array,
    revise_node,
)
from src.llm.client import LlmCallError
from src.llm.cost import TokenUsage

# ---------------------------------------------------------------------------
# _parse_json_array 测试
# ---------------------------------------------------------------------------


class TestParseJsonArray:
    """_parse_json_array 测试。"""

    def test_parse_clean_array(self) -> None:
        """干净 JSON 数组直接解析。"""
        raw = '[{"key": "v1"}, {"key": "v2"}]'
        result = _parse_json_array(raw, "test")
        assert len(result) == 2
        assert result[0] == {"key": "v1"}

    def test_parse_array_with_prefix(self) -> None:
        """带前缀文本的 JSON 数组能提取。"""
        raw = 'Here is the result:\n[{"key": "v1"}]'
        result = _parse_json_array(raw, "test")
        assert len(result) == 1

    def test_parse_array_with_suffix(self) -> None:
        """带后缀文本的 JSON 数组能提取。"""
        raw = '[{"key": "v1"}]\nDone.'
        result = _parse_json_array(raw, "test")
        assert len(result) == 1

    def test_parse_array_with_code_fence(self) -> None:
        """markdown code fence 包裹的 JSON 数组能提取。"""
        raw = '```json\n[{"key": "v1"}]\n```'
        result = _parse_json_array(raw, "test")
        assert len(result) == 1

    def test_parse_empty_array(self) -> None:
        """空数组解析为空列表。"""
        result = _parse_json_array("[]", "test")
        assert result == []

    def test_parse_non_dict_items_filtered(self) -> None:
        """数组中的非 dict 元素被过滤。"""
        raw = '[{"key": "v1"}, "not a dict", 42]'
        result = _parse_json_array(raw, "test")
        assert len(result) == 1

    def test_parse_dict_raises(self) -> None:
        """顶层是 dict 而非 array 时抛 ValueError。"""
        try:
            _parse_json_array('{"key": "value"}', "test")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "test" in str(exc)

    def test_parse_invalid_raises(self) -> None:
        """无法解析的文本抛 ValueError。"""
        try:
            _parse_json_array("not json at all", "test")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "test" in str(exc)


# ---------------------------------------------------------------------------
# revise_node 测试
# ---------------------------------------------------------------------------


class TestReviseNode:
    """revise_node 测试。"""

    def test_skip_when_no_analyses(self) -> None:
        """analyses 为空时跳过，返回 {}。"""
        result = revise_node({"analyses": [], "review_feedback": "需要改进"})
        assert result == {}

    def test_skip_when_no_feedback(self) -> None:
        """review_feedback 为空时跳过，返回 {}。"""
        result = revise_node({
            "analyses": [{"title": "a"}],
            "review_feedback": "",
        })
        assert result == {}

    def test_skip_when_both_empty(self) -> None:
        """analyses 和 feedback 都为空时跳过。"""
        result = revise_node({"analyses": [], "review_feedback": ""})
        assert result == {}

    def test_revise_success(self) -> None:
        """成功改写返回 improved analyses。"""
        original_analyses = [
            {"title": "项目A", "summary": "旧摘要", "score": 5},
            {"title": "项目B", "summary": "旧摘要B", "score": 6},
        ]
        improved_json = (
            '[{"title": "项目A", "summary": "改进摘要", "score": 8}, '
            '{"title": "项目B", "summary": "改进摘要B", "score": 9}]'
        )
        mock_usage = TokenUsage(200, 100, 300)

        mock_session = MagicMock()

        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ),
        ):
            result = revise_node({
                "analyses": original_analyses,
                "review_feedback": "摘要需要更详细",
            })

        assert "analyses" in result
        assert len(result["analyses"]) == 2
        assert result["analyses"][0]["summary"] == "改进摘要"
        assert result["analyses"][1]["summary"] == "改进摘要B"
        assert result["cost_tracker"]["revise"]["prompt_tokens"] == 200
        mock_session.close.assert_called_once()

    def test_revise_cost_tracker_accumulated(self) -> None:
        """cost_tracker 中已有数据时累加。"""
        original_analyses = [{"title": "a"}]
        improved_json = '[{"title": "a (改)"}]'
        mock_usage = TokenUsage(50, 30, 80)

        mock_session = MagicMock()

        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ),
        ):
            result = revise_node({
                "analyses": original_analyses,
                "review_feedback": "需要改进",
                "cost_tracker": {
                    "analyze": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    }
                },
            })

        assert "analyze" in result["cost_tracker"]
        assert "revise" in result["cost_tracker"]
        assert result["cost_tracker"]["revise"]["prompt_tokens"] == 50

    def test_llm_failure_returns_empty(self) -> None:
        """LLM 调用失败时返回 {}。"""
        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                side_effect=LlmCallError("LLM down"),
            ),
        ):
            result = revise_node({
                "analyses": [{"title": "a"}],
                "review_feedback": "需要改进",
            })
        assert result == {}

    def test_length_mismatch_fallback(self) -> None:
        """输出数量与输入不一致时保留原始 analyses（不覆盖）。"""
        original_analyses = [
            {"title": "a"},
            {"title": "b"},
            {"title": "c"},
        ]
        # LLM 只返回 2 条，长度不匹配
        improved_json = '[{"title": "a改"}, {"title": "b改"}]'
        mock_usage = TokenUsage(50, 30, 80)

        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ),
        ):
            result = revise_node({
                "analyses": original_analyses,
                "review_feedback": "需要改进",
            })

        # 不返回 analyses，只返回 cost_tracker
        assert "analyses" not in result
        assert "cost_tracker" in result

    def test_revise_uses_temperature_04(self) -> None:
        """验证 LLM 调用使用 temperature=0.4。"""
        original_analyses = [{"title": "a"}]
        improved_json = '[{"title": "a改"}]'
        mock_usage = TokenUsage(50, 30, 80)

        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ) as mock_call,
        ):
            revise_node({
                "analyses": original_analyses,
                "review_feedback": "需要改进",
            })

        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs.kwargs["temperature"] == 0.4

    def test_revise_feedback_injected_into_prompt(self) -> None:
        """验证 feedback 被注入 prompt。"""
        original_analyses = [{"title": "a", "summary": "旧"}]
        improved_json = '[{"title": "a", "summary": "新"}]'
        mock_usage = TokenUsage(50, 30, 80)
        feedback_text = "摘要需要更加详细具体"

        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ) as mock_call,
        ):
            revise_node({
                "analyses": original_analyses,
                "review_feedback": feedback_text,
            })

        prompt_arg = mock_call.call_args.args[0]
        assert feedback_text in prompt_arg

    def test_revise_single_item_success(self) -> None:
        """单条 analyses 也能正常改写。"""
        original = [{"title": "only", "summary": "old"}]
        improved_json = '[{"title": "only", "summary": "new"}]'
        mock_usage = TokenUsage(30, 20, 50)

        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                return_value=(improved_json, mock_usage),
            ),
        ):
            result = revise_node({
                "analyses": original,
                "review_feedback": "改进",
            })

        assert len(result["analyses"]) == 1
        assert result["analyses"][0]["summary"] == "new"

    def test_revise_runtime_error_returns_empty(self) -> None:
        """无可用供应商-模型时返回 {}。"""
        mock_session = MagicMock()
        with (
            patch(
                "src.graph.nodes._get_session",
                return_value=mock_session,
            ),
            patch(
                "src.graph.nodes._call_llm",
                side_effect=RuntimeError("无可用 LLM 供应商-模型组合"),
            ),
        ):
            result = revise_node({
                "analyses": [{"title": "a"}],
                "review_feedback": "需要改进",
            })
        assert result == {}
