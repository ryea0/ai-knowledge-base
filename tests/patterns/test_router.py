"""src.patterns.router 的单元测试。

测试覆盖:
- 关键词匹配（命中 / 未命中 / 中英文混合）
- LLM 分类兜底（识别 / 无法识别回退）
- github_search: quote 编码 / urllib 调用 / 重试 / 空结果
- knowledge_query: index.json 加载 / 目录扫描回退 / 关键词匹配 / 空库
- general_chat: quick_chat 调用
- route: 空输入 / 关键词分派 / LLM 分派 / 无 session 降级
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.patterns.router import (
    GENERAL_CHAT,
    GITHUB_SEARCH,
    KNOWLEDGE_QUERY,
    _classify_with_llm,
    _github_search,
    _knowledge_query,
    _load_knowledge_index,
    _match_keywords,
    route,
)

# ---------------------------------------------------------------------------
# 第一层：关键词匹配
# ---------------------------------------------------------------------------


class TestMatchKeywords:
    """关键词快速匹配测试。"""

    @pytest.mark.parametrize(
        "query, expected",
        [
            ("帮我搜索 github 上的项目", GITHUB_SEARCH),
            ("find a repo for web framework", GITHUB_SEARCH),
            ("有什么热门开源项目", GITHUB_SEARCH),
            ("github trending today", GITHUB_SEARCH),
            ("知识库里有没有 llm 文章", KNOWLEDGE_QUERY),
            ("search knowledge base for rag", KNOWLEDGE_QUERY),
            ("查一下之前的笔记", KNOWLEDGE_QUERY),
            ("检索 article about agent", KNOWLEDGE_QUERY),
        ],
    )
    def test_keyword_hit(self, query: str, expected: str) -> None:
        assert _match_keywords(query) == expected

    @pytest.mark.parametrize(
        "query",
        [
            "explain transformer architecture",
            "你好",
            "how does attention work",
        ],
    )
    def test_keyword_miss(self, query: str) -> None:
        assert _match_keywords(query) is None

    @pytest.mark.parametrize(
        "query",
        [
            "什么是 RAG",
            "LangGraph 和 CrewAI 有什么区别",
            "注意力机制的原理是什么",
        ],
    )
    def test_chat_pattern_hit(self, query: str) -> None:
        """对比/解释类问题应被判定为 general_chat。"""
        assert _match_keywords(query) == GENERAL_CHAT

    def test_case_insensitive(self) -> None:
        assert _match_keywords("GITHUB SEARCH") == GITHUB_SEARCH
        assert _match_keywords("Knowledge Query") == KNOWLEDGE_QUERY

    def test_empty_query(self) -> None:
        assert _match_keywords("") is None


# ---------------------------------------------------------------------------
# 第二层：LLM 分类兜底
# ---------------------------------------------------------------------------


class TestClassifyWithLlm:
    """LLM 分类兜底测试。"""

    @pytest.mark.parametrize(
        "llm_output, expected",
        [
            ("github_search", GITHUB_SEARCH),
            ("knowledge_query", KNOWLEDGE_QUERY),
            ("general_chat", GENERAL_CHAT),
            ("  GITHUB_SEARCH  ", GITHUB_SEARCH),
            ("我认为是 general_chat 意图", GENERAL_CHAT),
        ],
    )
    def test_classify_identified(self, llm_output: str, expected: str) -> None:
        mock_session = MagicMock()
        with patch("src.patterns.router.quick_chat", return_value=llm_output):
            result = _classify_with_llm("test query", mock_session)
        assert result == expected

    def test_classify_unrecognized_fallback(self) -> None:
        mock_session = MagicMock()
        with patch("src.patterns.router.quick_chat", return_value="unknown_intent"):
            result = _classify_with_llm("test query", mock_session)
        assert result == GENERAL_CHAT


# ---------------------------------------------------------------------------
# 处理器: github_search
# ---------------------------------------------------------------------------


class TestGithubSearch:
    """GitHub 搜索处理器测试。"""

    @patch("src.patterns.router.urllib.request.urlopen")
    def test_search_success(self, mock_urlopen: patch) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "items": [
                {
                    "full_name": "python/cpython",
                    "stargazers_count": 60000,
                    "description": "The Python programming language",
                    "html_url": "https://github.com/python/cpython",
                },
            ]
        }).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _github_search("python")
        assert "python/cpython" in result
        assert "60000" in result
        assert "https://github.com/python/cpython" in result

    @patch("src.patterns.router.urllib.request.urlopen")
    def test_search_empty_results(self, mock_urlopen: patch) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"items": []}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _github_search("nonexistent_xyz_123")
        assert "未找到" in result

    @patch("src.patterns.router.urllib.request.urlopen")
    def test_search_url_encoding(self, mock_urlopen: patch) -> None:
        """验证 query 参数经 urllib.parse.quote 编码（中文/空格）。"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"items": []}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _github_search("深度学习 框架")

        called_url = mock_urlopen.call_args.args[0].full_url
        # 中文和空格须被编码，不能原样出现
        assert "深度学习" not in called_url
        assert "%20" in called_url or "%E6" in called_url

    @patch("src.patterns.router.urllib.request.urlopen")
    def test_search_retry_on_url_error(self, mock_urlopen: patch) -> None:
        """URLError 触发重试。"""
        import urllib.error

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"items": []}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [
            urllib.error.URLError("connection refused"),
            mock_resp,
        ]

        result = _github_search("python")
        assert "未找到" in result
        assert mock_urlopen.call_count == 2


# ---------------------------------------------------------------------------
# 处理器: knowledge_query
# ---------------------------------------------------------------------------


class TestKnowledgeQuery:
    """知识库检索处理器测试。"""

    def test_query_with_results(self, tmp_path: Path) -> None:
        entries = [
            {
                "article_id": "kb-001",
                "title": "LLM Agent 框架综述",
                "summary": "本文介绍主流 Agent 框架",
                "tags": ["llm", "agent"],
                "score": 8,
                "source_url": "https://example.com/1",
            },
            {
                "article_id": "kb-002",
                "title": "RAG 检索增强生成",
                "summary": "RAG 技术详解",
                "tags": ["rag", "retrieval"],
                "score": 7,
                "source_url": "https://example.com/2",
            },
        ]
        with patch("src.patterns.router._load_knowledge_index", return_value=entries):
            result = _knowledge_query("llm agent")
        assert "kb-001" in result
        assert "LLM Agent" in result
        assert "8" in result

    def test_query_no_match(self) -> None:
        entries = [{"article_id": "kb-001", "title": "Something", "summary": "", "tags": []}]
        with patch("src.patterns.router._load_knowledge_index", return_value=entries):
            result = _knowledge_query("quantum_computing_xyz")
        assert "未找到" in result

    def test_query_empty_kb(self) -> None:
        with patch("src.patterns.router._load_knowledge_index", return_value=[]):
            result = _knowledge_query("anything")
        assert "为空" in result

    def test_load_index_from_file(self, tmp_path: Path) -> None:
        index_data = [{"article_id": "kb-001", "title": "test"}]
        index_file = tmp_path / "index.json"
        index_file.write_text(json.dumps(index_data), encoding="utf-8")

        with patch("src.patterns.router._INDEX_FILE", index_file):
            entries = _load_knowledge_index()
        assert len(entries) == 1
        assert entries[0]["article_id"] == "kb-001"

    def test_load_index_scan_directory(self, tmp_path: Path) -> None:
        """index.json 不存在时，扫描目录下 *.json 重建。"""
        (tmp_path / "kb-001.json").write_text(
            json.dumps({"article_id": "kb-001", "title": "a"}), encoding="utf-8"
        )
        (tmp_path / "kb-002.json").write_text(
            json.dumps({"article_id": "kb-002", "title": "b"}), encoding="utf-8"
        )

        with patch("src.patterns.router._INDEX_FILE", tmp_path / "nonexistent.json"), \
             patch("src.patterns.router._KNOWLEDGE_DIR", tmp_path):
            entries = _load_knowledge_index()
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# 处理器: general_chat
# ---------------------------------------------------------------------------


class TestGeneralChat:
    """通用对话处理器测试。"""

    @patch("src.patterns.router.quick_chat")
    def test_chat_success(self, mock_quick_chat: patch) -> None:
        mock_quick_chat.return_value = "RAG 是检索增强生成技术。"
        mock_session = MagicMock()
        from src.patterns.router import _general_chat

        result = _general_chat("什么是 RAG", mock_session)
        assert "RAG" in result
        mock_quick_chat.assert_called_once()

    @patch("src.patterns.router.quick_chat")
    def test_chat_retry_on_llm_error(self, mock_quick_chat: patch) -> None:
        """LlmCallError 触发重试后成功。"""
        from src.llm.client import LlmCallError, LlmErrorType

        mock_quick_chat.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            "成功回复",
        ]
        mock_session = MagicMock()
        from src.patterns.router import _general_chat

        result = _general_chat("test", mock_session)
        assert result == "成功回复"
        assert mock_quick_chat.call_count == 2


# ---------------------------------------------------------------------------
# 统一入口: route
# ---------------------------------------------------------------------------


class TestRoute:
    """route 统一入口测试。"""

    def test_empty_input(self) -> None:
        assert "有效" in route("")

    def test_whitespace_input(self) -> None:
        assert "有效" in route("   ")

    @patch("src.patterns.router._github_search")
    def test_route_github_keyword(self, mock_search: patch) -> None:
        mock_search.return_value = "GitHub 结果"
        result = route("搜索 github python 项目")
        assert result == "GitHub 结果"
        mock_search.assert_called_once()

    @patch("src.patterns.router._knowledge_query")
    def test_route_knowledge_keyword(self, mock_query: patch) -> None:
        mock_query.return_value = "知识库结果"
        result = route("知识库查一下 llm")
        assert result == "知识库结果"
        mock_query.assert_called_once()

    @patch("src.patterns.router._classify_with_llm")
    @patch("src.patterns.router._general_chat")
    def test_route_llm_classify_then_chat(
        self, mock_chat: patch, mock_classify: patch
    ) -> None:
        mock_classify.return_value = GENERAL_CHAT
        mock_chat.return_value = "LLM 回复"
        mock_session = MagicMock()

        result = route("explain transformer architecture", session=mock_session)
        assert result == "LLM 回复"
        mock_classify.assert_called_once()
        mock_chat.assert_called_once()

    @patch("src.patterns.router._general_chat")
    def test_route_no_session_fallback_general(self, mock_chat: patch) -> None:
        """关键词未命中且无 session -> general_chat 降级提示。"""
        result = route("explain transformer architecture")
        assert "数据库会话" in result or "LLM" in result
        mock_chat.assert_not_called()

    @patch("src.patterns.router._classify_with_llm")
    @patch("src.patterns.router._github_search")
    def test_route_llm_classify_to_github(
        self, mock_search: patch, mock_classify: patch
    ) -> None:
        """LLM 分类为 github_search 后分派到搜索。"""
        mock_classify.return_value = GITHUB_SEARCH
        mock_search.return_value = "搜索结果"
        mock_session = MagicMock()

        result = route("帮我找个代码库", session=mock_session)
        assert result == "搜索结果"
        mock_search.assert_called_once()
