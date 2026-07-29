"""LangGraph 修订节点：根据审核反馈批量改写 analyses。

由 :func:`revise_node` 实现。当审核不通过时，工作流将审核反馈注入
LLM prompt，让模型一次性改写全部 analyses 列表，而非逐条修正。

工作流位置::

    review ──not passed──> revise ──> review (最多 3 轮)

与 :func:`~src.graph.nodes.organize_node` 的区别：
    - organize_node：逐条调 LLM 修正，兼做去重/格式化/低分过滤
    - revise_node：一次性传全部 analyses + feedback，批量改写，不做过滤
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.common.trace import set_trace_id
from src.graph.state import KBState
from src.llm.client import LlmCallError
from src.llm.cost import TokenUsage

logger = logging.getLogger(__name__)

_REVISE_SYSTEM_PROMPT = (
    "你是一个知识库修订助手。请根据审核反馈对分析结果列表进行改写，"
    "输出严格的 JSON 数组格式，不要输出任何其他内容。\n"
    "保持原有数组和每条条目的 JSON 结构不变，仅根据反馈修改相应字段。"
    "输出数组的长度必须与输入数组完全一致。"
)

_REVISE_TEMPERATURE = 0.4


def _set_trace_from_state(state: KBState) -> None:
    """从 state 中读取 trace_id 并注入日志上下文。

    Args:
        state: 当前工作流状态。
    """
    trace_id = state.get("trace_id", "-")
    set_trace_id(trace_id)


def _accumulate_usage(
    tracker: dict[str, Any],
    node_name: str,
    usage: TokenUsage,
) -> None:
    """将单次 LLM 调用的 token 用量累加到 cost_tracker。

    Args:
        tracker: cost_tracker 字典（会被原地修改）。
        node_name: 节点名称。
        usage: 本次调用的 TokenUsage。
    """
    slot = tracker.setdefault(
        node_name,
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    slot["prompt_tokens"] += usage.prompt_tokens
    slot["completion_tokens"] += usage.completion_tokens
    slot["total_tokens"] += usage.total_tokens


def _parse_json_array(raw: str, context: str) -> list[dict[str, Any]]:
    """解析 LLM 输出的 JSON 数组文本。

    容忍前后多余的非 JSON 文本和 markdown code fence。

    Args:
        raw: LLM 原始输出文本。
        context: 调用上下文名称，用于错误消息。

    Returns:
        解析后的 list[dict]。

    Raises:
        ValueError: 输出无法解析为合法 JSON 数组。
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} 输出无法解析为 JSON: {exc}") from exc
    if not isinstance(result, list):
        raise ValueError(
            f"{context} 输出 JSON 顶层数据不是 list: {type(result).__name__}"
        )
    return [item for item in result if isinstance(item, dict)]


def revise_node(state: KBState) -> dict[str, Any]:
    """修订节点：根据审核反馈用 LLM 批量改写 analyses。

    读取 ``state["analyses"]`` 和 ``state["review_feedback"]``，
    将全部 analyses 和 feedback 拼成一次 prompt，调用 LLM 一次性改写。
    temperature=0.4 允许一定创造性改写。

    跳过条件（返回空 dict，不更新 state）：
        - ``analyses`` 为空
        - ``review_feedback`` 为空

    Args:
        state: 当前工作流状态，须包含 ``analyses`` 和 ``review_feedback``。

    Returns:
        状态更新 dict，包含 ``analyses``（改写后的列表）和
        ``cost_tracker``（累加 revise 节点用量）。
        跳过时返回 ``{}``。
    """
    _set_trace_from_state(state)

    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")

    if not analyses:
        logger.warning("无待修订 analyses, 跳过")
        return {}
    if not feedback:
        logger.warning("无审核反馈, 跳过")
        return {}

    logger.info(
        "启动, 待修订条目数: %d, feedback 长度: %d",
        len(analyses),
        len(feedback),
    )

    cost_tracker: dict[str, Any] = dict(state.get("cost_tracker", {}))

    # 延迟导入避免循环依赖（nodes.py 和 reviser.py 共享底层工具）
    from src.graph.nodes import _call_llm, _get_session

    try:
        session = _get_session()
        try:
            prompt = (
                "请根据以下审核反馈，对分析结果列表进行改写：\n\n"
                f"分析结果列表:\n{json.dumps(analyses, ensure_ascii=False, indent=2)}\n\n"
                f"审核反馈:\n{feedback}\n\n"
                "请输出改写后的完整 JSON 数组，结构与输入一致，"
                "数组长度必须与输入相同。"
            )
            raw_text, usage = _call_llm(
                prompt,
                session,
                system_prompt=_REVISE_SYSTEM_PROMPT,
                temperature=_REVISE_TEMPERATURE,
            )
            _accumulate_usage(cost_tracker, "revise", usage)
        finally:
            session.close()
    except (LlmCallError, RuntimeError) as exc:
        logger.error("修订 LLM 调用失败: %s", exc, exc_info=True)
        return {}

    improved = _parse_json_array(raw_text, "revise_node")

    # 保证输出长度与输入一致；不一致时回退到原始 analyses
    if len(improved) != len(analyses):
        logger.warning(
            "修订结果数量不匹配 (输入 %d, 输出 %d), 保留原始 analyses",
            len(analyses),
            len(improved),
        )
        return {"cost_tracker": cost_tracker}

    logger.info("修订完成, 共 %d 条", len(improved))
    return {"analyses": improved, "cost_tracker": cost_tracker}
