"""LLM 响应内容提取器 -- 策略模式。

不同供应商的推理模型将回复内容放在不同字段中：

+----------+--------------------------+-------------------------------------------+
| 模型类型 | 字段名                   | 示例供应商                                |
+==========+==========================+===========================================+
| 标准     | message.content          | GPT-4o, DeepSeek-Chat, Qwen-Plus, Ollama  |
| 推理     | message.reasoning_content| DeepSeek-R1/V4, Qwen3, Volcengine doubao  |
| Thinking | message.thinking_blocks  | Claude (extended thinking)                |
+----------+--------------------------+-------------------------------------------+

按模型的 ``supports_reasoning`` 标志选择对应提取器，
调用方只需 :func:`extract_content`，无需关心字段差异。

设计模式与 :mod:`src.llm.auth_adapter` / :mod:`src.llm.connectivity` 一致，
均为策略模式 + 工厂分派。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.llm.orm import LlmModel

logger = logging.getLogger(__name__)


class ResponseExtractor(ABC):
    """响应内容提取器抽象基类（策略模式）。

    每个子类对应一种响应字段布局，负责从 LiteLLM 响应中
   提取回复文本。
    """

    @abstractmethod
    def extract(self, response: dict[str, Any] | object) -> str:
        """从 LiteLLM 响应中提取回复文本。

        Args:
            response: LiteLLM 响应对象或字典。

        Returns:
            回复文本，提取失败时返回空字符串。
        """


class StandardExtractor(ResponseExtractor):
    """标准提取器 -- 从 ``message.content`` 提取。

    适用于非推理模型（GPT-4o, DeepSeek-Chat, Ollama 等）。
    """

    def extract(self, response: dict[str, Any] | object) -> str:
        message = _get_first_message(response)
        if message is None:
            return ""
        return _get_str_field(message, "content")


class ReasoningExtractor(ResponseExtractor):
    """推理模型提取器 -- ``content`` 优先，空则回退 ``reasoning_content``。

    适用于 DeepSeek-R1/V4、Qwen3、Volcengine doubao 等推理模型。
    这些模型可能在 ``content`` 中返回最终答案、在 ``reasoning_content``
    中返回推理过程；当 ``max_tokens`` 不足时 ``content`` 为空，
    仅有 ``reasoning_content``。
    """

    def extract(self, response: dict[str, Any] | object) -> str:
        message = _get_first_message(response)
        if message is None:
            return ""
        content = _get_str_field(message, "content")
        if content:
            return content
        return _get_str_field(message, "reasoning_content")


class ThinkingBlockExtractor(ResponseExtractor):
    """Thinking 块提取器 -- 从 ``thinking_blocks`` 拆解文本。

    适用于 Claude extended thinking 模型。
    ``thinking_blocks`` 是一个列表，每项含 ``type`` 和 ``thinking`` 字段。
    本提取器将所有 ``thinking`` 文本拼接返回。

    同样回退 ``content`` 和 ``reasoning_content`` 以保证兼容性。
    """

    def extract(self, response: dict[str, Any] | object) -> str:
        message = _get_first_message(response)
        if message is None:
            return ""
        content = _get_str_field(message, "content")
        if content:
            return content

        thinking_blocks = _get_field(message, "thinking_blocks")
        if thinking_blocks:
            parts: list[str] = []
            for block in thinking_blocks:
                if isinstance(block, dict):
                    text = block.get("thinking", "")
                else:
                    text = getattr(block, "thinking", "")
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts)

        return _get_str_field(message, "reasoning_content")


_STANDARD = StandardExtractor()
_REASONING = ReasoningExtractor()
_THINKING = ThinkingBlockExtractor()


def get_extractor(model: LlmModel | None) -> ResponseExtractor:
    """根据模型的 ``supports_reasoning`` 标志返回对应提取器。

    Args:
        model: 模型 ORM 对象。None 时返回标准提取器。

    Returns:
        :class:`ResponseExtractor` 实例。
    """
    if model is not None and getattr(model, "supports_reasoning", False):
        return _REASONING
    return _STANDARD


def extract_content(
    response: dict[str, Any] | object,
    model: LlmModel | None = None,
) -> str:
    """从 LiteLLM 响应中提取回复文本（统一入口）。

    根据模型类型自动选择提取策略：
        - ``supports_reasoning=True`` -> :class:`ReasoningExtractor`
        - ``supports_reasoning=False`` -> :class:`StandardExtractor`
        - ``model=None`` -> :class:`StandardExtractor`

    Args:
        response: LiteLLM 响应对象或字典。
        model: 模型 ORM 对象，用于判断推理类型。None 时使用标准提取。

    Returns:
        回复文本，提取失败时返回空字符串。
    """
    extractor = get_extractor(model)
    return extractor.extract(response)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------


def _get_first_message(
    response: dict[str, Any] | object,
) -> dict[str, Any] | object | None:
    """从响应中提取第一个 choice 的 message 对象。

    兼容 ``dict`` 和 ``ModelResponse`` 两种形态。

    Args:
        response: LiteLLM 响应。

    Returns:
        message 对象，不存在时返回 None。
    """
    if isinstance(response, dict):
        choices = response.get("choices")
    else:
        choices = getattr(response, "choices", None)

    if not choices:
        return None

    first_choice = choices[0]
    if isinstance(first_choice, dict):
        return first_choice.get("message")
    return getattr(first_choice, "message", None)


def _get_field(obj: dict[str, Any] | object, field_name: str) -> Any:
    """从对象或字典中安全提取字段值。

    Args:
        obj: dict 或 Pydantic model 对象。
        field_name: 字段名。

    Returns:
        字段值，不存在时返回 None。
    """
    if isinstance(obj, dict):
        return obj.get(field_name)
    return getattr(obj, field_name, None)


def _get_str_field(obj: dict[str, Any] | object, field_name: str) -> str:
    """从对象或字典中安全提取字符串字段。

    Args:
        obj: dict 或 Pydantic model 对象。
        field_name: 字段名。

    Returns:
        字段值字符串，不存在或非字符串时返回空字符串。
    """
    val = _get_field(obj, field_name)
    if val is None:
        return ""
    return str(val) if val else ""


__all__ = [
    "ReasoningExtractor",
    "ResponseExtractor",
    "StandardExtractor",
    "ThinkingBlockExtractor",
    "extract_content",
    "get_extractor",
]
