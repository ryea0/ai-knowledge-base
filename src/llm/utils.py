"""LLM 模块公共工具函数。

提取 ``client.py`` / ``connectivity.py`` 中重复的脱敏逻辑到统一入口。
"""

from __future__ import annotations

import re

_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "token",
)


def sanitize_secrets(text: str, *, max_length: int = 500) -> str:
    """脱敏文本中可能包含的 API Key / Token 等敏感信息。

    将 ``api_key`` / ``apikey`` / ``authorization`` / ``bearer`` / ``token``
    等关键词后的值替换为 ``***REDACTED***``，并截断至 ``max_length`` 字符。

    Args:
        text: 原始文本。
        max_length: 最大输出长度，默认 500。

    Returns:
        脱敏并截断后的文本。
    """
    sanitized = text
    for keyword in _SENSITIVE_KEYWORDS:
        if keyword.lower() in sanitized.lower():
            sanitized = re.sub(
                rf"(?i)({keyword})\s*[=:]\s*\S+",
                r"\1=***REDACTED***",
                sanitized,
            )
    return sanitized[:max_length]


__all__ = ["sanitize_secrets"]
