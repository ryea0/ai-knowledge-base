"""鉴权适配器 -- 按 ``auth_type`` 构造统一的 :class:`AuthContext`。

将鉴权逻辑从 ``client.py`` / ``health.py`` / ``service.py`` 三处收拢到单一入口，
按 ``LlmAuthType`` 分派到对应 Adapter，解密凭证并构造 LiteLLM / httpx 可用的参数。

Adapter 列表：
    - :class:`BearerAuthAdapter`  -- ``Authorization: Bearer <key>``
    - :class:`HeaderAuthAdapter`  -- 自定义 header（如 ``x-api-key: <key>``）
    - :class:`NoneAuthAdapter`    -- 无鉴权（Ollama / llama.cpp）
    - :class:`OAuthAuthAdapter`   -- OAuth 换 access_token（二期，预留接口）

设计详见 docs/specs/llm-provider.md §9.3。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.llm.crypto import decrypt
from src.llm.orm import LlmProvider
from src.models.enums import LlmAuthType

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """鉴权后供 LiteLLM / httpx 调用的统一参数。

    由 :func:`build_auth_context` 构造，调用方直接消费此对象，
    无需关心凭证解密或协议差异。

    Attributes:
        api_key: LiteLLM ``api_key`` 参数（bearer / oauth）。
        api_base: LiteLLM ``api_base`` 参数。
        extra_headers: 自定义 header（header 鉴权）。
        extra_kwargs: 协议特有参数（如 Azure ``api_version``，二期）。
    """

    api_key: str | None = None
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


class AuthAdapter(ABC):
    """鉴权适配器抽象基类（策略模式）。

    每个子类对应一种 :class:`LlmAuthType`，负责解密凭证并构造
    :class:`AuthContext`。
    """

    @abstractmethod
    def build(self, provider: LlmProvider) -> AuthContext:
        """构造鉴权上下文。

        Args:
            provider: 供应商 ORM 对象（含加密凭证列）。

        Returns:
            :class:`AuthContext` 实例。
        """


class BearerAuthAdapter(AuthAdapter):
    """Bearer Token 鉴权适配器。

    解密 ``api_key_encrypted``，填入 ``AuthContext.api_key``。
    LiteLLM 会自动构造 ``Authorization: Bearer <key>`` header。
    """

    def build(self, provider: LlmProvider) -> AuthContext:
        api_key: str | None = None
        if provider.api_key_encrypted:
            api_key = decrypt(provider.api_key_encrypted)
        return AuthContext(
            api_key=api_key,
            api_base=provider.base_url,
        )


class HeaderAuthAdapter(AuthAdapter):
    """自定义 Header 鉴权适配器。

    解密 ``api_key_encrypted``，填入 ``AuthContext.extra_headers``，
    header 名取自 ``provider.header_name``。
    """

    def build(self, provider: LlmProvider) -> AuthContext:
        if not provider.api_key_encrypted:
            return AuthContext(api_base=provider.base_url)

        plaintext = decrypt(provider.api_key_encrypted)
        header_name = provider.header_name or "x-api-key"
        return AuthContext(
            api_base=provider.base_url,
            extra_headers={header_name: plaintext},
        )


class NoneAuthAdapter(AuthAdapter):
    """无鉴权适配器（Ollama / llama.cpp）。

    仅设置 ``api_base``，不携带任何凭证。
    """

    def build(self, provider: LlmProvider) -> AuthContext:
        return AuthContext(api_base=provider.base_url)


class OAuthAuthAdapter(AuthAdapter):
    """OAuth 鉴权适配器（二期）。

    用 ``api_key`` + ``secret_key`` 向 ``token_url`` 换取 access_token，
    带模块级缓存避免重复请求。

    一期无 oauth 类型供应商，此处仅预留接口，调用时抛 ``NotImplementedError``。
    """

    def build(self, provider: LlmProvider) -> AuthContext:
        raise NotImplementedError(
            "OAuth 鉴权适配器尚未实现（二期功能），"
            "当前无 oauth 类型供应商"
        )


_ADAPTERS: dict[LlmAuthType, AuthAdapter] = {
    LlmAuthType.BEARER: BearerAuthAdapter(),
    LlmAuthType.HEADER: HeaderAuthAdapter(),
    LlmAuthType.NONE: NoneAuthAdapter(),
    LlmAuthType.OAUTH: OAuthAuthAdapter(),
}


def build_auth_context(provider: LlmProvider) -> AuthContext:
    """根据供应商的 ``auth_type`` 构造鉴权上下文（唯一入口）。

    适配逻辑：

    +----------+----------------------------------------------------------+
    | auth_type| 构造逻辑                                                 |
    +==========+==========================================================+
    | none     | ``AuthContext(api_base=provider.base_url)``              |
    +----------+----------------------------------------------------------+
    | bearer   | decrypt(api_key_encrypted) -> api_key + api_base        |
    +----------+----------------------------------------------------------+
    | header   | decrypt(api_key_encrypted) -> extra_headers + api_base   |
    +----------+----------------------------------------------------------+
    | oauth    | 二期实现，当前抛 NotImplementedError                      |
    +----------+----------------------------------------------------------+

    Args:
        provider: 供应商 ORM 对象。

    Returns:
        :class:`AuthContext` 实例。

    Raises:
        ValueError: 凭证解密失败。
        NotImplementedError: auth_type 为 oauth（二期功能）。
    """
    adapter = _ADAPTERS.get(provider.auth_type)
    if adapter is None:
        logger.warning(
            "未知 auth_type=%s，回退到 none 适配器",
            provider.auth_type,
        )
        adapter = _ADAPTERS[LlmAuthType.NONE]

    ctx = adapter.build(provider)
    auth_type_name = (
        provider.auth_type.name.lower()
        if hasattr(provider.auth_type, "name")
        else str(provider.auth_type)
    )
    logger.debug(
        "构造鉴权上下文: provider=%s auth_type=%s has_key=%s has_headers=%s",
        provider.provider_code,
        auth_type_name,
        ctx.api_key is not None,
        ctx.extra_headers is not None,
    )
    return ctx


def build_httpx_headers(ctx: AuthContext) -> dict[str, str]:
    """从 :class:`AuthContext` 提取 httpx 请求 headers。

    用于 ``discover_models`` / ``check_model_health`` 等直接调用
    httpx 的场景（非 LiteLLM 调用）。

    - bearer: 返回 ``{"Authorization": "Bearer <key>", "Accept": "application/json"}``
    - header: 返回 ``{<header_name>: <key>, "Accept": "application/json"}``
    - none:  仅返回 ``{"Accept": "application/json"}``

    Args:
        ctx: 鉴权上下文。

    Returns:
        httpx headers 字典。
    """
    headers: dict[str, str] = {"Accept": "application/json"}

    if ctx.api_key:
        headers["Authorization"] = f"Bearer {ctx.api_key}"

    if ctx.extra_headers:
        headers.update(ctx.extra_headers)

    return headers


__all__ = [
    "AuthAdapter",
    "AuthContext",
    "BearerAuthAdapter",
    "HeaderAuthAdapter",
    "NoneAuthAdapter",
    "OAuthAuthAdapter",
    "build_auth_context",
    "build_httpx_headers",
]
