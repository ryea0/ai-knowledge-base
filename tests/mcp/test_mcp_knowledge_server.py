"""mcp_knowledge_server 的单元测试。

测试覆盖：
- search_articles: 关键词搜索、大小写不敏感、limit 截断、空关键词
- get_article: 按 ID 查找、不存在返回 None
- knowledge_stats: 总数、来源分布、热门标签
- handle_request: MCP 协议方法分发（initialize / tools/list / tools/call / 未知方法 / 通知）
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_knowledge_server import (
    _handle_initialize,
    _handle_tools_call,
    _handle_tools_list,
    get_article,
    handle_request,
    knowledge_stats,
    search_articles,
)

# 测试数据目录
_TEST_ARTICLES_DIR = Path("/tmp/opencode/test_articles")

# 预加载的测试文章列表（避免依赖磁盘读取）
_TEST_ARTICLES = [
    {
        "article_id": "kb-20260720-0001",
        "title": "LangChain 发布 v0.3 多Agent编排框架",
        "source_url": "https://github.com/langchain-ai/langchain",
        "source_platform": "github_trending",
        "source_score": 942,
        "summary": "LangChain v0.3 引入 LangGraph 多Agent编排能力，支持状态机式工作流定义。"
        "新版本优化了工具调用接口，增强了RAG检索链路的灵活性。",
        "content_path": "knowledge/raw/kb-20260720-0001.md",
        "tags": ["langchain", "agent", "rag", "workflow"],
        "category": "tool",
        "status": "published",
        "language": "zh",
        "collected_at": "2026-07-20T08:00:00Z",
        "analyzed_at": "2026-07-20T08:05:00Z",
        "published_at": "2026-07-20T10:00:00Z",
        "published_channels": ["telegram"],
    },
    {
        "article_id": "kb-20260721-0002",
        "title": "OpenAI 发布 GPT-5 多模态推理模型",
        "source_url": "https://news.ycombinator.com/item?id=12345678",
        "source_platform": "hackernews",
        "source_score": 2941,
        "summary": "GPT-5 支持原生多模态输入，推理能力显著提升。"
        "新模型在数学推理和代码生成基准测试中达到SOTA，上下文窗口扩展至256K。",
        "content_path": "knowledge/raw/kb-20260721-0002.md",
        "tags": ["openai", "gpt-5", "multimodal", "reasoning"],
        "category": "model_release",
        "status": "reviewed",
        "language": "en",
        "collected_at": "2026-07-21T09:00:00Z",
        "analyzed_at": "2026-07-21T09:10:00Z",
        "published_at": None,
        "published_channels": None,
    },
    {
        "article_id": "kb-20260722-0003",
        "title": "vLLM 推理优化：PagedAttention 机制详解",
        "source_url": "https://github.com/vllm-project/vllm",
        "source_platform": "github_trending",
        "source_score": 678,
        "summary": "vLLM 通过 PagedAttention 机制优化KV缓存管理，将推理吞吐量提升2-4倍。"
        "该方案借鉴操作系统的虚拟内存分页思想管理显存。",
        "content_path": "knowledge/raw/kb-20260722-0003.md",
        "tags": ["vllm", "inference", "optimization", "attention"],
        "category": "tutorial",
        "status": "pending",
        "language": "zh",
        "collected_at": "2026-07-22T08:00:00Z",
        "analyzed_at": None,
        "published_at": None,
        "published_channels": None,
    },
]


# ============================================================
# search_articles 测试
# ============================================================


class TestSearchArticles:
    """search_articles 工具测试。"""

    def test_search_by_title_keyword(self) -> None:
        """关键词匹配标题。"""
        results = search_articles("GPT-5", articles=_TEST_ARTICLES)
        assert len(results) == 1
        assert results[0]["article_id"] == "kb-20260721-0002"

    def test_search_by_summary_keyword(self) -> None:
        """关键词匹配摘要。"""
        results = search_articles("PagedAttention", articles=_TEST_ARTICLES)
        assert len(results) == 1
        assert results[0]["article_id"] == "kb-20260722-0003"

    def test_search_case_insensitive(self) -> None:
        """搜索不区分大小写。"""
        results_lower = search_articles("agent", articles=_TEST_ARTICLES)
        results_upper = search_articles("AGENT", articles=_TEST_ARTICLES)
        assert len(results_lower) == len(results_upper)
        assert results_lower[0]["article_id"] == results_upper[0]["article_id"]

    def test_search_sorted_by_score(self) -> None:
        """结果按 source_score 降序排列。"""
        results = search_articles("推理", articles=_TEST_ARTICLES, limit=10)
        assert len(results) == 2
        assert results[0]["source_score"] >= results[1]["source_score"]

    def test_search_limit_truncation(self) -> None:
        """limit 截断结果数量。"""
        results = search_articles("的", articles=_TEST_ARTICLES, limit=1)
        assert len(results) == 1

    def test_search_no_match(self) -> None:
        """无匹配返回空列表。"""
        results = search_articles("量子计算", articles=_TEST_ARTICLES)
        assert results == []

    def test_search_empty_keyword(self) -> None:
        """空关键词返回空列表。"""
        results = search_articles("", articles=_TEST_ARTICLES)
        assert results == []

    def test_search_result_fields(self) -> None:
        """结果包含正确的字段子集。"""
        results = search_articles("LangChain", articles=_TEST_ARTICLES)
        assert len(results) == 1
        item = results[0]
        expected_keys = {
            "article_id",
            "title",
            "summary",
            "source_platform",
            "source_score",
            "tags",
            "category",
        }
        assert set(item.keys()) == expected_keys


# ============================================================
# get_article 测试
# ============================================================


class TestGetArticle:
    """get_article 工具测试。"""

    def test_get_existing_article(self) -> None:
        """获取存在的文章，返回完整内容。"""
        result = get_article("kb-20260720-0001", articles=_TEST_ARTICLES)
        assert result is not None
        assert result["article_id"] == "kb-20260720-0001"
        assert result["title"] == "LangChain 发布 v0.3 多Agent编排框架"
        assert "content_path" in result
        assert "status" in result

    def test_get_nonexistent_article(self) -> None:
        """获取不存在的文章返回 None。"""
        result = get_article("kb-99999999-9999", articles=_TEST_ARTICLES)
        assert result is None

    def test_get_article_returns_full_dict(self) -> None:
        """返回的文章包含所有字段（非裁剪子集）。"""
        result = get_article("kb-20260721-0002", articles=_TEST_ARTICLES)
        assert result is not None
        assert "published_channels" in result
        assert "collected_at" in result


# ============================================================
# knowledge_stats 测试
# ============================================================


class TestKnowledgeStats:
    """knowledge_stats 工具测试。"""

    def test_stats_total(self) -> None:
        """总数正确。"""
        stats = knowledge_stats(articles=_TEST_ARTICLES)
        assert stats["total"] == 3

    def test_stats_source_distribution(self) -> None:
        """来源平台分布正确。"""
        stats = knowledge_stats(articles=_TEST_ARTICLES)
        dist = stats["source_distribution"]
        assert dist["github_trending"] == 2
        assert dist["hackernews"] == 1

    def test_stats_top_tags(self) -> None:
        """热门标签列表正确。"""
        stats = knowledge_stats(articles=_TEST_ARTICLES)
        top_tags = stats["top_tags"]
        assert len(top_tags) <= 10
        # 每个标签出现次数为 1（测试数据中无重复标签）
        for tag, count in top_tags:
            assert isinstance(tag, str)
            assert count == 1

    def test_stats_empty_articles(self) -> None:
        """空文章列表返回零值统计。"""
        stats = knowledge_stats(articles=[])
        assert stats["total"] == 0
        assert stats["source_distribution"] == {}
        assert stats["top_tags"] == []


# ============================================================
# MCP 协议 handle_request 测试
# ============================================================


class TestHandleRequest:
    """JSON-RPC 请求处理测试。"""

    def test_initialize(self) -> None:
        """initialize 返回协议版本和能力声明。"""
        response = handle_request(
            {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        )
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        result = response["result"]
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert result["capabilities"]["tools"] == {}
        assert result["serverInfo"]["name"] == "mcp-knowledge-server"

    def test_tools_list(self) -> None:
        """tools/list 返回 3 个工具定义。"""
        response = handle_request(
            {"jsonrpc": "2.0", "method": "tools/list", "id": 2}
        )
        assert response is not None
        tools = response["result"]["tools"]
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"search_articles", "get_article", "knowledge_stats"}

    def test_tools_call_search(self) -> None:
        """tools/call 调用 search_articles 返回结果。"""
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "search_articles",
                    "arguments": {"keyword": "Agent", "limit": 2},
                },
                "id": 3,
            }
        )
        assert response is not None
        assert response["id"] == 3
        content = response["result"]["content"]
        assert content[0]["type"] == "text"
        data = json.loads(content[0]["text"])
        assert isinstance(data, list)
        assert len(data) <= 2

    def test_tools_call_get_article_not_found(self) -> None:
        """tools/call 获取不存在的文章返回错误信息。"""
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_article",
                    "arguments": {"article_id": "kb-00000000-0000"},
                },
                "id": 4,
            }
        )
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "error" in data

    def test_tools_call_unknown_tool(self) -> None:
        """调用未知工具返回 -32601 错误。"""
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
                "id": 5,
            }
        )
        assert response is not None
        assert response["error"]["code"] == -32601

    def test_unknown_method(self) -> None:
        """未知方法返回 -32601 错误。"""
        response = handle_request(
            {"jsonrpc": "2.0", "method": "foo/bar", "id": 6}
        )
        assert response is not None
        assert response["error"]["code"] == -32601

    def test_notification_returns_none(self) -> None:
        """通知（notifications/initialized）返回 None。"""
        response = handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert response is None


# ============================================================
# 辅助函数测试
# ============================================================


class TestHandleInitialize:
    """_handle_initialize 直接测试。"""

    def test_initialize_response_structure(self) -> None:
        """initialize 响应结构完整。"""
        response = _handle_initialize(99)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 99
        assert response["result"]["protocolVersion"] == "2024-11-05"


class TestHandleToolsList:
    """_handle_tools_list 直接测试。"""

    def test_tools_have_input_schema(self) -> None:
        """每个工具都有 inputSchema。"""
        response = _handle_tools_list(None)
        for tool in response["result"]["tools"]:
            assert "inputSchema" in tool
            assert "name" in tool
            assert "description" in tool


class TestHandleToolsCall:
    """_handle_tools_call 直接测试。"""

    def test_call_knowledge_stats(self) -> None:
        """调用 knowledge_stats 返回统计。"""
        response = _handle_tools_call(
            {"name": "knowledge_stats", "arguments": {}}, req_id=7
        )
        assert response["id"] == 7
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "total" in data
        assert "source_distribution" in data
        assert "top_tags" in data

    def test_call_search_default_limit(self) -> None:
        """search_articles 不传 limit 时使用默认值 5。"""
        response = _handle_tools_call(
            {"name": "search_articles", "arguments": {"keyword": "模型"}}, req_id=8
        )
        assert response["id"] == 8
        data = json.loads(response["result"]["content"][0]["text"])
        assert isinstance(data, list)


# ============================================================
# 磁盘读取测试（使用临时测试数据）
# ============================================================


class TestDiskLoad:
    """测试从磁盘加载文章文件。"""

    def test_load_from_disk(self) -> None:
        """从临时目录加载 3 篇文章。"""
        from mcp_knowledge_server import _load_articles

        articles = _load_articles(_TEST_ARTICLES_DIR)
        assert len(articles) == 3
        ids = {a["article_id"] for a in articles}
        assert ids == {"kb-20260720-0001", "kb-20260721-0002", "kb-20260722-0003"}

    def test_load_nonexistent_dir(self) -> None:
        """不存在的目录返回空列表。"""
        from mcp_knowledge_server import _load_articles

        articles = _load_articles(Path("/tmp/opencode/nonexistent_dir"))
        assert articles == []


# ============================================================
# 边界情况与错误处理测试
# ============================================================


class TestEdgeCases:
    """边界情况与错误分支测试。"""

    def test_make_error_with_data(self) -> None:
        """_make_error 带 data 字段时正确返回。"""
        from mcp_knowledge_server import _make_error

        resp = _make_error(-32600, "bad request", data={"detail": "extra"}, req_id=10)
        assert resp["error"]["code"] == -32600
        assert resp["error"]["data"] == {"detail": "extra"}
        assert resp["id"] == 10

    def test_make_error_without_data(self) -> None:
        """_make_error 不带 data 时不含 data 键。"""
        from mcp_knowledge_server import _make_error

        resp = _make_error(-1, "simple", req_id=None)
        assert "data" not in resp["error"]

    def test_tools_call_non_dict_arguments(self) -> None:
        """arguments 非字典时使用空字典。"""
        response = _handle_tools_call(
            {"name": "knowledge_stats", "arguments": "not_a_dict"}, req_id=11
        )
        assert response["id"] == 11
        data = json.loads(response["result"]["content"][0]["text"])
        assert "total" in data

    def test_tools_call_search_invalid_limit_type(self) -> None:
        """limit 为非整数时使用默认值 5。"""
        response = _handle_tools_call(
            {
                "name": "search_articles",
                "arguments": {"keyword": "test", "limit": "invalid"},
            },
            req_id=12,
        )
        data = json.loads(response["result"]["content"][0]["text"])
        assert isinstance(data, list)

    def test_tools_call_search_bool_limit(self) -> None:
        """limit 为 bool 时使用默认值（bool 是 int 子类需排除）。"""
        response = _handle_tools_call(
            {
                "name": "search_articles",
                "arguments": {"keyword": "test", "limit": True},
            },
            req_id=13,
        )
        data = json.loads(response["result"]["content"][0]["text"])
        assert isinstance(data, list)

    def test_handle_request_non_dict_params(self) -> None:
        """tools/call 的 params 非字典时不崩溃。"""
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": "invalid_string",
                "id": 14,
            }
        )
        assert response is not None
        assert response["id"] == 14

    def test_search_whitespace_keyword(self) -> None:
        """纯空白关键词返回空列表。"""
        results = search_articles("   ", articles=_TEST_ARTICLES)
        assert results == []

    def test_stats_with_non_list_tags(self) -> None:
        """tags 非列表时跳过不崩溃。"""
        bad_articles = [
            {
                "article_id": "kb-test-0001",
                "title": "test",
                "source_platform": "test",
                "tags": "not_a_list",
            }
        ]
        stats = knowledge_stats(articles=bad_articles)
        assert stats["total"] == 1
        assert stats["top_tags"] == []

    def test_stats_with_non_string_tag(self) -> None:
        """tags 列表中含非字符串元素时跳过。"""
        bad_articles = [
            {
                "article_id": "kb-test-0001",
                "title": "test",
                "source_platform": "test",
                "tags": ["valid", 123, None],
            }
        ]
        stats = knowledge_stats(articles=bad_articles)
        tag_names = [t for t, _ in stats["top_tags"]]
        assert "valid" in tag_names
        assert 123 not in tag_names

    def test_search_results_have_score_sort(self) -> None:
        """多结果按 source_score 降序。"""
        results = search_articles(
            "的", articles=_TEST_ARTICLES, limit=10
        )
        scores = [r["source_score"] for r in results]
        assert scores == sorted(scores, reverse=True)


# ============================================================
# main() stdin 循环集成测试
# ============================================================


class TestMainLoop:
    """main() 主循环集成测试（通过 subprocess）。"""

    def test_main_initialize(self) -> None:
        """main 循环正确响应 initialize 请求。"""
        import subprocess
        import sys

        req = json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": 1})
        proc = subprocess.run(
            [sys.executable, "-c", _RUN_MAIN_SCRIPT],
            input=req + "\n",
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        resp = json.loads(proc.stdout.strip())
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "protocolVersion" in resp["result"]

    def test_main_invalid_json(self) -> None:
        """main 循环遇到非法 JSON 返回 -32700 错误。"""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-c", _RUN_MAIN_SCRIPT],
            input="not_json_at_all\n",
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        resp = json.loads(proc.stdout.strip())
        assert resp["error"]["code"] == -32700

    def test_main_non_object_json(self) -> None:
        """main 循环遇到合法 JSON 但非对象时返回 -32600 错误。"""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-c", _RUN_MAIN_SCRIPT],
            input="[1, 2, 3]\n",
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        resp = json.loads(proc.stdout.strip())
        assert resp["error"]["code"] == -32600

    def test_main_notification_no_response(self) -> None:
        """main 循环收到通知时不产生输出。"""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-c", _RUN_MAIN_SCRIPT],
            input=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            ) + "\n",
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        assert proc.stdout.strip() == ""


# 用于 subprocess 执行 main() 的脚本
_RUN_MAIN_SCRIPT = (
    "import sys; sys.path.insert(0, 'src'); "
    "from mcp_knowledge_server import main; main()"
)

