"""Router 路由模式：两层意图分类 + 三种意图处理器。

意图分类策略：
    1. 第一层 -- 关键词快速匹配（零成本，不调 LLM）
    2. 第二层 -- LLM 分类兜底（处理模糊意图）

三种意图：
    - ``github_search``   -- 调用 GitHub Search API（urllib.request），query 经 quote 编码
    - ``knowledge_query`` -- 从本地 knowledge/articles/index.json 检索
    - ``general_chat``    -- 调用 LLM 直接回答

统一入口 :func:`route`，根据分类结果分派到对应处理器并返回字符串结果。

GitHub 搜索与 LLM 调用均通过 :func:`src.llm.retry_decorator.with_retry` 包装，
对网络异常（``urllib.error.URLError`` / ``httpx.*`` / ``LlmCallError`` 可重试子类）
自动退避重试。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.llm.client import LlmCallError, quick_chat
from src.llm.retry_decorator import with_retry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

Intent = str
GITHUB_SEARCH: Intent = "github_search"
KNOWLEDGE_QUERY: Intent = "knowledge_query"
GENERAL_CHAT: Intent = "general_chat"

_GITHUB_API_URL = "https://api.github.com/search/repositories"
_GITHUB_API_TOKEN = ""  # 未认证受 60 次/小时限流，生产环境应从环境变量注入
_KNOWLEDGE_DIR = Path("knowledge/articles")
_INDEX_FILE = _KNOWLEDGE_DIR / "index.json"

_INTENT_LIST: list[Intent] = [GITHUB_SEARCH, KNOWLEDGE_QUERY, GENERAL_CHAT]

# ---------------------------------------------------------------------------
# 第一层：关键词快速匹配
# ---------------------------------------------------------------------------

_KEYWORD_MAP: dict[str, list[str]] = {
    GITHUB_SEARCH: [
        "github", "repo", "repository", "开源", "项目",
        "trending", "star", "fork", "starred",
    ],
    KNOWLEDGE_QUERY: [
        "knowledge", "知识库", "文章", "article", "笔记", "note",
        "查一下", "检索", "search knowledge", "之前", "记录",
    ],
}

# 对比/解释类问题模式 -- 命中则直接判定为 general_chat，
# 跳过 LLM 分类，避免框架名被误判为 github_search
_CHAT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"有什么区别", r"区别是", r"对比", r"比较",
        r"哪个好", r"哪个更", r"还是",
        r"什么是", r"是什么", r"怎么回事", r"怎么理解",
        r"原理", r"如何实现", r"怎么实现",
        r"优缺点", r"优势", r"劣势",
    ]
]


def _match_keywords(query: str) -> Intent | None:
    """关键词快速匹配（零成本，不调 LLM）。

    匹配顺序：
        1. 先检查对比/解释类模式，命中则直接判定 ``general_chat``；
        2. 再检查关键词表，命中则返回对应意图。

    Args:
        query: 用户输入文本。

    Returns:
        命中的意图字符串，未命中返回 ``None``。
    """
    # 对比/解释类问题优先判定为 general_chat，
    # 防止 LLM 因框架名误判为 github_search
    if any(p.search(query) for p in _CHAT_PATTERNS):
        logger.debug("对比/解释模式命中: intent=general_chat, query=%s", query)
        return GENERAL_CHAT

    lowered = query.lower()
    for intent, keywords in _KEYWORD_MAP.items():
        if any(kw in lowered for kw in keywords):
            logger.debug("关键词匹配命中: intent=%s, query=%s", intent, query)
            return intent
    return None


# ---------------------------------------------------------------------------
# 第二层：LLM 分类兜底
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "你是一个意图分类器。只输出意图名称（github_search / knowledge_query / general_chat），"
    "禁止输出任何解释、推理、编号或标点。\n\n"
    "意图定义：\n"
    "- github_search: 用户明确要求搜索、查找 GitHub 上的开源项目/仓库/代码\n"
    "- knowledge_query: 查询本地知识库中已有的文章/笔记\n"
    "- general_chat: 普通对话、问答、闲聊、技术解释、框架对比、原理分析\n\n"
    "判定规则：\n"
    "- 提到框架/库名但意图是对比、解释、问答 -> general_chat（不是 github_search）\n"
    "- 仅当用户明确表达「搜索/查找/找」项目/仓库意图时 -> github_search\n"
    "- 对比类问题（A 和 B 有什么区别/哪个好）一定是 general_chat\n\n"
    "示例：\n"
    "输入: 帮我找个代码库 -> github_search\n"
    "输入: 之前记录的 RAG 文章 -> knowledge_query\n"
    "输入: 什么是注意力机制 -> general_chat\n"
    "输入: 搜索最近的 AI Agent 框架 -> github_search\n"
    "输入: LangGraph 和 CrewAI 有什么区别 -> general_chat\n"
    "输入: Pydantic 和 dataclass 哪个好用 -> general_chat\n"
    "输入: LangChain 怎么实现 RAG -> general_chat\n"
    "输入: 有没有 LangGraph 的 GitHub 仓库 -> github_search"
)


def _classify_with_llm(query: str, session: Session) -> Intent:
    """LLM 分类兜底（处理关键词未命中的模糊意图）。

    Args:
        query: 用户输入文本。
        session: SQLAlchemy Session，用于 LLM 调用。

    Returns:
        分类后的意图字符串；LLM 返回无法识别时回退为 ``general_chat``。
    """
    prompt = (
        "对以下输入输出意图名称"
        "（github_search / knowledge_query / general_chat）：\n\n" + query
    )
    raw = quick_chat(
        prompt, session,
        system_prompt=_CLASSIFY_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=50,
    )
    result = raw.strip().lower()
    for intent in _INTENT_LIST:
        if intent in result:
            logger.info("LLM 分类结果: intent=%s, query=%s", intent, query)
            return intent
    logger.warning("LLM 分类无法识别(%s)，回退为 general_chat", result)
    return GENERAL_CHAT


# ---------------------------------------------------------------------------
# 处理器
# ---------------------------------------------------------------------------


def _extract_search_terms(query: str) -> str:
    """从用户输入提取 GitHub 搜索关键词。

    GitHub Search 对中文整句匹配差，优先提取英文词和技术术语。
    无英文词时回退原 query（由 quote 编码后仍可尝试搜索）。

    Args:
        query: 用户原始输入。

    Returns:
        适合 GitHub Search 的关键词字符串。
    """
    english_words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]*", query)
    if english_words:
        terms = " ".join(english_words)
        logger.debug("提取搜索词: %s -> %s", query, terms)
        return terms
    return query


@with_retry(
    retry_on=(urllib.error.URLError, TimeoutError),
    max_attempts=3,
    base_delay=1.0,
)
def _github_search(query: str) -> str:
    """调用 GitHub Search API 搜索仓库。

    ``query`` 经 :func:`urllib.parse.quote` 编码，正确处理中文与空格。
    使用 :func:`urllib.request.urlopen` 发送请求。

    GitHub Search 对中文整句匹配较差，本函数先提取英文/技术关键词，
    若无英文词则回退原 query。

    Args:
        query: 搜索关键词。

    Returns:
        格式化的搜索结果摘要字符串。
    """
    search_q = _extract_search_terms(query)
    encoded = urllib.parse.quote(search_q, safe="")
    url = f"{_GITHUB_API_URL}?q={encoded}&sort=stars&order=desc&per_page=5"
    logger.info("GitHub 搜索: %s (原始query=%s)", url, query)

    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-knowledge-base/1.0",
    })
    if _GITHUB_API_TOKEN:
        req.add_header("Authorization", f"Bearer {_GITHUB_API_TOKEN}")

    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 -- 受控 URL
        data = json.loads(resp.read().decode("utf-8"))

    items = data.get("items", [])
    if not items:
        return f"未找到与「{query}」相关的 GitHub 仓库。"

    lines = [f"GitHub 搜索「{query}」Top {len(items)} 结果：\n"]
    for i, item in enumerate(items, 1):
        name = item.get("full_name", "?")
        stars = item.get("stargazers_count", 0)
        desc = (item.get("description") or "无描述")[:80]
        html_url = item.get("html_url", "")
        lines.append(f"{i}. {name} (★{stars})\n   {desc}\n   {html_url}")
    return "\n".join(lines)


def _knowledge_query(query: str) -> str:
    """从本地 knowledge/articles/index.json 检索知识条目。

    若 ``index.json`` 不存在，则扫描 ``knowledge/articles/`` 目录下所有
    ``*.json`` 文件，按标题/摘要/标签匹配关键词。

    Args:
        query: 检索关键词。

    Returns:
        匹配到的条目摘要字符串；无匹配返回提示信息。
    """
    entries = _load_knowledge_index()
    if not entries:
        return "知识库为空，暂无可检索内容。"

    keywords = [w.lower() for w in query.split() if w.strip()]
    if not keywords:
        keywords = [query.lower()]

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        title = str(entry.get("title", "")).lower()
        summary = str(entry.get("summary", "")).lower()
        tag_list = entry.get("tags", [])
        tags = " ".join(str(t).lower() for t in tag_list) if isinstance(tag_list, list) else ""
        haystack = f"{title} {summary} {tags}"

        score = sum(1.0 for kw in keywords if kw in haystack)
        if score > 0:
            scored.append((score, entry))

    if not scored:
        return f"知识库中未找到与「{query}」相关的条目。"

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:5]

    lines = [f"知识库检索「{query}」匹配 {len(scored)} 条，Top {len(top)}：\n"]
    for i, (_, entry) in enumerate(top, 1):
        aid = str(entry.get("article_id", "?"))
        title = str(entry.get("title", "无标题"))
        score = entry.get("score", 0)
        tag_list = entry.get("tags", [])
        tags = ", ".join(str(t) for t in tag_list) if isinstance(tag_list, list) else "无标签"
        source = str(entry.get("source_url", ""))
        lines.append(f"{i}. [{aid}] {title} (评分:{score})\n   标签: {tags}\n   {source}")
    return "\n".join(lines)


def _load_knowledge_index() -> list[dict[str, Any]]:
    """加载知识库索引。

    优先读取 ``index.json``；不存在时扫描目录重建内存索引。

    Returns:
        知识条目列表，每项为 dict。
    """
    if _INDEX_FILE.exists():
        try:
            with _INDEX_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [e for e in data if isinstance(e, dict)]
                if isinstance(data, dict) and isinstance(data.get("articles"), list):
                    return [e for e in data["articles"] if isinstance(e, dict)]
        except (json.JSONDecodeError, OSError):
            logger.exception("index.json 解析失败，回退为目录扫描")

    if not _KNOWLEDGE_DIR.exists():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(_KNOWLEDGE_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                entry = json.load(f)
                if isinstance(entry, dict):
                    entries.append(entry)
        except (json.JSONDecodeError, OSError):
            logger.warning("跳过无法解析的文件: %s", path)
    return entries


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def _general_chat(query: str, session: Session) -> str:
    """调用 LLM 直接回答通用对话。

    ``quick_chat`` 内部已调 ``chat_completion_with_retry`` 含重试，
    外层 ``with_retry`` 仅对偶发穿透的 ``LlmCallError`` 兜底，实际极少触发。

    Args:
        query: 用户提问文本。
        session: SQLAlchemy Session，用于 LLM 调用。

    Returns:
        LLM 生成的回复文本。
    """
    system_prompt = "你是一个友好的 AI 知识库助手，请简洁、准确地回答用户问题。"
    return quick_chat(query, session, system_prompt=system_prompt)


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def route(query: str, session: Session | None = None) -> str:
    """统一路由入口：分类意图 -> 分派处理器 -> 返回字符串结果。

    分类策略：
        1. 先尝试关键词快速匹配（零成本）；
        2. 未命中且 ``session`` 可用时，调用 LLM 分类兜底；
        3. 无 ``session`` 时回退为 ``general_chat``。

    Args:
        query: 用户输入文本。
        session: 可选的 SQLAlchemy Session，提供时启用 LLM 分类与对话。

    Returns:
        处理器返回的字符串结果。
    """
    if not query or not query.strip():
        return "请输入有效内容。"

    intent = _match_keywords(query)
    if intent is None:
        if session is not None:
            intent = _classify_with_llm(query, session)
        else:
            intent = GENERAL_CHAT
            logger.info("无 session，关键词未命中，回退为 general_chat")

    logger.info("路由分派: intent=%s, query=%s", intent, query)

    if intent == GITHUB_SEARCH:
        return _github_search(query)
    if intent == KNOWLEDGE_QUERY:
        return _knowledge_query(query)
    if intent == GENERAL_CHAT:
        if session is None:
            return "通用对话需要 LLM 支持，但当前未提供数据库会话。"
        return _general_chat(query, session)

    return _general_chat(query, session) if session is not None else "未知意图。"


# ---------------------------------------------------------------------------
# 测试入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _session: Session | None = None
    try:
        from src.config.database import get_session_factory

        _session_factory = get_session_factory()
        _session = _session_factory()
    except Exception:  # noqa: BLE001 -- 测试入口允许宽泛捕获
        logger.warning("无法初始化数据库会话，general_chat 将降级", exc_info=True)

    # 支持命令行参数：python -m patterns.router "查询内容"
    if len(sys.argv) > 1:
        _queries: list[tuple[str | None, str]] = [(None, " ".join(sys.argv[1:]))]
    else:
        _queries = [
            ("github_search", "帮我搜索 python web framework 的 github 项目"),
            ("knowledge_query", "知识库里有没有 llm 相关的文章"),
            ("general_chat", "什么是 RAG？"),
        ]

    for _, q in _queries:
        print(f"\n{'=' * 60}")
        print(f"查询: {q}")
        print("-" * 60)
        try:
            result = route(q, session=_session)
            print(result)
        except Exception as e:  # noqa: BLE001 -- 测试入口允许宽泛捕获
            print(f"错误: {e}")
        print("=" * 60)

    if _session is not None:
        _session.close()
    sys.exit(0)
