"""src.graph.nodes 模块的单元测试。

测试覆盖：
- collect_node: GitHub API 采集（mock urllib）
- analyze_node: LLM 分析（mock _call_llm_json）
- organize_node: 低分过滤 / URL 去重 / 反馈修正
- review_node: LLM 审核评分 / iteration 强制通过
- save_node: 文件写入 / index.json 更新
- 工具函数: _parse_json_output / _accumulate_usage / _safe_float / _to_article_dict
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch
from urllib.error import URLError

from src.graph.nodes import (
    _accumulate_usage,
    _parse_json_output,
    _safe_float,
    _to_article_dict,
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
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


class TestToArticleDict:
    """_to_article_dict 测试。"""

    def test_full_analysis(self) -> None:
        """完整分析结果转换为标准条目。"""
        analysis = {
            "title": "测试项目",
            "summary": "测试摘要",
            "tags": ["llm", "agent"],
            "score": 0.85,
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
        assert article["score"] == 0.85
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
        assert article["score"] == 0.0
        assert article["category"] == "news"
        assert article["language"] == "zh"


# ---------------------------------------------------------------------------
# collect_node 测试
# ---------------------------------------------------------------------------


class TestCollectNode:
    """collect_node 测试。"""

    def test_collect_success(self) -> None:
        """成功采集返回 sources 列表。"""
        mock_response_data = {
            "items": [
                {
                    "full_name": "test/repo1",
                    "html_url": "https://github.com/test/repo1",
                    "stargazers_count": 100,
                    "description": "A test repo",
                },
                {
                    "full_name": "test/repo2",
                    "html_url": "https://github.com/test/repo2",
                    "stargazers_count": 50,
                    "description": "Another repo",
                },
            ]
        }

        with patch("src.graph.nodes.urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock_urlopen.return_value
            mock_resp.__enter__ = lambda self: mock_resp
            mock_resp.__exit__ = lambda self, *args: None
            mock_resp.read.return_value = json.dumps(mock_response_data).encode()

            result = collect_node({})

        assert len(result["sources"]) == 2
        assert result["sources"][0]["title"] == "test/repo1"
        assert result["sources"][0]["url"] == "https://github.com/test/repo1"
        assert result["sources"][0]["source_score"] == 100
        assert result["sources"][0]["source_platform"] == "github_trending"

    def test_collect_network_error(self) -> None:
        """网络错误时返回空 sources。"""
        with patch(
            "src.graph.nodes.urllib.request.urlopen",
            side_effect=URLError("network error"),
        ):
            result = collect_node({})
        assert result["sources"] == []

    def test_collect_empty_response(self) -> None:
        """空响应返回空 sources。"""
        mock_response_data = {"items": []}
        with patch("src.graph.nodes.urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock_urlopen.return_value
            mock_resp.__enter__ = lambda self: mock_resp
            mock_resp.__exit__ = lambda self, *args: None
            mock_resp.read.return_value = json.dumps(mock_response_data).encode()

            result = collect_node({})
        assert result["sources"] == []


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
            "score": 0.8,
            "category": "tool",
            "language": "en",
        }
        mock_usage = TokenUsage(100, 50, 150)

        with (
            patch("src.graph.nodes._get_session") as mock_session,
            patch(
                "src.graph.nodes._call_llm_json",
                return_value=(mock_result, mock_usage),
            ),
        ):
            mock_session.return_value = mock_session
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


# ---------------------------------------------------------------------------
# organize_node 测试
# ---------------------------------------------------------------------------


class TestOrganizeNode:
    """organize_node 测试。"""

    def test_filter_low_score(self) -> None:
        """低分条目被过滤。"""
        analyses = [
            {"title": "good", "score": 0.8, "source_url": "url1"},
            {"title": "bad", "score": 0.3, "source_url": "url2"},
        ]
        result = organize_node({"analyses": analyses})
        assert len(result["articles"]) == 1
        assert result["articles"][0]["title"] == "good"

    def test_dedup_by_url(self) -> None:
        """相同 URL 的条目去重。"""
        analyses = [
            {"title": "a", "score": 0.8, "source_url": "same_url"},
            {"title": "b", "score": 0.9, "source_url": "same_url"},
        ]
        result = organize_node({"analyses": analyses})
        assert len(result["articles"]) == 1
        assert result["articles"][0]["title"] == "a"

    def test_no_feedback_no_llm(self) -> None:
        """无反馈时不调用 LLM。"""
        analyses = [{"title": "a", "score": 0.8, "source_url": "url1"}]
        with patch("src.graph.nodes._get_session") as mock_session:
            result = organize_node({"analyses": analyses, "iteration": 0})
            mock_session.assert_not_called()
        assert len(result["articles"]) == 1

    def test_with_feedback_calls_llm(self) -> None:
        """有反馈时调用 LLM 修正。"""
        analyses = [
            {
                "title": "a",
                "score": 0.8,
                "source_url": "url1",
                "summary": "old summary",
                "tags": ["tag1"],
            }
        ]
        mock_result = {
            "title": "a (修正)",
            "summary": "improved summary",
            "tags": ["tag1", "tag2"],
            "score": 0.9,
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


class TestReviewNode:
    """review_node 测试。"""

    def test_force_pass_at_max_iteration(self) -> None:
        """iteration >= 3 时强制通过，不调用 LLM。"""
        with patch("src.graph.nodes._get_session") as mock_session:
            result = review_node({
                "articles": [{"article_id": "kb-1"}],
                "iteration": 3,
            })
            mock_session.assert_not_called()
        assert result["review_passed"] is True
        assert result["review_feedback"] == ""
        assert result["iteration"] == 4

    def test_force_pass_at_iteration_2(self) -> None:
        """iteration=2 不是强制通过（需要 >= _MAX_ITERATIONS=3）。"""
        mock_result = {
            "passed": False,
            "overall_score": 5.0,
            "feedback": "需要改进",
            "scores": {},
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
                "articles": [{"article_id": "kb-1"}],
                "iteration": 2,
            })
        assert result["review_passed"] is False
        assert "需要改进" in result["review_feedback"]
        mock_session.close.assert_called_once()

    def test_review_passed(self) -> None:
        """审核通过时 review_passed=True, feedback 清空。"""
        mock_result = {
            "passed": True,
            "overall_score": 8.5,
            "feedback": "质量很好",
            "scores": {},
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
                "articles": [{"article_id": "kb-1"}],
                "iteration": 1,
            })
        assert result["review_passed"] is True
        assert result["review_feedback"] == ""

    def test_review_not_passed(self) -> None:
        """审核不通过时 review_passed=False, feedback 保留。"""
        mock_result = {
            "passed": False,
            "overall_score": 4.0,
            "feedback": "摘要过短",
            "scores": {},
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
                "articles": [{"article_id": "kb-1"}],
                "iteration": 1,
            })
        assert result["review_passed"] is False
        assert result["review_feedback"] == "摘要过短"

    def test_review_score_threshold_override(self) -> None:
        """passed=False 但 overall_score >= 7.0 时自动通过。"""
        mock_result = {
            "passed": False,
            "overall_score": 7.5,
            "feedback": "小问题",
            "scores": {},
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
                "articles": [{"article_id": "kb-1"}],
                "iteration": 1,
            })
        assert result["review_passed"] is True

    def test_empty_articles_auto_pass(self) -> None:
        """空 articles 自动通过。"""
        result = review_node({"articles": [], "iteration": 1})
        assert result["review_passed"] is True


# ---------------------------------------------------------------------------
# save_node 测试
# ---------------------------------------------------------------------------


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

        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")

            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
            ):
                result = save_node({"articles": articles})

            assert result["saved_count"] == 2

            file1 = os.path.join(articles_dir, "kb-test-0001.json")
            file2 = os.path.join(articles_dir, "kb-test-0002.json")
            assert os.path.exists(file1)
            assert os.path.exists(file2)

            with open(file1, encoding="utf-8") as f:
                saved = json.load(f)
            assert saved["title"] == "测试1"

            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            assert len(index) == 2
            assert index[0]["article_id"] == "kb-test-0001"

    def test_save_empty_articles(self) -> None:
        """空 articles 返回 saved_count=0。"""
        result = save_node({"articles": []})
        assert result["saved_count"] == 0

    def test_save_generates_article_id_if_missing(self) -> None:
        """缺少 article_id 时自动生成。"""
        articles = [{"title": "no id", "source_url": "url"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            articles_dir = os.path.join(tmpdir, "articles")
            index_file = os.path.join(articles_dir, "index.json")
            with (
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
                patch("src.graph.nodes._INDEX_FILE", index_file),
            ):
                result = save_node({"articles": articles})
            assert result["saved_count"] == 1
            assert articles[0]["article_id"].startswith("kb-")

    def test_save_updates_existing_index(self) -> None:
        """保存时合并已有索引。"""
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
            ):
                save_node({"articles": new_articles})

            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            assert len(index) == 2
            ids = [item["article_id"] for item in index]
            assert "kb-old-0001" in ids
            assert "kb-new-0001" in ids
