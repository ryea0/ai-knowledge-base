"""Supervisor 监督模式：Worker 产出 -> Supervisor 审核 -> 循环重做。

工作流程：
    1. Worker Agent 接收任务，输出 JSON 格式的分析报告
    2. Supervisor Agent 对 Worker 产出进行质量审核
       - 评分维度：准确性(1-10)、深度(1-10)、格式(1-10)
       - 输出 JSON: {"passed": bool, "score": int, "feedback": str}
    3. 审核循环：
       - 通过（score >= 7）-> 返回结果
       - 不通过 -> 带反馈重做（最多 max_retries 轮）
       - 超过 max_retries -> 强制返回 + 警告

LLM 调用通过 :func:`src.llm.client.quick_chat`（内部封装
:func:`chat_completion_with_retry` + 健康联动 + 预算控制），
对偶发 ``LlmCallError`` 由 :func:`src.llm.retry_decorator.with_retry` 兜底重试。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from src.llm.client import LlmCallError, quick_chat
from src.llm.retry_decorator import with_retry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PASS_THRESHOLD = 7  # 审核通过分数线

_WORKER_SYSTEM_PROMPT = (
    "你是一个专业的技术分析助手。请对给定任务进行深入分析，"
    "输出严格的 JSON 格式报告，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    '{"title": "报告标题", "summary": "摘要", '
    '"details": "详细分析", "tags": ["标签1", "标签2"]}\n'
    "要求：内容准确、分析深入、格式规范。"
)

_SUPERVISOR_SYSTEM_PROMPT = (
    "你是一个严格的质量审核员。请对 Worker 的分析报告进行评分。\n"
    "评分维度：准确性(1-10)、深度(1-10)、格式(1-10)。\n"
    "输出严格的 JSON，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    '{"passed": true/false, "score": 1-10的整数, "feedback": "改进建议"}\n'
    "score 为三个维度的平均分（四舍五入取整）。\n"
    "passed 为 true 当且仅当 score >= 7。"
)

# ---------------------------------------------------------------------------
# Worker Agent
# ---------------------------------------------------------------------------


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def _worker(
    task: str,
    session: Session,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Worker Agent：接收任务，输出 JSON 分析报告。

    当传入 ``feedback`` 时，将上一轮 Supervisor 的反馈追加到 prompt，
    引导 Worker 针对性改进。

    Args:
        task: 分析任务描述。
        session: SQLAlchemy Session，用于 LLM 调用。
        feedback: 上一轮 Supervisor 的改进建议，首轮为 None。

    Returns:
        解析后的 JSON dict，包含 title/summary/details/tags 等字段。

    Raises:
        ValueError: LLM 输出无法解析为合法 JSON。
        LlmCallError: LLM 调用失败（重试耗尽后）。
    """
    prompt = f"任务：{task}"
    if feedback:
        prompt += f"\n\n上一轮审核反馈，请针对性改进：\n{feedback}"

    raw = quick_chat(
        prompt,
        session,
        system_prompt=_WORKER_SYSTEM_PROMPT,
        temperature=0.3,
    )
    logger.debug("Worker 原始输出: %s", raw)
    return _parse_json_output(raw, "Worker")


# ---------------------------------------------------------------------------
# Supervisor Agent
# ---------------------------------------------------------------------------


@with_retry(
    retry_on=(LlmCallError,),
    max_attempts=3,
    base_delay=1.0,
)
def _supervisor(
    task: str,
    worker_output: dict[str, Any],
    session: Session,
) -> dict[str, Any]:
    """Supervisor Agent：对 Worker 产出进行质量审核。

    Args:
        task: 原始任务描述，供 Supervisor 参考审核标准。
        worker_output: Worker 的分析报告 dict。
        session: SQLAlchemy Session，用于 LLM 调用。

    Returns:
        审核结果 dict，包含 passed(bool)/score(int)/feedback(str)。

    Raises:
        ValueError: LLM 输出无法解析为合法 JSON。
        LlmCallError: LLM 调用失败（重试耗尽后）。
    """
    prompt = (
        f"原始任务：{task}\n\n"
        f"Worker 报告：\n{json.dumps(worker_output, ensure_ascii=False)}"
    )
    raw = quick_chat(
        prompt,
        session,
        system_prompt=_SUPERVISOR_SYSTEM_PROMPT,
        temperature=0.0,
    )
    logger.debug("Supervisor 原始输出: %s", raw)
    return _parse_json_output(raw, "Supervisor")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Supervisor 监督模式统一入口。

    执行 Worker -> Supervisor 审核循环：
        - Supervisor 评分 >= 7 -> 通过，返回结果
        - 评分 < 7 -> 带反馈重做，最多 ``max_retries`` 轮
        - 超过 ``max_retries`` 仍未通过 -> 强制返回最后一次结果 + 警告

    Args:
        task: 分析任务描述。
        max_retries: 最大重做次数（含首次），取值 1-10。

    Returns:
        结果 dict，包含以下字段：
        - ``output``: Worker 最终分析报告 dict
        - ``attempts``: 实际尝试次数
        - ``final_score``: Supervisor 最终评分
        - ``passed``: 是否通过审核
        - ``warning``: 仅在超时未通过时存在，描述强制返回

    Raises:
        ValueError: ``max_retries`` 越界。
    """
    if not 1 <= max_retries <= 10:
        raise ValueError(f"max_retries 须在 1-10 范围内, 实际值: {max_retries}")

    session = _get_session()
    if session is None:
        raise RuntimeError("无法初始化数据库会话，supervisor 需要 LLM 支持")

    try:
        return _run_supervision_loop(task, max_retries, session)
    finally:
        session.close()


def _run_supervision_loop(
    task: str,
    max_retries: int,
    session: Session,
) -> dict[str, Any]:
    """执行审核循环核心逻辑。

    Args:
        task: 分析任务描述。
        max_retries: 最大重做次数。
        session: SQLAlchemy Session。

    Returns:
        结果 dict，字段同 :func:`supervisor`。
    """
    feedback: str | None = None
    worker_output: dict[str, Any] = {}
    review: dict[str, Any] = {"passed": False, "score": 0, "feedback": ""}

    for attempt in range(1, max_retries + 1):
        logger.info("Supervisor 第 %d/%d 轮", attempt, max_retries)

        worker_output = _worker(task, session, feedback=feedback)
        review = _supervisor(task, worker_output, session)

        passed = bool(review.get("passed", False))
        score = int(review.get("score", 0))
        feedback = str(review.get("feedback", ""))

        logger.info(
            "第 %d 轮审核: passed=%s, score=%d, feedback=%s",
            attempt, passed, score, feedback[:100],
        )

        if passed or score >= _PASS_THRESHOLD:
            return {
                "output": worker_output,
                "attempts": attempt,
                "final_score": score,
                "passed": True,
            }

    logger.warning("Supervisor 审核循环耗尽 %d 轮, 强制返回", max_retries)
    return {
        "output": worker_output,
        "attempts": max_retries,
        "final_score": int(review.get("score", 0)),
        "passed": False,
        "warning": (
            f"经过 {max_retries} 轮审核仍未通过（最终评分: "
            f"{review.get('score', 0)}），强制返回最后结果。"
        ),
    }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_json_output(raw: str, agent_name: str) -> dict[str, Any]:
    """解析 LLM 输出的 JSON 文本。

    容忍前后多余的非 JSON 文本：提取第一个 ``{`` 到最后一个 ``}`` 之间的内容。
    若提取后仍无法解析，抛出 ValueError。

    Args:
        raw: LLM 原始输出文本。
        agent_name: Agent 名称，用于错误消息（Worker/Supervisor）。

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
        raise ValueError(
            f"{agent_name} 输出无法解析为 JSON: {exc}"
        ) from exc

    if not isinstance(result, dict):
        raise ValueError(
            f"{agent_name} 输出 JSON 顶层数据不是 dict: {type(result).__name__}"
        )

    return result


def _get_session() -> Session | None:
    """获取数据库会话。

    尝试从 ``src.config.database`` 创建 Session，失败时返回 None。

    Returns:
        SQLAlchemy Session 实例，或 None。
    """
    try:
        from src.config.database import get_session_factory

        factory = get_session_factory()
        return factory()
    except Exception:  # noqa: BLE001 -- 测试入口允许宽泛捕获
        logger.warning("无法初始化数据库会话", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 测试入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _task: str
    if len(sys.argv) > 1:
        _task = " ".join(sys.argv[1:])
    else:
        _task = "分析 LangGraph 和 CrewAI 在多智能体编排上的核心差异"

    print(f"\n{'=' * 60}")
    print(f"任务: {_task}")
    print("-" * 60)

    try:
        _result = supervisor(_task)
        print(json.dumps(_result, ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001 -- 测试入口允许宽泛捕获
        print(f"错误: {e}")
    print("=" * 60)
    sys.exit(0)
