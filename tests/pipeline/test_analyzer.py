"""src.pipeline.analyzer 的单元测试。

测试覆盖：
- LLM 分析成功解析
- JSON 响应解析（直接/正则提取）
- 字段校验与补全
- LLM 不可用时降级分析
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.pipeline.analyzer import LLMAnalyzer


class TestLLMAnalyzerParse:
    """LLM 响应解析测试。"""

    def test_parse_valid_json(self) -> None:
        """直接解析合法 JSON。"""
        analyzer = LLMAnalyzer()
        raw = (
            '{"summary": "测试摘要", "highlights": ["亮点1"], '
            '"score": 8, "tags": ["llm"], "category": "tool", "language": "en"}'
        )
        item = {"title": "Test", "source": "github", "summary": "desc"}

        result = analyzer._parse_llm_response(raw, item)

        assert result["summary"] == "测试摘要"
        assert result["highlights"] == ["亮点1"]
        assert result["score"] == 8
        assert result["tags"] == ["llm"]
        assert result["category"] == "tool"
        assert result["language"] == "en"

    def test_parse_json_with_surrounding_text(self) -> None:
        """JSON 前后有额外文字时正则提取。"""
        analyzer = LLMAnalyzer()
        raw = (
            'Here is the analysis:\n'
            '{"summary": "摘要", "highlights": [], "score": 5, '
            '"tags": ["ai"], "category": "news", "language": "zh"}\n'
            'Done.'
        )
        item = {"title": "Test", "source": "rss", "summary": "desc"}

        result = analyzer._parse_llm_response(raw, item)

        assert result["summary"] == "摘要"
        assert result["score"] == 5
        assert result["category"] == "news"

    def test_parse_invalid_json_raises(self) -> None:
        """完全无法解析的 JSON 抛出 RuntimeError。"""
        analyzer = LLMAnalyzer()
        raw = "This is not JSON at all"
        item = {"title": "Test", "source": "github", "summary": "desc"}

        with pytest.raises(RuntimeError, match="解析失败"):
            analyzer._parse_llm_response(raw, item)


class TestLLMAnalyzerValidate:
    """字段校验测试。"""

    def test_clamp_score_high(self) -> None:
        """评分超过 10 被截断为 10。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 15, "tags": ["llm"], "category": "tool", "language": "en"},
            {"summary": "desc"},
        )
        assert result["score"] == 10

    def test_clamp_score_low(self) -> None:
        """评分低于 1 被截断为 1。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": -3, "tags": ["llm"], "category": "tool", "language": "en"},
            {"summary": "desc"},
        )
        assert result["score"] == 1

    def test_invalid_score_defaults_to_5(self) -> None:
        """非数字评分默认为 5。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": "abc", "tags": ["llm"], "category": "tool", "language": "en"},
            {"summary": "desc"},
        )
        assert result["score"] == 5

    def test_invalid_category_defaults_to_news(self) -> None:
        """非法分类默认为 news。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": ["llm"], "category": "invalid", "language": "en"},
            {"summary": "desc"},
        )
        assert result["category"] == "news"

    def test_invalid_language_defaults_to_en(self) -> None:
        """非法语言默认为 en。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": ["llm"], "category": "tool", "language": "fr"},
            {"summary": "desc"},
        )
        assert result["language"] == "en"

    def test_empty_summary_falls_back_to_item(self) -> None:
        """空摘要降级为原始描述。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": ["llm"], "category": "tool", "language": "en",
             "summary": ""},
            {"summary": "Original description text here"},
        )
        assert "Original description" in result["summary"]

    def test_tags_lowercased(self) -> None:
        """标签被转为小写。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": ["LLM", "RAG", "Agent"], "category": "tool",
             "language": "en", "summary": "test"},
            {"summary": "desc"},
        )
        assert all(t == t.lower() for t in result["tags"])

    def test_non_list_tags_handled(self) -> None:
        """非列表标签被替换为空列表。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": "not-a-list", "category": "tool",
             "language": "en", "summary": "test"},
            {"summary": "desc"},
        )
        assert result["tags"] == []

    def test_non_list_highlights_handled(self) -> None:
        """非列表亮点被替换为空列表。"""
        analyzer = LLMAnalyzer()
        result = analyzer._validate_result(
            {"score": 5, "tags": ["llm"], "category": "tool",
             "language": "en", "summary": "test", "highlights": "not-a-list"},
            {"summary": "desc"},
        )
        assert result["highlights"] == []


class TestLLMAnalyzerFallback:
    """降级分析测试。"""

    def test_fallback_model_release(self) -> None:
        """标题含 GPT 关键词分类为 model_release。"""
        analyzer = LLMAnalyzer()
        item = {"title": "GPT-5 Released", "summary": "New model from OpenAI", "source": "github"}
        result = analyzer._fallback_analyze(item)

        assert result["category"] == "model_release"
        assert result["score"] == 5
        assert len(result["tags"]) > 0

    def test_fallback_paper(self) -> None:
        """标题含 paper/arxiv 分类为 paper。"""
        analyzer = LLMAnalyzer()
        item = {"title": "New arxiv paper on transformers", "summary": "Research", "source": "rss"}
        result = analyzer._fallback_analyze(item)

        assert result["category"] == "paper"

    def test_fallback_tool(self) -> None:
        """标题含 framework 分类为 tool。"""
        analyzer = LLMAnalyzer()
        item = {"title": "New LLM framework", "summary": "A framework", "source": "github"}
        result = analyzer._fallback_analyze(item)

        assert result["category"] == "tool"

    def test_fallback_tutorial(self) -> None:
        """标题含 guide 分类为 tutorial。"""
        analyzer = LLMAnalyzer()
        item = {"title": "How-to guide for RAG", "summary": "Tutorial", "source": "rss"}
        result = analyzer._fallback_analyze(item)

        assert result["category"] == "tutorial"

    def test_fallback_news(self) -> None:
        """无匹配关键词分类为 news。"""
        analyzer = LLMAnalyzer()
        item = {"title": "AI industry update", "summary": "Market news", "source": "rss"}
        result = analyzer._fallback_analyze(item)

        assert result["category"] == "news"

    def test_fallback_extracts_tags(self) -> None:
        """降级分析从标题提取关键词作为标签。"""
        analyzer = LLMAnalyzer()
        item = {
            "title": "RAG Agent with embedding",
            "summary": "rag agent embedding",
            "source": "github",
        }
        result = analyzer._fallback_analyze(item)

        assert "rag" in result["tags"]
        assert "agent" in result["tags"]
        assert "embedding" in result["tags"]

    def test_fallback_default_tag(self) -> None:
        """无关键词匹配时使用默认标签 ai。"""
        analyzer = LLMAnalyzer()
        item = {"title": "Something new", "summary": "No keywords here", "source": "rss"}
        result = analyzer._fallback_analyze(item)

        assert "ai" in result["tags"]


class TestLLMAnalyzerAnalyze:
    """analyze 方法集成测试。"""

    @patch("src.pipeline.analyzer.LLMAnalyzer._analyze_with_llm")
    def test_analyze_uses_llm_on_success(self, mock_llm: patch) -> None:
        """LLM 成功时使用 LLM 结果。"""
        mock_llm.return_value = {
            "summary": "LLM summary",
            "highlights": ["h1"],
            "score": 8,
            "tags": ["llm"],
            "category": "tool",
            "language": "en",
        }
        analyzer = LLMAnalyzer()
        item = {"title": "Test", "summary": "desc", "source": "github"}

        result = analyzer.analyze(item)

        assert result["summary"] == "LLM summary"
        assert result["score"] == 8

    @patch.object(LLMAnalyzer, "_analyze_with_llm")
    def test_analyze_falls_back_on_error(self, mock_llm: patch) -> None:
        """LLM 失败时降级为规则分析。"""
        from src.llm.client import LlmCallError, LlmErrorType

        mock_llm.side_effect = LlmCallError(
            "failed",
            error_type=LlmErrorType.UNKNOWN,
        )
        analyzer = LLMAnalyzer()
        item = {"title": "GPT-5 Released", "summary": "New model", "source": "github"}

        result = analyzer.analyze(item)

        assert result["category"] == "model_release"
        assert result["score"] == 5

    @patch.object(LLMAnalyzer, "_analyze_with_llm")
    def test_analyze_falls_back_on_runtime_error(self, mock_llm: patch) -> None:
        """RuntimeError（无供应商）时降级。"""
        mock_llm.side_effect = RuntimeError("No provider available")
        analyzer = LLMAnalyzer()
        item = {"title": "LLM tool", "summary": "A tool", "source": "github"}

        result = analyzer.analyze(item)

        assert result["category"] == "tool"


class TestGetRetryParams:
    """_get_retry_params 时间窗口策略测试。"""

    def test_daytime_returns_max_attempts_3(self) -> None:
        """白天 14:00 返回 max_attempts=3。"""
        import datetime

        from src.pipeline.analyzer import _get_retry_params

        params = _get_retry_params(
            now=datetime.datetime(2026, 7, 30, 14, 0, 0)
        )
        assert params["max_attempts"] == 3
        assert params["base_delay"] == 1.0
        assert params["backoff_factor"] == 2.0

    def test_nighttime_returns_max_attempts_1(self) -> None:
        """夜间 23:00 返回 max_attempts=1。"""
        import datetime

        from src.pipeline.analyzer import _get_retry_params

        params = _get_retry_params(
            now=datetime.datetime(2026, 7, 30, 23, 0, 0)
        )
        assert params["max_attempts"] == 1

    def test_boundary_08_returns_3(self) -> None:
        """08:00 边界返回 max_attempts=3。"""
        import datetime

        from src.pipeline.analyzer import _get_retry_params

        params = _get_retry_params(
            now=datetime.datetime(2026, 7, 30, 8, 0, 0)
        )
        assert params["max_attempts"] == 3

    def test_boundary_22_returns_1(self) -> None:
        """22:00 边界返回 max_attempts=1。"""
        import datetime

        from src.pipeline.analyzer import _get_retry_params

        params = _get_retry_params(
            now=datetime.datetime(2026, 7, 30, 22, 0, 0)
        )
        assert params["max_attempts"] == 1


class TestAnalyzeFallbackExtended:
    """analyze() 降级测试 -- BudgetExceededError / NonRetryableLlmError / LlmCallError。"""

    @patch.object(LLMAnalyzer, "_analyze_with_llm")
    def test_analyze_falls_back_on_budget_exceeded(self, mock_llm: patch) -> None:
        """BudgetExceededError 降级为规则分析。"""
        from src.llm.budget import BudgetExceededError

        mock_llm.side_effect = BudgetExceededError(
            "budget exceeded",
            daily_limit=100.0,
            daily_spent=90.0,
            estimated_cost=20.0,
            currency="CNY",
        )
        analyzer = LLMAnalyzer()
        item = {"title": "GPT-5 Released", "summary": "New model", "source": "github"}

        result = analyzer.analyze(item)

        assert result["category"] == "model_release"
        assert result["score"] == 5

    @patch.object(LLMAnalyzer, "_analyze_with_llm")
    def test_analyze_falls_back_on_non_retryable_llm_error(
        self, mock_llm: patch
    ) -> None:
        """NonRetryableLlmError 降级为规则分析。"""
        from src.llm.client import LlmCallError, LlmErrorType
        from src.llm.retry_decorator import NonRetryableLlmError

        original = LlmCallError(
            "auth failed",
            error_type=LlmErrorType.AUTH_FAILED,
        )
        mock_llm.side_effect = NonRetryableLlmError(original)
        analyzer = LLMAnalyzer()
        item = {"title": "LLM tool", "summary": "A tool", "source": "github"}

        result = analyzer.analyze(item)

        assert result["category"] == "tool"
        assert result["score"] == 5

    @patch.object(LLMAnalyzer, "_analyze_with_llm")
    def test_analyze_falls_back_on_llm_call_error_retry_exhausted(
        self, mock_llm: patch
    ) -> None:
        """LlmCallError（重试耗尽后）降级为规则分析。"""
        from src.llm.client import LlmCallError, LlmErrorType

        mock_llm.side_effect = LlmCallError(
            "timeout after retries",
            error_type=LlmErrorType.TIMEOUT,
        )
        analyzer = LLMAnalyzer()
        item = {"title": "Something new", "summary": "desc", "source": "rss"}

        result = analyzer.analyze(item)

        assert result["category"] == "news"
        assert result["score"] == 5
