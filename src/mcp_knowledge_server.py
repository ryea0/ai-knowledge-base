"""MCP Knowledge Server — 让 AI 工具搜索本地知识库。

实现 JSON-RPC 2.0 over stdio 协议，支持 MCP 核心方法：
- initialize: 握手与能力协商
- tools/list: 返回可用工具列表
- tools/call: 调用具体工具

提供 3 个工具：
- search_articles: 按关键词搜索文章标题和摘要
- get_article: 按 article_id 获取文章完整内容
- knowledge_stats: 返回统计信息（文章总数、来源分布、热门标签）

仅依赖 Python 标准库，无第三方依赖。
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 知识条目目录，相对于项目根目录（src/ 的上一级）
_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"

# MCP 协议版本
_MCP_VERSION = "2024-11-05"

# Server 信息
_SERVER_INFO: dict[str, str] = {
    "name": "mcp-knowledge-server",
    "version": "0.1.0",
}

# 工具定义
_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_articles",
        "description": "按关键词搜索知识库文章，匹配标题和摘要。返回匹配的文章列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（不区分大小写）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量上限，默认 5",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "按 article_id 获取文章的完整内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "文章 ID，格式 kb-YYYYMMDD-NNNN",
                },
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "返回知识库统计信息：文章总数、来源平台分布、热门标签 Top 10。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _load_articles(knowledge_dir: Path | None = None) -> list[dict[str, Any]]:
    """加载 knowledge/articles/ 目录下所有 JSON 文章。

    Args:
        knowledge_dir: 知识条目目录，默认使用模块级常量。

    Returns:
        文章字典列表，解析失败的文件跳过并记日志。
    """
    base_dir = knowledge_dir if knowledge_dir is not None else _KNOWLEDGE_DIR
    if not base_dir.is_dir():
        logger.warning("知识条目目录不存在: %s", base_dir)
        return []

    articles: list[dict[str, Any]] = []
    for json_file in sorted(base_dir.glob("*.json")):
        try:
            text = json_file.read_text(encoding="utf-8")
            data = json.loads(text)
        except OSError as exc:
            logger.error("读取文件失败 %s: %s", json_file, exc)
            continue
        except json.JSONDecodeError as exc:
            logger.error("JSON 解析失败 %s: %s", json_file, exc)
            continue

        if isinstance(data, dict):
            articles.append(data)

    return articles


def search_articles(
    keyword: str, limit: int = 5, articles: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """按关键词搜索文章，匹配标题和摘要（不区分大小写）。

    Args:
        keyword: 搜索关键词。
        limit: 返回结果数量上限。
        articles: 文章列表，默认从磁盘加载。

    Returns:
        匹配的文章列表，每项含 article_id、title、summary、source_platform、
        source_score、tags、category。按 source_score 降序排列。
    """
    if not keyword.strip():
        return []

    source = articles if articles is not None else _load_articles()
    kw_lower = keyword.lower()

    matched: list[dict[str, Any]] = []
    for entry in source:
        title = str(entry.get("title", ""))
        summary = str(entry.get("summary", ""))
        if kw_lower in title.lower() or kw_lower in summary.lower():
            matched.append(
                {
                    "article_id": entry.get("article_id", ""),
                    "title": title,
                    "summary": summary,
                    "source_platform": entry.get("source_platform", ""),
                    "source_score": entry.get("source_score", 0),
                    "tags": entry.get("tags", []),
                    "category": entry.get("category", ""),
                }
            )

    matched.sort(key=lambda x: x.get("source_score", 0), reverse=True)
    return matched[:limit]


def get_article(
    article_id: str, articles: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """按 article_id 获取文章完整内容。

    Args:
        article_id: 文章 ID。
        articles: 文章列表，默认从磁盘加载。

    Returns:
        完整文章字典；未找到时返回 None。
    """
    source = articles if articles is not None else _load_articles()
    for entry in source:
        if entry.get("article_id") == article_id:
            return entry
    return None


def knowledge_stats(articles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """返回知识库统计信息。

    Args:
        articles: 文章列表，默认从磁盘加载。

    Returns:
        包含 total、source_distribution、top_tags 的字典。
    """
    source = articles if articles is not None else _load_articles()
    total = len(source)

    platform_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()

    for entry in source:
        platform = str(entry.get("source_platform", "unknown"))
        platform_counter[platform] += 1
        tags = entry.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str):
                    tag_counter[tag] += 1

    return {
        "total": total,
        "source_distribution": dict(platform_counter),
        "top_tags": tag_counter.most_common(10),
    }


def _make_error(
    code: int, message: str, data: Any = None, req_id: Any = None
) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 错误响应。

    Args:
        code: 错误码（如 -32601 表示方法不存在）。
        message: 错误消息。
        data: 附加错误数据。
        req_id: 请求 ID，透传回客户端。

    Returns:
        JSON-RPC 错误响应字典。
    """
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "error": err, "id": req_id}


def _make_result(result: Any, req_id: Any) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 成功响应。

    Args:
        result: 结果数据。
        req_id: 请求 ID。

    Returns:
        JSON-RPC 成功响应字典。
    """
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def _handle_initialize(req_id: Any) -> dict[str, Any]:
    """处理 initialize 请求，返回能力声明。

    Args:
        req_id: 请求 ID。

    Returns:
        JSON-RPC 响应，result 含 protocolVersion、capabilities、serverInfo。
    """
    return _make_result(
        {
            "protocolVersion": _MCP_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": _SERVER_INFO,
        },
        req_id,
    )


def _handle_tools_list(req_id: Any) -> dict[str, Any]:
    """处理 tools/list 请求，返回工具定义列表。

    Args:
        req_id: 请求 ID。

    Returns:
        JSON-RPC 响应，result 含 tools 数组。
    """
    return _make_result({"tools": _TOOLS}, req_id)


def _handle_tools_call(
    params: dict[str, Any], req_id: Any
) -> dict[str, Any]:
    """处理 tools/call 请求，分发到具体工具执行。

    Args:
        params: 调用参数，含 name 和 arguments。
        req_id: 请求 ID。

    Returns:
        JSON-RPC 响应，result 含 content 数组（MCP 工具返回格式）。
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    if tool_name == "search_articles":
        keyword = str(arguments.get("keyword", ""))
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool):
            limit = 5
        limit = max(1, min(50, limit))
        call_result: Any = search_articles(keyword, limit)
        text = json.dumps(call_result, ensure_ascii=False, indent=2)

    elif tool_name == "get_article":
        article_id = str(arguments.get("article_id", ""))
        call_result = get_article(article_id)
        if call_result is None:
            text = json.dumps(
                {"error": f"未找到 article_id: {article_id}"}, ensure_ascii=False
            )
        else:
            text = json.dumps(call_result, ensure_ascii=False, indent=2)

    elif tool_name == "knowledge_stats":
        call_result = knowledge_stats()
        text = json.dumps(call_result, ensure_ascii=False, indent=2)

    else:
        return _make_error(
            -32601, f"未知工具: {tool_name}", req_id=req_id
        )

    return _make_result(
        {"content": [{"type": "text", "text": text}]}, req_id
    )


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """处理单个 JSON-RPC 2.0 请求。

    Args:
        request: 已解析的 JSON-RPC 请求字典。

    Returns:
        JSON-RPC 响应字典；通知（无 id 字段）返回 None。
    """
    req_id = request.get("id")
    method = request.get("method", "")

    if method == "initialize":
        return _handle_initialize(req_id)

    if method == "tools/list":
        return _handle_tools_list(req_id)

    if method == "tools/call":
        params = request.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return _handle_tools_call(params, req_id)

    if method == "notifications/initialized":
        return None

    return _make_error(-32601, f"未知方法: {method}", req_id=req_id)


def main() -> None:
    """MCP Server 主循环，从 stdin 读取 JSON-RPC 请求，写响应到 stdout。

    每行一个 JSON-RPC 请求（以换行符分隔）。
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = _make_error(-32700, f"JSON 解析失败: {exc.msg}", req_id=None)
            sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        if not isinstance(request, dict):
            err_resp = _make_error(-32600, "请求不是 JSON 对象", req_id=None)
            sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
