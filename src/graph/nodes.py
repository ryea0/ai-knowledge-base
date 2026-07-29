"""LangGraph 图节点定义。

每个节点对应工作流的一个阶段，接收 :class:`~src.graph.state.KBState`
并返回状态更新 dict（部分字段），遵循"纯函数"约定。

工作流流程::

    collect -> analyze -> organize -> review ──passed──> save
                                  └─not passed─> analyze (带 feedback, 最多 3 轮)

节点使用 :func:`src.llm.client.chat_completion_with_retry` 调用 LLM
（返回 :class:`~src.llm.response.LLMResponse`，含 token 用量），
通过 :func:`src.llm.router.select_first_available` 获取供应商-模型对。
LLM 调用的瞬时故障由 :func:`src.llm.retry_decorator.with_retry` 兜底重试。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.config.database import get_session_factory
from src.graph.state import KBState
from src.llm.client import LlmCallError, LLMResponse, chat_completion_with_retry
from src.llm.cost import TokenUsage
from src.llm.retry_decorator import with_retry
from src.llm.router import select_first_available

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_GITHUB_API_URL = "https://api.github.com/search/repositories"
_GITHUB_AI_QUERY = (
    "AI OR LLM OR agent OR RAG OR transformer "
    "OR fine-tuning OR multimodal OR embedding"
)
_GITHUB_PER_PAGE = 10
_GITHUB_SORT = "stars"
_GITHUB_ORDER = "desc"
_HTTP_TIMEOUT = 30

_MIN_SCORE = 0.6
_MAX_ITERATIONS = 3

_ARTICLES_DIR = os.path.join("knowledge", "articles")
_INDEX_FILE = os.path.join(_ARTICLES_DIR, "index.json")

_ANALYZE_SYSTEM_PROMPT = (
    "你是一个专业的 AI 技术分析师。请对给定的 GitHub 仓库进行分析，"
    "输出严格的 JSON 格式，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    "{\n"
    '  "title": "中文标题（保留专有名词英文）",\n'
    '  "summary": "2-4 句话中文摘要（150 字以内）",\n'
    '  "tags": ["小写英文标签", "3-8 个"],\n'
    '  "score": 0.0-1.0 的浮点数（质量评分）,\n'
    '  "category": "model_release|paper|tool|tutorial|news",\n'
    '  "language": "zh|en"\n'
    "}"
)

_ORGANIZE_SYSTEM_PROMPT = (
    "你是一个知识库整理助手。请根据审核反馈对分析结果进行定向修正，"
    "输出严格的 JSON 格式，不要输出任何其他内容。\n"
    "保持原有 JSON 结构不变，仅根据反馈修改相应字段。"
)

_REVIEW_SYSTEM_PROMPT = (
    "你是一个严格的知识库质量审核员。请从以下四个维度对知识条目逐一评分：\n"
    "1. summary_quality: 摘要质量（1-10）\n"
    "2. tag_accuracy: 标签准确性（1-10）\n"
    "3. category_correctness: 分类合理性（1-10）\n"
    "4. consistency: 一致性（标题/摘要/标签是否自洽）（1-10）\n"
    "输出严格的 JSON，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    "{\n"
    '  "passed": true/false,\n'
    '  "overall_score": 四维度平均分（浮点数）,\n'
    '  "feedback": "改进建议（通过时为空字符串）",\n'
    '  "scores": {\n'
    '    "summary_quality": 1-10,\n'
    '    "tag_accuracy": 1-10,\n'
    '    "category_correctness": 1-10,\n'
    '    "consistency": 1-10\n'
    "  }\n"
    "}\n"
    "passed 为 true 当且仅当 overall_score >= 7.0。"
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_json_output(raw: str, context: str) -> dict[str, Any]:
    """解析 LLM 输出的 JSON 文本。

    容忍前后多余的非 JSON 文本：提取第一个 ``{`` 到最后一个 ``}`` 之间的内容。

    Args:
        raw: LLM 原始输出文本。
        context: 调用上下文名称，用于错误消息。

    Returns:
        解析后的 dict。

    Raises:
        ValueError: 输出无法解析为合法 JSON dict。
    """
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} 输出无法解析为 JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(
            f"{context} 输出 JSON 顶层数据不是 dict: {type(result).__name__}"
        )
    return result


def _accumulate_usage(
    tracker: dict[str, Any],
    node_name: str,
    usage: TokenUsage,
) -> None:
    """将单次 LLM 调用的 token 用量累加到 cost_tracker。

    Args:
        tracker: cost_tracker 字典（会被原地修改）。
        node_name: 节点名称（如 ``"analyze"``）。
        usage: 本次调用的 TokenUsage。
    """
    slot = tracker.setdefault(
        node_name,
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    slot["prompt_tokens"] += usage.prompt_tokens
    slot["completion_tokens"] += usage.completion_tokens
    slot["total_tokens"] += usage.total_tokens


def _get_session() -> Session:
    """获取数据库会话。

    Returns:
        SQLAlchemy Session 实例。

    Raises:
        RuntimeError: 无法初始化数据库会话。
    """
    factory = get_session_factory()
    return factory()


def _call_llm(
    prompt: str,
    session: Session,
    *,
    system_prompt: str = "",
    temperature: float = 0.7,
) -> tuple[str, TokenUsage]:
    """调用 LLM 并返回 (文本, token 用量)。

    内部通过 :func:`select_first_available` 获取供应商-模型对，
    调用 :func:`chat_completion_with_retry` 发送单轮对话。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session。
        system_prompt: 可选的 system 消息。
        temperature: 采样温度。

    Returns:
        (回复文本, TokenUsage) 元组。

    Raises:
        LlmCallError: LLM 调用失败。
        RuntimeError: 无可用供应商-模型组合。
    """
    pair = select_first_available(session)
    if pair is None:
        raise RuntimeError("无可用 LLM 供应商-模型组合")
    provider, model = pair

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = chat_completion_with_retry(
        provider,
        model,
        messages,
        temperature=temperature,
        session=session,
    )

    if isinstance(response, LLMResponse):
        return response.content, response.usage
    return str(response), TokenUsage(0, 0, 0)


def _call_llm_json(
    prompt: str,
    session: Session,
    *,
    system_prompt: str = "",
    temperature: float = 0.7,
    context: str = "LLM",
) -> tuple[dict[str, Any], TokenUsage]:
    """调用 LLM 并解析 JSON 输出。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session。
        system_prompt: 可选的 system 消息。
        temperature: 采样温度。
        context: JSON 解析失败时的上下文名称。

    Returns:
        (解析后的 dict, TokenUsage) 元组。

    Raises:
        ValueError: LLM 输出无法解析为 JSON。
        LlmCallError: LLM 调用失败。
        RuntimeError: 无可用供应商-模型组合。
    """
    text, usage = _call_llm(
        prompt,
        session,
        system_prompt=system_prompt,
        temperature=temperature,
    )
    return _parse_json_output(text, context), usage


# ---------------------------------------------------------------------------
# 节点 1: collect_node
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict[str, Any]:
    """采集节点：调用 GitHub Search API 采集 AI 相关仓库。

    使用 ``urllib.request`` 直接请求 GitHub Search API，
    按 star 数降序排列，取前 ``_GITHUB_PER_PAGE`` 条。
    采集结果写入 ``sources`` 字段。

    Args:
        state: 当前工作流状态（本节点不读取任何字段）。

    Returns:
        状态更新 dict，包含 ``sources`` 和 ``cost_tracker``。
    """
    logger.info("[collect_node] 启动 GitHub 仓库采集")

    params = urllib.parse.urlencode(
        {
            "q": _GITHUB_AI_QUERY,
            "sort": _GITHUB_SORT,
            "order": _GITHUB_ORDER,
            "per_page": _GITHUB_PER_PAGE,
        }
    )
    url = f"{_GITHUB_API_URL}?{params}"

    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-knowledge-base",
    }
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    sources: list[dict[str, Any]] = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        for repo in data.get("items", []):
            sources.append(
                {
                    "title": repo.get("full_name", ""),
                    "url": repo.get("html_url", ""),
                    "source_platform": "github_trending",
                    "source_score": repo.get("stargazers_count", 0),
                    "summary": repo.get("description", ""),
                    "content_path": "",
                }
            )
        logger.info("[collect_node] 采集完成, 共 %d 条", len(sources))
    except urllib.error.URLError as exc:
        logger.error("[collect_node] GitHub API 请求失败: %s", exc)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("[collect_node] GitHub API 响应解析失败: %s", exc)

    return {"sources": sources}


# ---------------------------------------------------------------------------
# 节点 2: analyze_node
# ---------------------------------------------------------------------------


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条数据生成中文摘要、标签、评分。

    遍历 ``sources`` 中的每条候选条目，调用 LLM 进行分析，
    将结果写入 ``analyses`` 字段。Token 用量累加到 ``cost_tracker["analyze"]``。

    Args:
        state: 当前工作流状态，须包含 ``sources``。

    Returns:
        状态更新 dict，包含 ``analyses`` 和 ``cost_tracker``。
    """
    logger.info("[analyze_node] 启动, 待分析条目数: %d", len(state.get("sources", [])))

    sources = state.get("sources", [])
    if not sources:
        logger.warning("[analyze_node] 无待分析条目")
        return {"analyses": []}

    session = _get_session()
    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))
    analyses: list[dict[str, Any]] = []

    try:
        for item in sources:
            prompt = (
                f"仓库名称: {item.get('title', '')}\n"
                f"仓库链接: {item.get('url', '')}\n"
                f"Star 数: {item.get('source_score', 0)}\n"
                f"原始描述: {item.get('summary', '')}\n"
                "请分析此仓库的技术内容。"
            )
            result, usage = _call_llm_json(
                prompt,
                session,
                system_prompt=_ANALYZE_SYSTEM_PROMPT,
                temperature=0.3,
                context="analyze_node",
            )
            result["source_url"] = item.get("url", "")
            result["source_platform"] = item.get("source_platform", "")
            result["source_score"] = item.get("source_score", 0)
            _accumulate_usage(cost_tracker, "analyze", usage)
            analyses.append(result)
            logger.info(
                "[analyze_node] 分析完成: %s (score=%s)",
                result.get("title", "?"),
                result.get("score", "?"),
            )
    finally:
        session.close()

    return {"analyses": analyses, "cost_tracker": cost_tracker}


# ---------------------------------------------------------------------------
# 节点 3: organize_node
# ---------------------------------------------------------------------------


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def organize_node(state: KBState) -> dict[str, Any]:
    """整理节点：过滤低分、按 URL 去重、如有审核反馈则用 LLM 修正。

    处理流程：
        1. 过滤 ``score < _MIN_SCORE`` 的低分条目。
        2. 按 ``source_url`` 去重，保留首个出现的条目。
        3. 若 ``iteration > 0`` 且有 ``review_feedback``，
           调用 LLM 根据反馈对每条条目做定向修正。

    Args:
        state: 当前工作流状态，须包含 ``analyses``。

    Returns:
        状态更新 dict，包含 ``articles`` 和 ``cost_tracker``。
    """
    logger.info("[organize_node] 启动, 分析结果数: %d", len(state.get("analyses", [])))

    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))

    filtered = [a for a in analyses if _safe_float(a.get("score", 0)) >= _MIN_SCORE]
    logger.info(
        "[organize_node] 低分过滤: %d -> %d", len(analyses), len(filtered)
    )

    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in filtered:
        url = item.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
    logger.info(
        "[organize_node] URL 去重: %d -> %d", len(filtered), len(deduped)
    )

    articles: list[dict[str, Any]] = []
    if iteration > 0 and feedback:
        logger.info(
            "[organize_node] 检测到审核反馈 (iteration=%d), 调用 LLM 修正",
            iteration,
        )
        session = _get_session()
        try:
            for item in deduped:
                prompt = (
                    "以下是一个知识条目的分析结果，请根据审核反馈进行定向修正：\n\n"
                    f"分析结果:\n{json.dumps(item, ensure_ascii=False, indent=2)}\n\n"
                    f"审核反馈:\n{feedback}"
                )
                result, usage = _call_llm_json(
                    prompt,
                    session,
                    system_prompt=_ORGANIZE_SYSTEM_PROMPT,
                    temperature=0.3,
                    context="organize_node",
                )
                for key in ("source_url", "source_platform", "source_score"):
                    if key in item:
                        result[key] = item[key]
                _accumulate_usage(cost_tracker, "organize", usage)
                articles.append(_to_article_dict(result))
        finally:
            session.close()
    else:
        for item in deduped:
            articles.append(_to_article_dict(item))

    return {"articles": articles, "cost_tracker": cost_tracker}


# ---------------------------------------------------------------------------
# 节点 4: review_node
# ---------------------------------------------------------------------------


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：LLM 四维度评分，iteration >= 2 强制通过。

    评分维度：摘要质量 / 标签准确 / 分类合理 / 一致性。
    当 ``iteration >= _MAX_ITERATIONS`` 时跳过 LLM 审核直接强制通过，
    避免无限循环。

    Args:
        state: 当前工作流状态，须包含 ``articles`` 和 ``iteration``。

    Returns:
        状态更新 dict，包含 ``review_passed``、``review_feedback``
        和 ``cost_tracker``。
    """
    iteration = state.get("iteration", 0)
    logger.info(
        "[review_node] 启动, iteration=%d, 待审核条目数: %d",
        iteration,
        len(state.get("articles", [])),
    )

    if iteration >= _MAX_ITERATIONS:
        logger.warning(
            "[review_node] iteration=%d >= %d, 强制通过",
            iteration,
            _MAX_ITERATIONS,
        )
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    articles = state.get("articles", [])
    if not articles:
        logger.warning("[review_node] 无待审核条目, 自动通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    session = _get_session()
    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))

    try:
        prompt = (
            "请审核以下知识条目列表的质量：\n\n"
            f"{json.dumps(articles, ensure_ascii=False, indent=2)}"
        )
        result, usage = _call_llm_json(
            prompt,
            session,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            temperature=0.0,
            context="review_node",
        )
        _accumulate_usage(cost_tracker, "review", usage)
    finally:
        session.close()

    passed = bool(result.get("passed", False))
    overall_score = _safe_float(result.get("overall_score", 0))
    if not passed and overall_score >= 7.0:
        passed = True

    feedback = str(result.get("feedback", ""))
    if passed:
        feedback = ""

    logger.info(
        "[review_node] 审核完成: passed=%s, score=%.1f, feedback=%s",
        passed,
        overall_score,
        feedback[:100],
    )

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": cost_tracker,
    }


# ---------------------------------------------------------------------------
# 节点 5: save_node
# ---------------------------------------------------------------------------


def save_node(state: KBState) -> dict[str, Any]:
    """保存节点：将 articles 写入 knowledge/articles/ 的 JSON 文件。

    每条 article 写入独立的 ``<article_id>.json`` 文件，
    同时更新 ``index.json`` 索引文件（包含所有条目的元信息摘要）。

    Args:
        state: 当前工作流状态，须包含 ``articles``。

    Returns:
        状态更新 dict，包含 ``saved_count``。
    """
    logger.info(
        "[save_node] 启动, 待保存条目数: %d", len(state.get("articles", []))
    )

    articles = state.get("articles", [])
    if not articles:
        logger.warning("[save_node] 无待保存条目")
        return {"saved_count": 0}

    os.makedirs(_ARTICLES_DIR, exist_ok=True)

    saved: list[dict[str, Any]] = []
    for article in articles:
        article_id = article.get("article_id") or _generate_article_id()
        article["article_id"] = article_id

        if "collected_at" not in article:
            article["collected_at"] = datetime.now(UTC).isoformat()
        if "status" not in article:
            article["status"] = "pending"

        file_path = os.path.join(_ARTICLES_DIR, f"{article_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)
        logger.info("[save_node] 已保存: %s", file_path)
        saved.append(article)

    _update_index(saved)

    logger.info("[save_node] 保存完成, 共 %d 条", len(saved))
    return {"saved_count": len(saved)}


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float:
    """安全转换为 float，失败返回 0.0。

    Args:
        value: 待转换的值。

    Returns:
        转换后的浮点数，失败时为 0.0。
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_article_dict(analysis: dict[str, Any]) -> dict[str, Any]:
    """将分析结果转换为标准知识条目格式。

    Args:
        analysis: LLM 分析结果 dict。

    Returns:
        符合 article-format.md 的知识条目 dict。
    """
    now = datetime.now(UTC).isoformat()
    return {
        "article_id": _generate_article_id(),
        "title": analysis.get("title", ""),
        "source_url": analysis.get("source_url", ""),
        "source_platform": analysis.get("source_platform", "github_trending"),
        "source_score": analysis.get("source_score", 0),
        "summary": analysis.get("summary", ""),
        "content_path": "",
        "tags": analysis.get("tags", []),
        "category": analysis.get("category", "news"),
        "status": "pending",
        "language": analysis.get("language", "zh"),
        "collected_at": now,
        "analyzed_at": now,
        "published_at": None,
        "published_channels": None,
        "score": _safe_float(analysis.get("score", 0)),
    }


def _generate_article_id() -> str:
    """生成基于时间戳的 article_id。

    使用日期 + 8 位十六进制时间戳，保证单进程内唯一性。

    Returns:
        形如 ``kb-20260730-a1b2c3d4`` 的 ID。
    """
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    time_hex = f"{int(now.timestamp()):08x}"[-8:]
    return f"kb-{date_str}-{time_hex}"


def _update_index(articles: list[dict[str, Any]]) -> None:
    """更新 index.json 索引文件。

    读取现有索引（如果存在），合并新条目，写回文件。
    索引中每条记录只保留摘要字段（article_id / title / source_url / category / status）。

    Args:
        articles: 本次保存的知识条目列表。
    """
    existing: list[dict[str, Any]] = []
    if os.path.exists(_INDEX_FILE):
        try:
            with open(_INDEX_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_ids = {item.get("article_id") for item in existing}

    for article in articles:
        entry = {
            "article_id": article.get("article_id", ""),
            "title": article.get("title", ""),
            "source_url": article.get("source_url", ""),
            "category": article.get("category", ""),
            "status": article.get("status", "pending"),
        }
        if entry["article_id"] not in existing_ids:
            existing.append(entry)
        else:
            for i, item in enumerate(existing):
                if item.get("article_id") == entry["article_id"]:
                    existing[i] = entry
                    break

    with open(_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    logger.info("[save_node] 索引已更新: %s (%d 条)", _INDEX_FILE, len(existing))
