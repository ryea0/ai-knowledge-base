"""LLM 内容分析器。

调用 :func:`src.pipeline.llm_call_adapter.chat_for_analysis` 对每条采集内容进行分析，
生成中文摘要、亮点、1-10 评分、标签和分类。

分析结果为 JSON 字符串，本模块负责解析为 dict。
若 LLM 不可用或解析失败，降级为基于规则的简单分析。
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import re
from typing import Any

from src.llm.budget import BudgetExceededError
from src.llm.client import LlmCallError
from src.llm.retry_decorator import (
    NON_RETRYABLE_CONTENT_EXCEPTIONS,
    RETRYABLE_HTTP_EXCEPTIONS,
    NonRetryableLlmError,
    with_retry,
)
from src.pipeline.llm_call_adapter import chat_for_analysis

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一个 AI 技术内容分析专家。请分析给定内容并返回严格的 JSON 对象，包含以下字段：
- "summary": 中文摘要，2-4 句话，150 字以内
- "highlights": 亮点列表，2-5 条，每条一句话
- "score": 质量评分 1-10（整数）
- "tags": 标签列表，3-8 个，全小写英文
- "category": 分类，取值之一: model_release, paper, tool, tutorial, news
- "language": 原文语言，"zh" 或 "en"

只返回 JSON，不要其他文字。"""

_USER_PROMPT_TEMPLATE = """\
标题: {title}
来源: {source}
描述: {summary}

请分析以上内容并返回 JSON。"""

_VALID_CATEGORIES = {"model_release", "paper", "tool", "tutorial", "news"}

_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


class LLMAnalyzer:
    """基于 LLM 的内容分析器。

    使用 :func:`chat_for_analysis` 调用 LLM，自动路由到可用供应商。
    LLM 不可用时降级为规则分析。

    Attributes:
        temperature: LLM 采样温度。
        max_tokens: 最大输出 tokens。
    """

    def __init__(
        self,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> None:
        """初始化分析器。

        Args:
            temperature: 采样温度，分析任务建议低温度。
            max_tokens: 最大输出 tokens。
        """
        self.temperature = temperature
        self.max_tokens = max_tokens

    def analyze(self, item: dict[str, Any]) -> dict[str, Any]:
        """分析单条采集内容。

        调用 LLM 生成结构化分析结果，解析为 dict。
        LLM 不可用时降级为规则分析。

        Args:
            item: 采集条目，须含 title/source/summary。

        Returns:
            分析结果 dict，包含:
                - ``summary`` (str): 中文摘要。
                - ``highlights`` (list[str]): 亮点列表。
                - ``score`` (int): 1-10 评分。
                - ``tags`` (list[str]): 标签列表。
                - ``category`` (str): 分类字符串。
                - ``language`` (str): 原文语言。
        """
        try:
            return self._analyze_with_llm(item)
        except (
            LlmCallError,
            RuntimeError,
            BudgetExceededError,
            NonRetryableLlmError,
        ) as exc:
            logger.warning("LLM 分析失败，降级为规则分析: %s", exc)
            return self._fallback_analyze(item)

    def _analyze_with_llm(self, item: dict[str, Any]) -> dict[str, Any]:
        """调用 LLM 进行分析。

        使用 ``@with_retry`` 装饰的 ``chat_for_analysis`` 调用 LLM，
        重试参数按时间窗口策略表动态传入。

        Args:
            item: 采集条目。

        Returns:
            分析结果 dict。

        Raises:
            LlmCallError: LLM 调用失败（重试耗尽后）。
            RuntimeError: 无可用供应商或 JSON 解析失败。
            BudgetExceededError: 预算超限。
            NonRetryableLlmError: 不可重试的 LLM 错误。
        """
        from src.config.database import session_scope

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            title=item.get("title", ""),
            source=item.get("source", ""),
            summary=item.get("summary", ""),
        )

        retry_params = _get_retry_params()

        decorated_chat = with_retry(
            retry_on=(LlmCallError, *RETRYABLE_HTTP_EXCEPTIONS),
            no_retry_on=(
                BudgetExceededError,
                NonRetryableLlmError,
                *NON_RETRYABLE_CONTENT_EXCEPTIONS,
            ),
            **retry_params,
        )(chat_for_analysis)

        with session_scope() as session:
            raw_response = decorated_chat(
                prompt=user_prompt,
                session=session,
                system_prompt=_SYSTEM_PROMPT,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        return self._parse_llm_response(raw_response, item)

    @staticmethod
    def _strip_markdown_fence(text: str) -> str:
        """去除 Markdown 代码块标记（```json ... ```）。

        Args:
            text: 可能包含代码块标记的文本。

        Returns:
            去除标记后的文本。
        """
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines)
        return stripped

    def _parse_llm_response(
        self, raw_response: str, item: dict[str, Any]
    ) -> dict[str, Any]:
        """解析 LLM 返回的 JSON 响应。

        尝试直接 ``json.loads``，失败则用正则提取 JSON 子串。
        校验并填充缺失字段。

        Args:
            raw_response: LLM 返回的文本。
            item: 原始采集条目（用于降级填充）。

        Returns:
            分析结果 dict。

        Raises:
            RuntimeError: JSON 解析失败。
        """
        result: dict[str, Any] | None = None

        cleaned = self._strip_markdown_fence(raw_response)

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            match = _JSON_PATTERN.search(cleaned)
            if match:
                with contextlib.suppress(json.JSONDecodeError):
                    result = json.loads(match.group())

        if result is None:
            raise RuntimeError(f"LLM 响应解析失败: {raw_response[:200]}")

        return self._validate_result(result, item)

    @staticmethod
    def _validate_result(
        result: dict[str, Any], item: dict[str, Any]
    ) -> dict[str, Any]:
        """校验并补全分析结果字段。

        Args:
            result: LLM 解析出的 dict。
            item: 原始采集条目。

        Returns:
            校验后的完整分析结果 dict。
        """
        summary = str(result.get("summary", "")).strip()
        if not summary:
            summary = item.get("summary", "")[:150]

        highlights = result.get("highlights", [])
        if not isinstance(highlights, list):
            highlights = []

        score = result.get("score", 5)
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 5
        score = max(1, min(10, score))

        tags = result.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).lower().strip() for t in tags if str(t).strip()]

        category = str(result.get("category", "news")).strip()
        if category not in _VALID_CATEGORIES:
            category = "news"

        language = str(result.get("language", "en")).strip().lower()
        if language not in ("zh", "en"):
            language = "en"

        return {
            "summary": summary,
            "highlights": [str(h) for h in highlights],
            "score": score,
            "tags": tags,
            "category": category,
            "language": language,
        }

    @staticmethod
    def _fallback_analyze(item: dict[str, Any]) -> dict[str, Any]:
        """LLM 不可用时的规则降级分析。

        使用原始摘要截取、简单关键词分类、默认评分。

        Args:
            item: 采集条目。

        Returns:
            分析结果 dict。
        """
        summary = item.get("summary", "")[:150]
        title_lower = (item.get("title", "") + " " + summary).lower()

        if any(kw in title_lower for kw in ("gpt", "llama", "claude", "gemini", "qwen")):
            category = "model_release"
        elif any(kw in title_lower for kw in ("paper", "arxiv", "research")):
            category = "paper"
        elif any(kw in title_lower for kw in ("tool", "framework", "sdk", "library")):
            category = "tool"
        elif any(kw in title_lower for kw in ("tutorial", "guide", "how-to")):
            category = "tutorial"
        else:
            category = "news"

        tags: list[str] = []
        for kw in ("llm", "rag", "agent", "transformer", "embedding", "vllm",
                    "langchain", "fine-tuning", "multimodal"):
            if kw in title_lower:
                tags.append(kw)
        if not tags:
            tags = ["ai"]

        while len(tags) < 3:
            for fallback_tag in ("ai", "llm", "news"):
                if fallback_tag not in tags:
                    tags.append(fallback_tag)
                    break
            else:
                break

        return {
            "summary": summary or item.get("title", ""),
            "highlights": [],
            "score": 5,
            "tags": tags[:8],
            "category": category,
            "language": "en",
        }


def _get_retry_params(
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """按时间窗口获取重试参数。

    白天 (08:00-22:00): 容忍多次重试。
    夜间 (22:00-08:00): 失败不重试，避免长时间阻塞。

    Args:
        now: 可注入的当前时间，用于测试。默认 ``datetime.datetime.now()``。

    Returns:
        重试参数字典，可直接解包传入 ``with_retry``。
    """
    current = now or datetime.datetime.now()
    hour = current.hour
    if 8 <= hour < 22:
        return {"max_attempts": 3, "base_delay": 1.0, "backoff_factor": 2.0}
    return {"max_attempts": 1}
