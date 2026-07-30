"""src.graph.nodes 模块的单元测试。

测试覆盖：
- collect_node: GitHub API 采集（mock _fetch_github_repos_with_retry）
- analyze_node: LLM 分析（mock _call_llm_json）
- organize_node: 低分过滤 / URL 去重 / 反馈修正
- review_node: LLM 审核评分 / iteration 强制通过
- save_node: DB 写入 + 文件写入 / index.json 更新
- 工具函数: _parse_json_output / _accumulate_usage / _safe_float
  / _safe_int_score / _to_article_dict
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from src.graph.nodes import (
    _accumulate_usage,
    _compute_weighted_score,
    _parse_json_output,
    _safe_float,
    _safe_int_score,
    _to_article_dict,
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from src.llm.client import LlmCallError
from src.llm.cost import TokenUsage

# ---------------------------------------------------------------------------
# 工具函数测试
# ---------------------------------------------------------------------------


class TestParseJsonOutput:
    """_parse_json_output 测试。"""

    def test_parse_clean_json(self) -> None:
        """干净 JSON 直接解析。"""
        result = _parse_json_output('{"key": "value"}', "test")
        assert result == {"key": "value"}

    def test_parse_json_with_prefix(self) -> None:
        """带前缀文本的 JSON 能提取。"""
        result = _parse_json_output(
            'Here is the result:\n{"key": "value"}', "test"
        )
        assert result == {"key": "value"}

    def test_parse_json_with_suffix(self) -> None:
        """带后缀文本的 JSON 能提取。"""
        result = _parse_json_output(
            '{"key": "value"}\nDone.', "test"
        )
        assert result == {"key": "value"}

    def test_parse_json_with_code_fence(self) -> None:
        """markdown code fence 包裹的 JSON 能提取。"""
        result = _parse_json_output(
            '```json\n{"key": "value"}\n```', "test"
        )
        assert result == {"key": "value"}

    def test_parse_invalid_raises(self) -> None:
        """无法解析的文本抛出 ValueError。"""
        try:
            _parse_json_output("not json at all", "test")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "test" in str(exc)


class TestAccumulateUsage:
    """_accumulate_usage 测试。"""

    def test_accumulate_new_node(self) -> None:
        """新节点的用量被初始化。"""
        tracker: dict = {}
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        _accumulate_usage(tracker, "analyze", usage)
        assert tracker["analyze"]["prompt_tokens"] == 100
        assert tracker["analyze"]["completion_tokens"] == 50
        assert tracker["analyze"]["total_tokens"] == 150

    def test_accumulate_existing_node(self) -> None:
        """已有节点的用量被累加。"""
        tracker: dict = {
            "analyze": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }
        usage = TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300)
        _accumulate_usage(tracker, "analyze", usage)
        assert tracker["analyze"]["prompt_tokens"] == 300
        assert tracker["analyze"]["completion_tokens"] == 150
        assert tracker["analyze"]["total_tokens"] == 450


class TestSafeFloat:
    """_safe_float 测试。"""

    def test_valid_float(self) -> None:
        assert _safe_float(0.8) == 0.8

    def test_valid_string(self) -> None:
        assert _safe_float("0.6") == 0.6

    def test_valid_int(self) -> None:
        assert _safe_float(1) == 1.0

    def test_invalid_string(self) -> None:
        assert _safe_float("abc") == 0.0

    def test_none(self) -> None:
        assert _safe_float(None) == 0.0


class TestSafeIntScore:
    """_safe_int_score 测试。"""

    def test_valid_int(self) -> None:
        assert _safe_int_score(8) == 8

    def test_valid_float(self) -> None:
        assert _safe_int_score(8.7) == 8

    def test_valid_string(self) -> None:
        assert _safe_int_score("7") == 7

    def test_clamp_above_10(self) -> None:
        assert _safe_int_score(15) == 10

    def test_clamp_below_1(self) -> None:
        assert _safe_int_score(0) == 1

    def test_invalid_string(self) -> None:
        assert _safe_int_score("abc") == 5

    def test_none(self) -> None:
        assert _safe_int_score(None) == 5


class TestToArticleDict:
    """_to_article_dict 测试。"""

    def test_full_analysis(self) -> None:
        """完整分析结果转换为标准条目。"""
        analysis = {
            "title": "测试项目",
            "summary": "测试摘要",
            "tags": ["llm", "agent"],
            "score": 8,
            "category": "tool",
            "language": "en",
            "source_url": "https://github.com/test/repo",
            "source_platform": "github_trending",
            "source_score": 100,
        }
        article = _to_article_dict(analysis)
        assert article["title"] == "测试项目"
        assert article["summary"] == "测试摘要"
        assert article["tags"] == ["llm", "agent"]
        assert article["score"] == 8
        assert article["status"] == "pending"
        assert article["category"] == "tool"
        assert article["language"] == "en"
        assert article["source_url"] == "https://github.com/test/repo"
        assert article["article_id"].startswith("kb-")

    def test_missing_fields_defaults(self) -> None:
        """缺少字段时使用默认值。"""
        article = _to_article_dict({})
        assert article["title"] == ""
        assert article["summary"] == ""
        assert article["tags"] == []
        assert article["score"] == 5
        assert article["category"] == "news"
        assert article["language"] == "zh"

    def test_article_id_has_random_suffix(self) -> None:
        """生成的 article_id 包含随机后缀，短时间内不碰撞。"""
        ids = {_to_article_dict({})["article_id"] for _ in range(20)}
        assert len(ids) == 20, "article_id 在同秒内应不碰撞"


# ---------------------------------------------------------------------------
# collect_node 测试
# ---------------------------------------------------------------------------


class TestCollectNode:
    """collect_node 测试。"""

    def test_collect_success(self) -> None:
        """成功采集返回 sources 列表。"""
        mock_sources = [
            {
                "title": "test/repo1",
                "url": "https://github.com/test/repo1",
                "source_platform": "github_trending",
                "source_score": 100,
                "summary": "A test repo",
                "content_path": "",
            },
            {
                "title": "test/repo2",
                "url": "https://github.com/test/repo2",
                "source_platform": "github_trending",
                "source_score": 50,
                "summary": "Another repo",
                "content_path": "",
            },
        ]

        mock_collector = MagicMock()
        mock_collector.collect.return_value = mock_sources
        with patch(
            "src.graph.nodes.default_registry.get_all",
            return_value=[("github", mock_collector)],
        ):
            result = collect_node({})

        assert len(result["sources"]) == 2
        assert result["sources"][0]["title"] == "test/repo1"
        assert result["sources"][0]["url"] == "https://github.com/test/repo1"
        assert result["sources"][0]["source_score"] == 100
        assert result["sources"][0]["source_platform"] == "github_trending"

    def test_collect_network_error(self) -> None:
        """采集器失败时返回空 sources 和 errors。"""
        mock_collector = MagicMock()
        mock_collector.collect.side_effect = RuntimeError("network error")
        with patch(
            "src.graph.nodes.default_registry.get_all",
            return_value=[("github", mock_collector)],
        ):
            result = collect_node({})
        assert result["sources"] == []
        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["node"] == "collect"

    def test_collect_empty_response(self) -> None:
        """空响应返回空 sources。"""
        mock_collector = MagicMock()
        mock_collector.collect.return_value = []
        with patch(
            "src.graph.nodes.default_registry.get_all",
            return_value=[("github", mock_collector)],
        ):
            result = collect_node({})
        assert result["sources"] == []

    def test_collect_multi_source(self) -> None:
        """多采集器聚合：github + rss 结果合并。"""
        github_items = [
            {
                "title": "repo1",
                "url": "https://github.com/repo1",
                "source_platform": "github_trending",
                "source_score": 100,
                "summary": "GitHub repo",
                "content_path": "",
            },
        ]
        rss_items = [
            {
                "title": "AI News",
                "url": "https://hn.example.com/123",
                "source_platform": "hackernews",
                "source_score": 0,
                "summary": "RSS article",
                "content_path": "",
            },
        ]
        mock_github = MagicMock()
        mock_github.collect.return_value = github_items
        mock_rss = MagicMock()
        mock_rss.collect.return_value = rss_items
        with patch(
            "src.graph.nodes.default_registry.get_all",
            return_value=[("github", mock_github), ("rss", mock_rss)],
        ):
            result = collect_node({})

        assert len(result["sources"]) == 2
        assert result["sources"][0]["source_platform"] == "github_trending"
        assert result["sources"][1]["source_platform"] == "hackernews"

    def test_collect_partial_failure(self) -> None:
        """一个采集器失败不阻塞其他采集器。"""
        good_items = [
            {
                "title": "repo1",
                "url": "https://github.com/repo1",
                "source_platform": "github_trending",
                "source_score": 100,
                "summary": "GitHub repo",
                "content_path": "",
            },
        ]
        mock_good = MagicMock()
        mock_good.collect.return_value = good_items
        mock_bad = MagicMock()
        mock_bad.collect.side_effect = RuntimeError("RSS timeout")
        with patch(
            "src.graph.nodes.default_registry.get_all",
            return_value=[("github", mock_good), ("rss", mock_bad)],
        ):
            result = collect_node({})

        assert len(result["sources"]) == 1
        assert "errors" in result
        assert len(result["errors"]) == 1
        assert "[rss]" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# analyze_node 测试
# ---------------------------------------------------------------------------


class TestAnalyzeNode:
    """analyze_node 测试。"""

    def test_analyze_empty_sources(self) -> None:
        """无 sources 时返回空 analyses。"""
        result = analyze_node({"sources": []})
        assert result["analyses"] == []

    def test_analyze_success(self) -> None:
        """成功分析返回 analyses 列表。"""
        mock_result = {
            "title": "测试仓库",
            "summary": "测试摘要",
            "tags": ["llm"],
            "score": 8,
            "category": "tool",
            "language": "en",
        }
        mock_usage = TokenUsage(100, 50, 150)

        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_model = MagicMock()

        with (
            patch("src.graph.nodes._get_session", return_value=mock_session),
            patch(
                "src.graph.nodes.select_first_available",
                return_value=(mock_provider, mock_model),
            ),
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            result = analyze_node({
                "sources": [
                    {
                        "title": "test/repo",
                        "url": "https://github.com/test/repo",
                        "source_score": 100,
                        "summary": "A repo",
                        "source_platform": "github_trending",
                    }
                ],
            })

        assert len(result["analyses"]) == 1
        assert result["analyses"][0]["title"] == "测试仓库"
        assert result["analyses"][0]["source_url"] == "https://github.com/test/repo"
        assert result["cost_tracker"]["analyze"]["prompt_tokens"] == 100
        mock_session.close.assert_called_once()

    def test_analyze_caches_provider_model(self) -> None:
        """analyze_node 只查询一次 provider/model。"""
        mock_usage = TokenUsage(10, 5, 15)
        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_model = MagicMock()

        with (
            patch("src.graph.nodes._get_session", return_value=mock_session),
            patch(
                "src.graph.nodes.select_first_available",
                return_value=(mock_provider, mock_model),
            ) as mock_select,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=({"title": "t", "score": 9}, mock_usage),
            ),
        ):
            result = analyze_node({
                "sources": [
                    {
                        "title": "a",
                        "url": "u1",
                        "source_score": 1,
                        "summary": "",
                        "source_platform": "",
                    },
                    {
                        "title": "b",
                        "url": "u2",
                        "source_score": 2,
                        "summary": "",
                        "source_platform": "",
                    },
                ],
            })

        assert len(result["analyses"]) == 2
        mock_select.assert_called_once()


# ---------------------------------------------------------------------------
# organize_node 测试
# ---------------------------------------------------------------------------


class TestOrganizeNode:
    """organize_node 测试。"""

    def test_filter_low_score(self) -> None:
        """低分条目被过滤。"""
        analyses = [
            {"title": "good", "score": 8, "source_url": "url1"},
            {"title": "bad", "score": 3, "source_url": "url2"},
        ]
        result = organize_node({"analyses": analyses})
        assert len(result["articles"]) == 1
        assert result["articles"][0]["title"] == "good"

    def test_dedup_by_url(self) -> None:
        """相同 URL 的条目去重。"""
        analyses = [
            {"title": "a", "score": 8, "source_url": "same_url"},
            {"title": "b", "score": 9, "source_url": "same_url"},
        ]
        result = organize_node({"analyses": analyses})
        assert len(result["articles"]) == 1
        assert result["articles"][0]["title"] == "a"

    def test_no_feedback_no_llm(self) -> None:
        """无反馈时不调用 LLM。"""
        analyses = [{"title": "a", "score": 8, "source_url": "url1"}]
        with patch("src.graph.nodes._get_session") as mock_session:
            result = organize_node({"analyses": analyses, "iteration": 0})
            mock_session.assert_not_called()
        assert len(result["articles"]) == 1

    def test_with_feedback_calls_llm(self) -> None:
        """有反馈时调用 LLM 修正。"""
        analyses = [
            {
                "title": "a",
                "score": 8,
                "source_url": "url1",
                "summary": "old summary",
                "tags": ["tag1"],
            }
        ]
        mock_result = {
            "title": "a (修正)",
            "summary": "improved summary",
            "tags": ["tag1", "tag2"],
            "score": 9,
        }
        mock_usage = TokenUsage(50, 30, 80)

        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = organize_node({
                "analyses": analyses,
                "iteration": 1,
                "review_feedback": "摘要需要改进",
            })

        assert len(result["articles"]) == 1
        assert result["articles"][0]["summary"] == "improved summary"
        assert result["cost_tracker"]["organize"]["prompt_tokens"] == 50
        mock_session.close.assert_called_once()

    def test_empty_analyses(self) -> None:
        """空 analyses 返回空 articles。"""
        result = organize_node({"analyses": []})
        assert result["articles"] == []


# ---------------------------------------------------------------------------
# review_node 测试
# ---------------------------------------------------------------------------


class TestComputeWeightedScore:
    """_compute_weighted_score 测试。"""

    def test_perfect_scores(self) -> None:
        """全 10 分时加权总分为 10.0。"""
        scores = {
            "summary_quality": 10,
            "technical_depth": 10,
            "relevance": 10,
            "originality": 10,
            "formatting": 10,
        }
        assert _compute_weighted_score(scores) == 10.0

    def test_all_zero(self) -> None:
        """全 0 分时加权总分为 0.0。"""
        scores = {
            "summary_quality": 0,
            "technical_depth": 0,
            "relevance": 0,
            "originality": 0,
            "formatting": 0,
        }
        assert _compute_weighted_score(scores) == 0.0

    def test_weighted_calculation(self) -> None:
        """验证加权计算正确性。"""
        scores = {
            "summary_quality": 8,   # 8 * 0.25 = 2.0
            "technical_depth": 6,   # 6 * 0.25 = 1.5
            "relevance": 7,         # 7 * 0.20 = 1.4
            "originality": 5,       # 5 * 0.15 = 0.75
            "formatting": 9,        # 9 * 0.15 = 1.35
        }                          # total = 7.0
        assert _compute_weighted_score(scores) == 7.0

    def test_missing_dimension_treated_as_zero(self) -> None:
        """缺失维度按 0 分处理。"""
        scores = {
            "summary_quality": 10,  # 10 * 0.25 = 2.5
            "technical_depth": 10,  # 10 * 0.25 = 2.5
            # relevance missing -> 0 * 0.20 = 0
            "originality": 10,      # 10 * 0.15 = 1.5
            "formatting": 10,       # 10 * 0.15 = 1.5
        }                          # total = 8.0
        assert _compute_weighted_score(scores) == 8.0

    def test_clamp_above_10(self) -> None:
        """超过 10 的分数被 clamp 到 10。"""
        scores = {
            "summary_quality": 15,
            "technical_depth": 20,
            "relevance": 10,
            "originality": 10,
            "formatting": 10,
        }
        assert _compute_weighted_score(scores) == 10.0

    def test_clamp_below_0(self) -> None:
        """负分被 clamp 到 0。"""
        scores = {
            "summary_quality": -5,
            "technical_depth": 10,
            "relevance": 10,
            "originality": 10,
            "formatting": 10,
        }
        # summary_quality=0, others=10: 0*0.25 + 10*0.25 + 10*0.20 + 10*0.15 + 10*0.15
        # = 0 + 2.5 + 2.0 + 1.5 + 1.5 = 7.5
        assert _compute_weighted_score(scores) == 7.5

    def test_string_scores(self) -> None:
        """字符串数字也能正确转换。"""
        scores = {
            "summary_quality": "8",
            "technical_depth": "6",
            "relevance": "7",
            "originality": "5",
            "formatting": "9",
        }
        assert _compute_weighted_score(scores) == 7.0


# ---------------------------------------------------------------------------
# review_node 测试
# ---------------------------------------------------------------------------


class TestReviewNode:
    """review_node 测试。"""

    def test_force_pass_at_max_iteration(self) -> None:
        """iteration >= 3 时不调 LLM，返回 review_passed=False（转人工标记）。"""
        with patch("src.graph.nodes._get_session") as mock_session:
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 3,
            })
            mock_session.assert_not_called()
        assert result["review_passed"] is False
        assert "人工" in result["review_feedback"]
        assert result["iteration"] == 3

    def test_force_pass_at_iteration_2(self) -> None:
        """iteration=2 不是强制通过（需要 >= _MAX_ITERATIONS=3）。"""
        mock_result = {
            "scores": {
                "summary_quality": 4,
                "technical_depth": 5,
                "relevance": 4,
                "originality": 5,
                "formatting": 5,
            },
            "feedback": "需要改进",
        }
        mock_usage = TokenUsage(50, 20, 70)
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 2,
            })
        assert result["review_passed"] is False
        assert "需要改进" in result["review_feedback"]
        mock_session.close.assert_called_once()

    def test_review_passed(self) -> None:
        """高分时 review_passed=True, feedback 清空。"""
        mock_result = {
            "scores": {
                "summary_quality": 9,
                "technical_depth": 8,
                "relevance": 9,
                "originality": 7,
                "formatting": 8,
            },
            "feedback": "质量很好",
        }
        mock_usage = TokenUsage(50, 20, 70)
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 1,
            })
        assert result["review_passed"] is True
        assert result["review_feedback"] == ""

    def test_review_not_passed(self) -> None:
        """低分时 review_passed=False, feedback 保留。"""
        mock_result = {
            "scores": {
                "summary_quality": 3,
                "technical_depth": 4,
                "relevance": 3,
                "originality": 4,
                "formatting": 5,
            },
            "feedback": "摘要过短",
        }
        mock_usage = TokenUsage(50, 20, 70)
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 1,
            })
        assert result["review_passed"] is False
        assert result["review_feedback"] == "摘要过短"

    def test_review_threshold_boundary(self) -> None:
        """加权总分正好 7.0 时通过。"""
        mock_result = {
            "scores": {
                "summary_quality": 8,   # 2.0
                "technical_depth": 6,   # 1.5
                "relevance": 7,         # 1.4
                "originality": 5,       # 0.75
                "formatting": 9,        # 1.35
            },                          # total = 7.0
            "feedback": "边界分",
        }
        mock_usage = TokenUsage(50, 20, 70)
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 1,
            })
        assert result["review_passed"] is True
        assert result["review_feedback"] == ""

    def test_llm_failure_auto_pass(self) -> None:
        """LLM 调用失败时自动通过，不阻塞流程。"""
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                side_effect=LlmCallError("LLM down"),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 1,
            })
        assert result["review_passed"] is True
        assert result["review_feedback"] == ""
        assert result["iteration"] == 2

    def test_empty_analyses_auto_pass(self) -> None:
        """空 analyses 自动通过。"""
        result = review_node({"analyses": [], "iteration": 1})
        assert result["review_passed"] is True

    def test_only_reviews_first_5(self) -> None:
        """只审核前 5 条 analyses。"""
        mock_result = {
            "scores": {
                "summary_quality": 9,
                "technical_depth": 9,
                "relevance": 9,
                "originality": 9,
                "formatting": 9,
            },
            "feedback": "",
        }
        mock_usage = TokenUsage(50, 20, 70)

        captured_prompt = []

        def _capture_prompt(
            prompt: str,
            session: object,
            **kwargs: object,
        ) -> tuple[dict[str, object], TokenUsage]:
            captured_prompt.append(prompt)
            return mock_result, mock_usage

        analyses = [{"title": f"item-{i}"} for i in range(10)]

        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                side_effect=_capture_prompt,
            ),
        ):
            mock_session.return_value = mock_session
            review_node({"analyses": analyses, "iteration": 1})

        assert len(captured_prompt) == 1
        # prompt 中应包含前 5 条，不应包含第 6-10 条
        assert "item-4" in captured_prompt[0]
        assert "item-5" not in captured_prompt[0]

    def test_cost_tracker_accumulated(self) -> None:
        """审核的 token 用量累加到 cost_tracker。"""
        mock_result = {
            "scores": {
                "summary_quality": 9,
                "technical_depth": 9,
                "relevance": 9,
                "originality": 9,
                "formatting": 9,
            },
            "feedback": "",
        }
        mock_usage = TokenUsage(100, 40, 140)
        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
            result = review_node({
                "analyses": [{"title": "a"}],
                "iteration": 1,
                "cost_tracker": {
                    "analyze": {
                        "prompt_tokens": 200,
                        "completion_tokens": 100,
                        "total_tokens": 300,
                    }
                },
            })
        assert "review" in result["cost_tracker"]
        assert result["cost_tracker"]["review"]["prompt_tokens"] == 100
        assert "analyze" in result["cost_tracker"]


# ---------------------------------------------------------------------------
# save_node 测试
# ---------------------------------------------------------------------------


def _make_mock_session_scope() -> MagicMock:
    """创建模拟的 session_scope 上下文管理器。"""
    mock_session = MagicMock()
    mock_orm_obj = MagicMock()
    mock_orm_obj.id = 1
    mock_session.add.return_value = None
    mock_session.flush.return_value = None

    # session.add 后，返回的 ORM 对象需要有 id
    def _add_side_effect(obj: object) -> None:
        obj.id = 1

    mock_session.add.side_effect = _add_side_effect

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = lambda self: mock_session
    mock_ctx.__exit__ = lambda self, *args: None
    mock_scope = MagicMock(return_value=mock_ctx)
    return mock_scope


class TestSaveNode:
    """save_node 测试。"""

    def test_save_articles(self) -> None:
        """成功保存文章并更新索引。"""
        articles = [
            {
                "article_id": "kb-test-0001",
                "title": "测试1",
                "source_url": "https://github.com/test1",
                "category": "tool",
                "status": "pending",
                "summary": "摘要1",
                "tags": ["llm"],
            },
            {
                "article_id": "kb-test-0002",
                "title": "测试2",
                "source_url": "https://github.com/test2",
                "category": "paper",
                "status": "pending",
                "summary": "摘要2",
                "tags": ["rag"],
            },
        ]

        mock_scope = _make_mock_session_scope()

        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")

            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
                patch("src.graph.nodes.session_scope", mock_scope),
            ):
                result = save_node({"articles": articles})

            assert result["saved_count"] == 2

    def test_save_empty_articles(self) -> None:
        """空 articles 返回 saved_count=0。"""
        result = save_node({"articles": []})
        assert result["saved_count"] == 0

    def test_save_generates_article_id_if_missing(self) -> None:
        """缺少 article_id 时自动生成。"""
        articles = [{"title": "no id", "source_url": "url"}]
        mock_scope = _make_mock_session_scope()

        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")
            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
                patch("src.graph.nodes.session_scope", mock_scope),
            ):
                result = save_node({"articles": articles})
            assert result["saved_count"] == 1
            # 索引中的 article_id 被回填为正式格式（build_article_id 输出）
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            assert len(index) == 1
            assert index[0]["article_id"].startswith("kb-")

    def test_save_does_not_mutate_input(self) -> None:
        """save_node 不 mutate 输入 article dict。"""
        original_article = {
            "article_id": None,
            "title": "test",
            "source_url": "url",
            "status": "pending",
        }
        articles = [dict(original_article)]
        mock_scope = _make_mock_session_scope()

        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")
            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
                patch("src.graph.nodes.session_scope", mock_scope),
            ):
                save_node({"articles": articles})

        # 原始 dict 的 article_id 不应被修改（浅拷贝保护）
        assert articles[0]["article_id"] is None

    def test_save_updates_existing_index(self) -> None:
        """保存时合并已有索引。"""
        mock_scope = _make_mock_session_scope()

        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")
            os.makedirs(articles_dir)

            existing_index = [
                {
                    "article_id": "kb-old-0001",
                    "title": "旧条目",
                    "source_url": "old_url",
                    "category": "tool",
                    "status": "published",
                }
            ]
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(existing_index, f)

            new_articles = [
                {
                    "article_id": "kb-new-0001",
                    "title": "新条目",
                    "source_url": "new_url",
                    "category": "paper",
                    "status": "pending",
                }
            ]

            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
                patch("src.graph.nodes.session_scope", mock_scope),
            ):
                save_node({"articles": new_articles})

            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            assert len(index) == 2
            ids = [item["article_id"] for item in index]
            assert "kb-old-0001" in ids
            # save_node 用 DB 自增主键回填 article_id，格式为 kb-YYYYMMDD-0001
            new_ids = [aid for aid in ids if aid != "kb-old-0001"]
            assert len(new_ids) == 1
            assert new_ids[0].startswith("kb-")
