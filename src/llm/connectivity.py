"""供应商连通性测试 -- 按 ``litellm_provider``（协议族）分派到不同探测端点。

协议族与探测方式：

    +------------------+--------------------------+-------------------------------------------+
    | litellm_provider | 端点                     | 鉴权                                      |
    +==================+==========================+===========================================+
    | openai           | GET {base_url}/models    | Bearer Token（Authorization: Bearer <key>） |
    | anthropic        | GET {base_url}/models    | Header: x-api-key + anthropic-version      |
    | ollama           | GET {base_url}/api/tags  | 无认证                                    |
    | llamacpp         | GET {base_url}/models    | 无认证                                    |
    +------------------+--------------------------+-------------------------------------------+

设计要点：
    - 按 ``litellm_provider`` 分派，而非 ``auth_type`` -- 协议族决定端点和鉴权方式。
    - OpenAI 兼容供应商（deepseek/ark/qwen 等）的 ``litellm_provider`` 均为 ``openai``。
    - llama.cpp 服务器（``llama-server``）虽兼容 OpenAI ``/models`` 端点，但无需鉴权，
      故独立为 ``llamacpp`` 协议族，避免误发 Bearer header。
    - 鉴权凭证通过 :mod:`src.llm.auth_adapter` 统一解密，本模块仅负责按协议族组装请求。
    - 返回 :class:`ConnectivityResult`，包含成功/失败状态、延迟、错误信息。

设计详见 docs/specs/llm-provider.md §9.3-9.4。
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from src.llm.auth_adapter import build_auth_context
from src.llm.orm import LlmProvider

logger = logging.getLogger(__name__)

ANTHROPIC_API_VERSION = "2023-06-01"

_VERSION_SEGMENT_RE = re.compile(r"/v\d+(?:/|$)", re.IGNORECASE)


def build_openai_models_url(base_url: str) -> str:
    """构造 OpenAI 兼容协议的 ``/models`` 端点 URL。

    规范约定 ``base_url`` 应含版本段（如 ``/v1``），但部分供应商配置时
    可能省略。本函数在缺少版本段时自动补 ``/v1``：

    - ``https://api.openai.com/v1``      -> ``.../v1/models``
    - ``https://api.deepseek.com``       -> ``.../v1/models``（自动补 /v1）
    - ``https://dashscope.../v1``        -> ``.../v1/models``
    - ``https://ark.../api/v3``          -> ``.../api/v3/models``（已含版本段）
    - ``http://localhost:8080/v1/``      -> ``.../v1/models``（末尾 / 移除）

    Args:
        base_url: 供应商配置的 API 基础 URL。

    Returns:
        拼接后的完整 ``/models`` 端点 URL。
    """
    normalized = base_url.rstrip("/")
    if _VERSION_SEGMENT_RE.search(normalized + "/"):
        return f"{normalized}/models"
    return f"{normalized}/v1/models"


@dataclass
class ConnectivityResult:
    """连通性测试结果。

    Attributes:
        success: 是否连通成功。
        latency_ms: 响应延迟毫秒，失败时为 None。
        status_code: HTTP 状态码，网络异常时为 None。
        error: 错误信息（已脱敏），成功时为 None。
        endpoint: 实际请求的 URL。
    """

    success: bool
    latency_ms: int | None
    status_code: int | None
    error: str | None
    endpoint: str


class ConnectivityProbe(ABC):
    """连通性探测适配器抽象基类（策略模式）。

    每个子类对应一个协议族，负责构造请求 URL、headers 并解析响应。
    """

    @abstractmethod
    def test(self, provider: LlmProvider) -> ConnectivityResult:
        """执行连通性测试。

        Args:
            provider: 供应商 ORM 对象。

        Returns:
            :class:`ConnectivityResult` 测试结果。
        """


class OpenAIConnectivityProbe(ConnectivityProbe):
    """OpenAI 兼容协议探测。

    调用 ``GET {base_url}/models``，使用 Bearer Token 鉴权。
    适用于 litellm_provider = ``openai`` 的所有供应商
   （OpenAI / DeepSeek / Ark / Qwen / llama.cpp 等）。
    """

    def test(self, provider: LlmProvider) -> ConnectivityResult:
        ctx = build_auth_context(provider)
        url = build_openai_models_url(provider.base_url)

        headers: dict[str, str] = {"Accept": "application/json"}
        if ctx.api_key:
            headers["Authorization"] = f"Bearer {ctx.api_key}"
        if ctx.extra_headers:
            headers.update(ctx.extra_headers)

        return _execute_get(
            url=url,
            headers=headers,
            timeout=provider.timeout_seconds,
            provider_code=provider.provider_code,
        )


class AnthropicConnectivityProbe(ConnectivityProbe):
    """Anthropic 原生协议探测。

    调用 ``GET {base_url}/models``，使用 ``x-api-key`` header + ``anthropic-version`` header。
    """

    def test(self, provider: LlmProvider) -> ConnectivityResult:
        ctx = build_auth_context(provider)
        url = build_openai_models_url(provider.base_url)

        headers: dict[str, str] = {
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_API_VERSION,
        }
        if ctx.extra_headers:
            headers.update(ctx.extra_headers)
        elif ctx.api_key:
            headers["x-api-key"] = ctx.api_key

        return _execute_get(
            url=url,
            headers=headers,
            timeout=provider.timeout_seconds,
            provider_code=provider.provider_code,
        )


class OllamaConnectivityProbe(ConnectivityProbe):
    """Ollama 原生协议探测。

    调用 ``GET {base_url}/api/tags``，无认证。
    Ollama 的 ``/api/tags`` 返回 ``{"models": [...]}`` 格式。
    """

    def test(self, provider: LlmProvider) -> ConnectivityResult:
        url = provider.base_url.rstrip("/") + "/api/tags"

        headers: dict[str, str] = {"Accept": "application/json"}

        return _execute_get(
            url=url,
            headers=headers,
            timeout=provider.timeout_seconds,
            provider_code=provider.provider_code,
        )


class LlamaCppConnectivityProbe(ConnectivityProbe):
    """llama.cpp 服务器探测。

    调用 ``GET {base_url}/models``，无认证。
    ``llama-server`` 兼容 OpenAI ``/models`` 端点，但不校验任何鉴权 header，
    故独立为 ``llamacpp`` 协议族，避免误发 Bearer token。
    URL 拼接复用 :func:`build_openai_models_url` 以自动补全 ``/v1``。
    """

    def test(self, provider: LlmProvider) -> ConnectivityResult:
        url = build_openai_models_url(provider.base_url)

        headers: dict[str, str] = {"Accept": "application/json"}

        return _execute_get(
            url=url,
            headers=headers,
            timeout=provider.timeout_seconds,
            provider_code=provider.provider_code,
        )


_PROBES: dict[str, ConnectivityProbe] = {
    "openai": OpenAIConnectivityProbe(),
    "anthropic": AnthropicConnectivityProbe(),
    "ollama": OllamaConnectivityProbe(),
    "llamacpp": LlamaCppConnectivityProbe(),
}


def test_connectivity(provider: LlmProvider) -> ConnectivityResult:
    """按供应商的 ``litellm_provider``（协议族）执行连通性测试。

    分派规则：

    +-------------------+--------------------+------------------------------------------+
    | litellm_provider  | 探测器             | 端点 & 鉴权                              |
    +===================+====================+==========================================+
    | openai            | OpenAIProbe        | GET {base_url}/models, Bearer Token      |
    | anthropic         | AnthropicProbe     | GET {base_url}/models, x-api-key + ver   |
    | ollama            | OllamaProbe        | GET {base_url}/api/tags, 无认证           |
    | llamacpp          | LlamaCppProbe      | GET {base_url}/models, 无认证             |
    +-------------------+--------------------+------------------------------------------+

    未知协议族回退到 OpenAI 兼容探测（最通用）。

    Args:
        provider: 供应商 ORM 对象。

    Returns:
        :class:`ConnectivityResult` 测试结果。
    """
    probe = _PROBES.get(provider.litellm_provider)
    if probe is None:
        logger.warning(
            "未知 litellm_provider=%s，回退到 OpenAI 兼容探测",
            provider.litellm_provider,
        )
        probe = _PROBES["openai"]

    result = probe.test(provider)
    logger.info(
        "连通性测试: provider=%s protocol=%s success=%s latency=%sms",
        provider.provider_code,
        provider.litellm_provider,
        result.success,
        result.latency_ms,
    )
    return result


def _execute_get(
    url: str,
    headers: dict[str, str],
    timeout: int,
    provider_code: str,
) -> ConnectivityResult:
    """执行 GET 请求并构造 :class:`ConnectivityResult`。

    Args:
        url: 请求 URL。
        headers: 请求 headers。
        timeout: 超时秒数。
        provider_code: 供应商代码（仅用于日志）。

    Returns:
        :class:`ConnectivityResult` 实例。
    """
    start = time.monotonic()

    try:
        resp = httpx.get(url, headers=headers, timeout=timeout)
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code < 400:
            return ConnectivityResult(
                success=True,
                latency_ms=latency_ms,
                status_code=resp.status_code,
                error=None,
                endpoint=url,
            )

        error_msg = _sanitize_error(resp.text, resp.status_code)
        logger.warning(
            "供应商 %s 连通性测试失败: HTTP %d",
            provider_code,
            resp.status_code,
        )
        return ConnectivityResult(
            success=False,
            latency_ms=latency_ms,
            status_code=resp.status_code,
            error=error_msg,
            endpoint=url,
        )

    except httpx.TimeoutException as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("供应商 %s 连通性测试超时: %s", provider_code, exc)
        return ConnectivityResult(
            success=False,
            latency_ms=latency_ms,
            status_code=None,
            error=f"请求超时: {exc}",
            endpoint=url,
        )
    except httpx.HTTPError as exc:
        logger.warning("供应商 %s 连通性测试网络错误: %s", provider_code, exc)
        return ConnectivityResult(
            success=False,
            latency_ms=None,
            status_code=None,
            error=f"网络错误: {exc}",
            endpoint=url,
        )


def _sanitize_error(text: str, status_code: int) -> str:
    """脱敏 HTTP 错误响应体。

    截断至 500 字符，移除可能包含的 API Key 片段。

    Args:
        text: HTTP 响应体文本。
        status_code: HTTP 状态码。

    Returns:
        脱敏后的错误信息。
    """
    import re

    sanitized = text
    for keyword in ("api_key", "apikey", "authorization", "bearer", "token"):
        if keyword.lower() in sanitized.lower():
            sanitized = re.sub(
                rf"(?i)({keyword})\s*[=:]\s*\S+",
                r"\1=***REDACTED***",
                sanitized,
            )
    return f"HTTP {status_code}: {sanitized[:500]}"


__all__ = [
    "AnthropicConnectivityProbe",
    "ConnectivityProbe",
    "ConnectivityResult",
    "LlamaCppConnectivityProbe",
    "OllamaConnectivityProbe",
    "OpenAIConnectivityProbe",
    "build_openai_models_url",
    "test_connectivity",
]
