"""LangGraph 图节点定义。

每个节点对应工作流的一个阶段，接收 :class:`~src.graph.state.KBState`
并返回状态更新 dict（部分字段），遵循"纯函数"约定。

工作流流程::

    collect -> analyze -> organize -> review ──passed──> save
                                  └─not passed─> organize (带 feedback, 最多 3 轮)

节点使用 :func:`src.llm.client.chat_completion_with_retry` 调用 LLM
（返回 :class:`~src.llm.response.LLMResponse`，含 token 用量），
通过 :func:`src.llm.router.select_first_available` 获取供应商-模型对。
LLM 调用的瞬时故障由 ``chat_completion_with_retry`` 内部重试兜底，
节点层不再叠加 ``@with_retry``，避免双重重试。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.collectors import default_registry, ensure_registered
from src.common.cost_guard import BudgetExceededError
from src.common.trace import set_trace_id
from src.config.database import get_session_factory, session_scope
from src.graph.security import filter_output, sanitize_input
from src.graph.state import KBState
from src.llm.client import LlmCallError, chat_completion_with_retry
from src.llm.cost import TokenUsage
from src.llm.response import LLMResponse
from src.llm.router import select_first_available
from src.models.article import Article
from src.models.enums import ArticleStatus
from src.utils.id_gen import build_article_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MIN_SCORE = 0.6
_MAX_ITERATIONS = 3
_MAX_LLM_WORKERS = 5

_ARTICLES_DIR = os.path.join("knowledge", "articles")
_INDEX_FILE = os.path.join(_ARTICLES_DIR, "index.json")
_FLAGGED_DIR = os.path.join("knowledge", "flagged")

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
    "你是一个严格的知识库质量审核员。请从以下五个维度对分析结果逐一评分：\n"
    "1. summary_quality: 摘要质量（1-10，摘要是否准确、简洁、信息完整）\n"
    "2. technical_depth: 技术深度（1-10，技术细节是否充分、有洞察）\n"
    "3. relevance: 相关性（1-10，与 AI/LLM/Agent 领域的相关程度）\n"
    "4. originality: 原创性（1-10，内容是否新颖、有独特价值）\n"
    "5. formatting: 格式规范（1-10，标签/分类/语言等格式是否合规）\n"
    "输出严格的 JSON，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    "{\n"
    '  "scores": {\n'
    '    "summary_quality": 1-10,\n'
    '    "technical_depth": 1-10,\n'
    '    "relevance": 1-10,\n'
    '    "originality": 1-10,\n'
    '    "formatting": 1-10\n'
    "  },\n"
    '  "feedback": "改进建议（通过时为空字符串）"\n'
    "}\n"
    "注意：overall_score 由调用方代码加权计算，你只需给出各维度分数和反馈。"
)

_REVIEW_DIMENSIONS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}
_REVIEW_PASS_THRESHOLD = 7.0
_REVIEW_MAX_ITEMS = 5
_REVIEW_TEMPERATURE = 0.1


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _set_trace_from_state(state: KBState) -> None:
    """从 state 中读取 trace_id 并注入日志上下文。

    Args:
        state: 当前工作流状态。
    """
    trace_id = state.get("trace_id", "-")
    set_trace_id(trace_id)


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
    # 兼容 LLM 输出 markdown code fence 的情况
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
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
    node_name: str = "",
) -> tuple[str, TokenUsage]:
    """调用 LLM 并返回 (文本, token 用量)。

    内部通过 :func:`select_first_available` 获取供应商-模型对，
    调用 :func:`chat_completion_with_retry` 发送单轮对话。

    成本追踪由 :func:`chat_completion` 内部统一处理（record + check），
    本函数不再重复调用，避免双重计数。超限时 ``chat_completion`` 抛出
    :class:`BudgetExceededError`，由调用方捕获处理。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session。
        system_prompt: 可选的 system 消息。
        temperature: 采样温度。
        node_name: 发起调用的节点名称，透传给 ``chat_completion_with_retry``
            用于成本追踪。

    Returns:
        (回复文本, TokenUsage) 元组。

    Raises:
        BudgetExceededError: 预算超限（由 ``chat_completion`` 内部 check 抛出）。
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
        node_name=node_name,
    )

    assert isinstance(response, LLMResponse)

    return response.content, response.usage


def _call_llm_json(
    prompt: str,
    session: Session,
    *,
    system_prompt: str = "",
    temperature: float = 0.7,
    context: str = "LLM",
    node_name: str = "",
) -> tuple[dict[str, Any], TokenUsage]:
    """调用 LLM 并解析 JSON 输出。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session。
        system_prompt: 可选的 system 消息。
        temperature: 采样温度。
        context: JSON 解析失败时的上下文名称。
        node_name: 发起调用的节点名称，透传给 :func:`_call_llm` 用于成本追踪。

    Returns:
        (解析后的 dict, TokenUsage) 元组。

    Raises:
        ValueError: LLM 输出无法解析为 JSON。
        LlmCallError: LLM 调用失败。
        RuntimeError: 无可用供应商-模型组合。
        BudgetExceededError: 预算超限。
    """
    text, usage = _call_llm(
        prompt,
        session,
        system_prompt=system_prompt,
        temperature=temperature,
        node_name=node_name,
    )
    return _parse_json_output(text, context), usage


# ---------------------------------------------------------------------------
# 节点 1: collect_node
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict[str, Any]:
    """采集节点：从所有已注册采集器聚合候选条目。

    遍历 :data:`src.collectors.default_registry` 中的全部采集器（GitHub、RSS 等），
    逐个调用 ``collect()``，将结果合并到 ``sources`` 列表。
    单个采集器失败不阻塞其他采集器，错误记入 ``errors``。

    可扩展：新增数据源只需在 ``src/collectors/`` 注册采集器，
    本节点自动发现并调用，无需修改图结构。

    Args:
        state: 当前工作流状态（本节点不读取任何字段）。

    Returns:
        状态更新 dict，包含 ``sources``，可能包含 ``errors``。
    """
    _set_trace_from_state(state)

    # 确保内置采集器已注册（惰性导入下不会在 import 时自动注册）
    ensure_registered()

    errors: list[dict[str, Any]] = list(state.get("errors", []))
    sources: list[dict[str, Any]] = []

    collectors = default_registry.get_all()
    logger.info("启动采集, 已注册采集器: %s", default_registry.names())

    for name, collector in collectors:
        try:
            items = collector.collect()
            for item in items:
                title = item.get("title", "")
                if title:
                    cleaned, warnings = sanitize_input(title)
                    if warnings:
                        logger.warning(
                            "采集条目标题存在安全风险: collector=%s warnings=%s",
                            name,
                            warnings,
                        )
                    item["title"] = cleaned
                summary = item.get("summary", "")
                if summary:
                    cleaned, warnings = sanitize_input(summary)
                    if warnings:
                        logger.warning(
                            "采集条目摘要存在安全风险: collector=%s warnings=%s",
                            name,
                            warnings,
                        )
                    item["summary"] = cleaned
            sources.extend(items)
            logger.info("采集器 %s: %d 条", name, len(items))
        except Exception as exc:
            logger.error("采集器 %s 失败: %s", name, exc, exc_info=True)
            errors.append(
                {
                    "node": "collect",
                    "error": f"[{name}] {exc}",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    logger.info("采集完成, 共 %d 条", len(sources))

    result: dict[str, Any] = {"sources": sources}
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# 节点 2: analyze_node
# ---------------------------------------------------------------------------


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条数据生成中文摘要、标签、评分。

    遍历 ``sources`` 中的每条候选条目，调用 LLM 进行分析，
    将结果写入 ``analyses`` 字段。Token 用量累加到 ``cost_tracker["analyze"]``。
    使用 ``ThreadPoolExecutor(max_workers=5)`` 并发调用 LLM 以加速分析。

    Args:
        state: 当前工作流状态，须包含 ``sources``。

    Returns:
        状态更新 dict，包含 ``analyses`` 和 ``cost_tracker``。
    """
    _set_trace_from_state(state)
    logger.info("启动, 待分析条目数: %d", len(state.get("sources", [])))

    sources = state.get("sources", [])
    if not sources:
        logger.warning("无待分析条目")
        return {"analyses": []}

    session = _get_session()
    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))
    analyses: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = list(state.get("errors", []))

    try:
        # 缓存 provider/model 查询结果，避免循环内重复查 DB
        pair = select_first_available(session)
        if pair is None:
            raise RuntimeError("无可用 LLM 供应商-模型组合")
        provider, model = pair

        def _analyze_one(
            item: dict[str, Any],
        ) -> tuple[dict[str, Any], TokenUsage]:
            """分析单条数据源。

            Args:
                item: 数据源摘要 dict。

            Returns:
                (分析结果 dict, TokenUsage) 元组。
            """
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
                node_name="analyze",
            )
            result["source_url"] = item.get("url", "")
            result["source_platform"] = item.get("source_platform", "")
            result["source_score"] = item.get("source_score", 0)
            return result, usage

        with ThreadPoolExecutor(max_workers=_MAX_LLM_WORKERS) as pool:
            futures = [pool.submit(_analyze_one, item) for item in sources]
            for fut in futures:
                try:
                    analysis, usage = fut.result()
                    _accumulate_usage(cost_tracker, "analyze", usage)
                    analyses.append(analysis)
                    logger.info(
                        "分析完成: %s (score=%s)",
                        analysis.get("title", "?"),
                        analysis.get("score", "?"),
                    )
                except BudgetExceededError:
                    logger.error("预算超限, 中止剩余分析")
                    errors.append(
                        {
                            "node": "analyze",
                            "error": "预算超限",
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
                    break
                except LlmCallError as exc:
                    logger.error("LLM 调用失败: %s", exc, exc_info=True)
                    errors.append(
                        {
                            "node": "analyze",
                            "error": str(exc),
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
    finally:
        session.close()

    result: dict[str, Any] = {
        "analyses": analyses,
        "cost_tracker": cost_tracker,
    }
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# 节点 3: organize_node
# ---------------------------------------------------------------------------


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
    _set_trace_from_state(state)
    logger.info("启动, 分析结果数: %d", len(state.get("analyses", [])))

    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))

    filtered = [a for a in analyses if _safe_float(a.get("score", 0)) >= _MIN_SCORE]
    logger.info("低分过滤: %d -> %d", len(analyses), len(filtered))

    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in filtered:
        url = item.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
    logger.info("URL 去重: %d -> %d", len(filtered), len(deduped))

    articles: list[dict[str, Any]] = []
    if iteration > 0 and feedback:
        logger.info(
            "检测到审核反馈 (iteration=%d), 调用 LLM 修正", iteration
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
                    node_name="organize",
                )
                for key in ("source_url", "source_platform", "source_score"):
                    if key in item:
                        result[key] = item[key]
                _accumulate_usage(cost_tracker, "organize", usage)
                articles.append(_filter_article_pii(_to_article_dict(result)))
        finally:
            session.close()
    else:
        for item in deduped:
            articles.append(_filter_article_pii(_to_article_dict(item)))

    return {"articles": articles, "cost_tracker": cost_tracker}


# ---------------------------------------------------------------------------
# 节点 4: review_node
# ---------------------------------------------------------------------------


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：5 维度 LLM 评分，代码加权重算总分。

    审核对象是 ``state["analyses"]``（不是 articles，articles 在 organize 之后）。
    只审核前 ``_REVIEW_MAX_ITEMS`` 条 analyses 以控制 token 消耗。
    加权总分由代码计算（不信任模型算术），``>= _REVIEW_PASS_THRESHOLD`` 为通过。
    LLM 调用失败时自动通过，不阻塞流程。

    当 ``iteration >= _MAX_ITERATIONS`` 时不再调用 LLM，直接返回
    ``review_passed=False``，由路由函数将条目导向人工标记节点。

    评分维度与权重::

        summary_quality   25%
        technical_depth   25%
        relevance         20%
        originality       15%
        formatting        15%

    Args:
        state: 当前工作流状态，须包含 ``analyses`` 和 ``iteration``。

    Returns:
        状态更新 dict，包含 ``review_passed``、``review_feedback``
        ``iteration`` 和 ``cost_tracker``。
    """
    _set_trace_from_state(state)
    iteration = state.get("iteration", 0)
    analyses = state.get("analyses", [])
    logger.info(
        "启动, iteration=%d, 待审核 analyses 数: %d",
        iteration,
        len(analyses),
    )

    if iteration >= _MAX_ITERATIONS:
        logger.warning(
            "iteration=%d >= %d, 审核仍未通过, 转入人工标记",
            iteration,
            _MAX_ITERATIONS,
        )
        return {
            "review_passed": False,
            "review_feedback": "审核循环达上限, 需人工判断",
            "iteration": iteration,
        }

    if not analyses:
        logger.warning("无待审核 analyses, 自动通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    # 只审核前 _REVIEW_MAX_ITEMS 条，控 token 消耗
    to_review = analyses[:_REVIEW_MAX_ITEMS]
    logger.info("审核前 %d 条 (共 %d)", len(to_review), len(analyses))

    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))

    try:
        session = _get_session()
        try:
            prompt = (
                "请审核以下分析结果列表的质量：\n\n"
                f"{json.dumps(to_review, ensure_ascii=False, indent=2)}"
            )
            result, usage = _call_llm_json(
                prompt,
                session,
                system_prompt=_REVIEW_SYSTEM_PROMPT,
                temperature=_REVIEW_TEMPERATURE,
                context="review_node",
                node_name="review",
            )
            _accumulate_usage(cost_tracker, "review", usage)
        finally:
            session.close()
    except BudgetExceededError:
        logger.error("审核时预算超限, 自动通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }
    except (LlmCallError, RuntimeError, ValueError) as exc:
        logger.error("审核 LLM 调用失败, 自动通过: %s", exc, exc_info=True)
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    # 代码重算加权总分（不信任模型算术）
    scores_dict = result.get("scores", {})
    if not isinstance(scores_dict, dict):
        scores_dict = {}

    overall_score = _compute_weighted_score(scores_dict)
    passed = overall_score >= _REVIEW_PASS_THRESHOLD

    feedback = str(result.get("feedback", ""))
    if passed:
        feedback = ""

    logger.info(
        "审核完成: passed=%s, overall_score=%.2f, feedback=%s",
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
    """保存节点：将 articles 写入 DB 和 knowledge/articles/ JSON 文件。

    写入顺序遵循 article-format spec §4：先写 DB（事务内），
    成功后同步写 JSON 文件。DB 为 source of truth，JSON 为磁盘投影。
    每条 article 写入独立的 ``<article_id>.json`` 文件，
    同时更新 ``index.json`` 索引文件。

    Args:
        state: 当前工作流状态，须包含 ``articles``。

    Returns:
        状态更新 dict，包含 ``saved_count``。
    """
    _set_trace_from_state(state)
    logger.info("启动, 待保存条目数: %d", len(state.get("articles", [])))

    articles = state.get("articles", [])
    if not articles:
        logger.warning("无待保存条目")
        return {"saved_count": 0}

    os.makedirs(_ARTICLES_DIR, exist_ok=True)

    saved: list[dict[str, Any]] = []
    with session_scope() as session:
        for article in articles:
            # 浅拷贝避免 mutate 输入 state（纯函数约定）
            article = dict(article)

            article_id = article.get("article_id") or _generate_article_id()
            article["article_id"] = article_id

            if "collected_at" not in article:
                article["collected_at"] = datetime.now(UTC).isoformat()
            if "status" not in article:
                article["status"] = "pending"

            # 写 DB
            orm_obj = _to_article_orm(article)
            session.add(orm_obj)
            session.flush()
            db_id = orm_obj.id
            # 用 DB 自增主键回填 article_id
            collected_at = datetime.now(UTC).replace(tzinfo=None)
            article["article_id"] = build_article_id(db_id, collected_at)
            orm_obj.article_id = article["article_id"]

            # 写 JSON 文件
            file_path = os.path.join(
                _ARTICLES_DIR, f"{article['article_id']}.json"
            )
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)
            logger.info("已保存: %s", file_path)
            saved.append(article)

    _update_index(saved)

    logger.info("保存完成, 共 %d 条", len(saved))
    return {"saved_count": len(saved)}


# ---------------------------------------------------------------------------
# 节点 6: human_flag_node
# ---------------------------------------------------------------------------


def human_flag_node(state: KBState) -> dict[str, Any]:
    """人工标记节点：将审核未通过的条目隔离到 ``knowledge/flagged/`` 目录。

    当审核循环达到 ``_MAX_ITERATIONS`` 仍未通过时，说明问题不在"质量"
    而在"数据"——需要人工判断。本节点将当前 analyses 连同审核反馈
    写入独立的 ``knowledge/flagged/`` 目录，不污染主知识库
    （``knowledge/articles/``）。

    每个批次写入一个 JSON 文件，文件名包含 trace_id 和时间戳：
    ``flagged-{trace_id}-{timestamp}.json``

    文件结构::

        {
            "trace_id": "...",
            "flagged_at": "2026-07-30T12:00:00Z",
            "iteration": 3,
            "review_feedback": "审核反馈内容",
            "analyses": [...],
        }

    Args:
        state: 当前工作流状态，须包含 ``analyses``、``iteration``
            和 ``review_feedback``。

    Returns:
        状态更新 dict，包含 ``human_flagged: True``。
    """
    _set_trace_from_state(state)

    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    trace_id = state.get("trace_id", "-")

    logger.warning(
        "人工标记: iteration=%d, analyses=%d, feedback=%s",
        iteration,
        len(analyses),
        feedback[:100],
    )

    os.makedirs(_FLAGGED_DIR, exist_ok=True)

    flag_record: dict[str, Any] = {
        "trace_id": trace_id,
        "flagged_at": datetime.now(UTC).isoformat(),
        "iteration": iteration,
        "review_feedback": feedback,
        "analyses": analyses,
    }

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    safe_trace = trace_id.replace("/", "-")[:16] if trace_id != "-" else "no-trace"
    filename = f"flagged-{safe_trace}-{timestamp}.json"
    file_path = os.path.join(_FLAGGED_DIR, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(flag_record, f, ensure_ascii=False, indent=2)

    logger.info("已写入人工标记文件: %s", file_path)
    return {"human_flagged": True}


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _filter_article_pii(article: dict[str, Any]) -> dict[str, Any]:
    """对知识条目执行 PII 过滤（输出安全）。

    对 ``title`` 和 ``summary`` 字段调用 :func:`filter_output`，
    检测并掩码手机号 / 邮箱 / 身份证 / 信用卡 / IP 等个人身份信息。

    Args:
        article: 知识条目 dict。

    Returns:
        过滤后的知识条目 dict（原地修改并返回）。
    """
    for field_name in ("title", "summary"):
        value = article.get(field_name, "")
        if value:
            filtered, detections = filter_output(value)
            if detections:
                logger.warning(
                    "知识条目 %s 包含 PII: field=%s types=%s",
                    article.get("article_id", "?"),
                    field_name,
                    detections,
                )
            article[field_name] = filtered
    return article


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


def _compute_weighted_score(scores: dict[str, Any]) -> float:
    """根据 5 维度评分和预设权重计算加权总分。

    使用 :data:`_REVIEW_DIMENSIONS` 中的权重（summary_quality 25%,
    technical_depth 25%, relevance 20%, originality 15%, formatting 15%）。
    每维度分数 clamp 到 [0, 10] 范围，缺失维度按 0 分处理。

    Args:
        scores: LLM 返回的各维度评分 dict，键为维度名，值为 1-10 的数字。

    Returns:
        加权总分（0.0-10.0）。
    """
    total = 0.0
    for dim, weight in _REVIEW_DIMENSIONS.items():
        raw = _safe_float(scores.get(dim, 0))
        clamped = max(0.0, min(10.0, raw))
        total += clamped * weight
    return round(total, 2)


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


def _to_article_orm(article: dict[str, Any]) -> Article:
    """将 article dict 转换为 Article ORM 对象。

    Args:
        article: 知识条目 dict。

    Returns:
        Article ORM 实例（尚未持久化）。
    """
    status_str = article.get("status", "pending")
    try:
        status = ArticleStatus.from_json_str(status_str)
    except ValueError:
        status = ArticleStatus.PENDING

    collected_at_str = article.get("collected_at", "")
    if collected_at_str:
        try:
            collected_at = datetime.fromisoformat(collected_at_str).replace(
                tzinfo=None
            )
        except ValueError:
            collected_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        collected_at = datetime.now(UTC).replace(tzinfo=None)

    analyzed_at_str = article.get("analyzed_at")
    analyzed_at: datetime | None = None
    if analyzed_at_str:
        try:
            analyzed_at = datetime.fromisoformat(analyzed_at_str).replace(
                tzinfo=None
            )
        except ValueError:
            analyzed_at = None

    return Article(
        article_id=article.get("article_id", ""),
        title=article.get("title", ""),
        source_url=article.get("source_url", ""),
        source_platform=article.get("source_platform", "github_trending"),
        source_score=article.get("source_score", 0),
        summary=article.get("summary", ""),
        content_path=article.get("content_path", ""),
        tags=article.get("tags", []),
        category=article.get("category", "news"),
        status=status,
        language=article.get("language", "zh"),
        collected_at=collected_at,
        analyzed_at=analyzed_at,
        score=int(_safe_float(article.get("score", 0)) * 10)
        if article.get("score") is not None
        else None,
        highlights=article.get("highlights"),
    )


def _generate_article_id() -> str:
    """生成基于时间戳 + 随机后缀的临时 article_id。

    使用日期 + 8 位十六进制时间戳 + 4 位随机后缀，保证单进程内唯一性。
    此 ID 为临时占位，save_node 写入 DB 后会用 ``build_article_id(db_id, ...)``
    回填正式的 ``kb-YYYYMMDD-NNNN`` 格式 ID。

    Returns:
        形如 ``kb-20260730-a1b2c3d4e5f6`` 的临时 ID。
    """
    import uuid

    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    time_hex = f"{int(now.timestamp()):08x}"[-8:]
    random_suffix = uuid.uuid4().hex[:4]
    return f"kb-{date_str}-{time_hex}{random_suffix}"


def _update_index(articles: list[dict[str, Any]]) -> None:
    """更新 index.json 索引文件（原子写入）。

    读取现有索引（如果存在），合并新条目，写回文件。
    索引中每条记录只保留摘要字段（article_id / title / source_url / category / status）。
    使用临时文件 + ``os.replace`` 保证原子性，避免并发写入丢更新。

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

    # 原子写入：先写临时文件，再 os.replace 覆盖
    os.makedirs(os.path.dirname(_INDEX_FILE), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(_INDEX_FILE), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _INDEX_FILE)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    logger.info("索引已更新: %s (%d 条)", _INDEX_FILE, len(existing))
