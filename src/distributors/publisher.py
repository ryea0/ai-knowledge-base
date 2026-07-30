"""异步多渠道推送模块。

提供基于 ``aiohttp`` 的异步发布器，将每日知识简报并发推送至各渠道：
    - 飞书 Bot API（``app_id`` + ``app_secret`` -> ``tenant_access_token`` -> 发消息）
    - 飞书 Webhook（卡片消息）

核心组件：
    - :class:`PublishResult` -- 发布结果数据类。
    - :class:`BasePublisher` -- 异步发布器抽象基类。
    - :class:`FeishuPublisher` -- 飞书 Bot API + Webhook 发布器。
    - :func:`publish_daily_digest` -- 统一异步入口，并发发布到所有渠道。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiohttp

from src.distributors.formatter import generate_daily_digest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_FEISHU_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_REQUEST_TIMEOUT = 30  # 秒
_TOKEN_CACHE_TTL = 7000  # 飞书 token 有效期 7200 秒，提前 200 秒刷新

# ---------------------------------------------------------------------------
# PublishResult
# ---------------------------------------------------------------------------


@dataclass
class PublishResult:
    """单次发布结果。

    Attributes:
        channel: 渠道标识（如 ``feishu_bot`` / ``feishu_webhook``）。
        success: 是否推送成功。
        message_id: 成功时返回的消息 ID，失败为 ``None``。
        error: 失败原因，成功为 ``None``。
        attempted_at: 推送尝试时间（ISO 8601 UTC）。
    """

    channel: str
    success: bool
    message_id: str | None = None
    error: str | None = None
    attempted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# ---------------------------------------------------------------------------
# BasePublisher
# ---------------------------------------------------------------------------


class BasePublisher(ABC):
    """异步发布器抽象基类。

    子类须实现 :meth:`send_message` 和 :meth:`send_digest` 方法。
    所有方法均为 ``async``，调用方需在 asyncio 事件循环中使用。

    Args:
        timeout: HTTP 请求超时秒数，默认 30。
    """

    def __init__(self, timeout: int = _REQUEST_TIMEOUT) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """渠道标识名（如 ``feishu_bot`` / ``feishu_webhook``）。"""
        ...

    @abstractmethod
    async def send_message(
        self, content: str | dict[str, Any], **kwargs: Any
    ) -> PublishResult:
        """异步发送单条消息。

        Args:
            content: 消息内容，文本为 ``str``，卡片为 ``dict``。
            **kwargs: 子类特定参数（如 ``receive_id``）。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        ...

    @abstractmethod
    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """异步发送每日简报。

        Args:
            digest: ``generate_daily_digest()`` 返回的多渠道格式 dict。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        ...


# ---------------------------------------------------------------------------
# FeishuPublisher
# ---------------------------------------------------------------------------


class FeishuPublisher(BasePublisher):
    """飞书发布器，支持 Bot API 和 Webhook 两种模式。

    **Bot API 模式**：通过 ``FEISHU_APP_ID`` + ``FEISHU_APP_SECRET`` 获取
    ``tenant_access_token``，调用飞书 IM API 发送 Markdown 消息。

    **Webhook 模式**：通过 ``FEISHU_WEBHOOK_URL`` 直接 POST 卡片消息，
    无需 token，适合简单通知场景。

    两种模式可同时启用，``publish_daily_digest`` 会并发推送。

    Args:
        app_id: 飞书应用 App ID，默认从 ``FEISHU_APP_ID`` 读取。
        app_secret: 飞书应用 App Secret，默认从 ``FEISHU_APP_SECRET`` 读取。
        webhook_url: 飞书 Webhook 地址，默认从 ``FEISHU_WEBHOOK_URL`` 读取。
        receive_id: Bot API 接收者 ID（open_id / user_id / chat_id）。
        timeout: HTTP 请求超时秒数，默认 30。

    Raises:
        ValueError: Bot API 模式下 ``app_id`` / ``app_secret`` 缺失，
            或 Webhook 模式下 ``webhook_url`` 缺失时，
            在实际发送方法中抛出（构造时不抛出，允许部分配置）。
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        webhook_url: str | None = None,
        receive_id: str | None = None,
        timeout: int = _REQUEST_TIMEOUT,
    ) -> None:
        super().__init__(timeout)
        self._app_id = app_id if app_id is not None else os.environ.get("FEISHU_APP_ID", "")
        self._app_secret = (
            app_secret if app_secret is not None else os.environ.get("FEISHU_APP_SECRET", "")
        )
        self._webhook_url = (
            webhook_url if webhook_url is not None else os.environ.get("FEISHU_WEBHOOK_URL", "")
        )
        self._receive_id = receive_id
        self._token: str | None = None
        self._token_expire_at: float = 0.0

    @property
    def channel_name(self) -> str:
        """返回 ``feishu``。"""
        return "feishu"

    # -- Token 管理 ---------------------------------------------------------

    async def _get_tenant_access_token(self, session: aiohttp.ClientSession) -> str:
        """获取飞书 ``tenant_access_token``，带本地缓存。

        Token 有效期 7200 秒，本地缓存提前 200 秒刷新。

        Args:
            session: aiohttp 会话。

        Returns:
            ``tenant_access_token`` 字符串。

        Raises:
            ValueError: ``app_id`` 或 ``app_secret`` 未配置。
            RuntimeError: 飞书 API 返回错误。
        """
        if not self._app_id or not self._app_secret:
            raise ValueError(
                "FeishuPublisher Bot API 模式需要 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )

        if self._token and time.monotonic() < self._token_expire_at:
            return self._token

        payload = {"app_id": self._app_id, "app_secret": self._app_secret}
        try:
            async with session.post(
                _FEISHU_TOKEN_URL, json=payload, timeout=self._timeout
            ) as resp:
                data: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"获取 tenant_access_token 网络错误: {exc}") from exc

        if data.get("code") != 0:
            msg = data.get("msg", "未知错误")
            raise RuntimeError(f"获取 tenant_access_token 失败: {msg}")

        token: str = data.get("tenant_access_token", "")
        if not token:
            raise RuntimeError("tenant_access_token 为空")
        self._token = token
        self._token_expire_at = time.monotonic() + _TOKEN_CACHE_TTL
        logger.info("飞书 tenant_access_token 获取成功")
        return self._token

    # -- Bot API 发送 -------------------------------------------------------

    async def _send_via_bot_api(
        self, content: str, msg_type: str, session: aiohttp.ClientSession
    ) -> PublishResult:
        """通过飞书 Bot API 发送消息。

        Args:
            content: 消息内容字符串（Markdown 文本或 JSON 字符串）。
            msg_type: 消息类型（``text`` / ``interactive`` 等）。
            session: aiohttp 会话。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        attempted_at = datetime.now(UTC).isoformat()

        if not self._receive_id:
            return PublishResult(
                channel="feishu_bot",
                success=False,
                error="Bot API 模式需要 receive_id 参数",
                attempted_at=attempted_at,
            )

        try:
            token = await self._get_tenant_access_token(session)
        except (ValueError, RuntimeError) as exc:
            logger.error("飞书 Bot API 获取 token 失败: %s", exc)
            return PublishResult(
                channel="feishu_bot",
                success=False,
                error=str(exc),
                attempted_at=attempted_at,
            )

        headers = {"Authorization": f"Bearer {token}"}
        params = {"receive_id_type": "open_id"}
        body = {
            "receive_id": self._receive_id,
            "msg_type": msg_type,
            "content": content,
        }

        try:
            async with session.post(
                _FEISHU_MESSAGE_URL,
                headers=headers,
                params=params,
                json=body,
                timeout=self._timeout,
            ) as resp:
                data = await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("飞书 Bot API 发送消息网络错误: %s", exc)
            return PublishResult(
                channel="feishu_bot",
                success=False,
                error=f"网络错误: {exc}",
                attempted_at=attempted_at,
            )

        if data.get("code") != 0:
            msg = data.get("msg", "未知错误")
            logger.error("飞书 Bot API 发送失败: code=%s msg=%s", data.get("code"), msg)
            return PublishResult(
                channel="feishu_bot",
                success=False,
                error=f"飞书 API 错误: {msg}",
                attempted_at=attempted_at,
            )

        message_id = data.get("data", {}).get("message_id")
        logger.info("飞书 Bot API 发送成功: message_id=%s", message_id)
        return PublishResult(
            channel="feishu_bot",
            success=True,
            message_id=message_id,
            attempted_at=attempted_at,
        )

    # -- Webhook 发送 -------------------------------------------------------

    async def _send_via_webhook(
        self, card: dict[str, Any], session: aiohttp.ClientSession
    ) -> PublishResult:
        """通过飞书 Webhook 发送卡片消息。

        Args:
            card: 飞书卡片消息 dict（含 ``msg_type`` 和 ``card`` 键）。
            session: aiohttp 会话。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        attempted_at = datetime.now(UTC).isoformat()

        if not self._webhook_url:
            return PublishResult(
                channel="feishu_webhook",
                success=False,
                error="Webhook 模式需要 FEISHU_WEBHOOK_URL",
                attempted_at=attempted_at,
            )

        try:
            async with session.post(
                self._webhook_url, json=card, timeout=self._timeout
            ) as resp:
                data = await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("飞书 Webhook 发送网络错误: %s", exc)
            return PublishResult(
                channel="feishu_webhook",
                success=False,
                error=f"网络错误: {exc}",
                attempted_at=attempted_at,
            )

        if data.get("code") != 0 and data.get("StatusCode") != 0:
            msg = data.get("msg") or data.get("StatusMessage") or "未知错误"
            logger.error("飞书 Webhook 发送失败: %s", msg)
            return PublishResult(
                channel="feishu_webhook",
                success=False,
                error=f"飞书 Webhook 错误: {msg}",
                attempted_at=attempted_at,
            )

        logger.info("飞书 Webhook 发送成功")
        return PublishResult(
            channel="feishu_webhook",
            success=True,
            attempted_at=attempted_at,
        )

    # -- 公共接口 -----------------------------------------------------------

    async def send_message(
        self, content: str | dict[str, Any], **kwargs: Any
    ) -> PublishResult:
        """异步发送单条消息。

        根据 ``content`` 类型自动选择渠道：
            - ``str`` -> Bot API 发送 Markdown（``msg_type=text``）。
            - ``dict`` -> Webhook 发送卡片（``msg_type=interactive``）。

        Args:
            content: ``str`` 走 Bot API，``dict`` 走 Webhook。
            **kwargs: ``receive_id`` 可覆盖构造时设置的接收者。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        receive_id = kwargs.get("receive_id", self._receive_id)
        old_receive_id = self._receive_id
        if receive_id:
            self._receive_id = receive_id

        try:
            async with aiohttp.ClientSession() as session:
                if isinstance(content, dict):
                    return await self._send_via_webhook(content, session)
                return await self._send_via_bot_api(content, "text", session)
        finally:
            self._receive_id = old_receive_id

    async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
        """异步发送每日简报到飞书。

        优先使用 Webhook 发送卡片消息（含富文本排版）；
        若 Webhook 未配置但 Bot API 可用，则通过 Bot API 发送 Markdown 文本。

        Args:
            digest: ``generate_daily_digest()`` 返回的 dict。

        Returns:
            发布结果 :class:`PublishResult`。
        """
        async with aiohttp.ClientSession() as session:
            feishu_card = digest.get("feishu")
            markdown = digest.get("markdown", "")
            result: PublishResult | None = None

            if self._webhook_url and isinstance(feishu_card, dict):
                result = await self._send_via_webhook(feishu_card, session)
                if result.success:
                    return result
                logger.warning("Webhook 发送失败，尝试 Bot API: %s", result.error)

            if self._app_id and self._app_secret and self._receive_id:
                return await self._send_via_bot_api(markdown, "text", session)

            if result is not None:
                return result

            return PublishResult(
                channel=self.channel_name,
                success=False,
                error="飞书未配置任何可用渠道",
                attempted_at=datetime.now(UTC).isoformat(),
            )


# ---------------------------------------------------------------------------
# publish_daily_digest
# ---------------------------------------------------------------------------


async def publish_daily_digest(
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
    feishu_publisher: FeishuPublisher | None = None,
) -> list[PublishResult]:
    """统一异步入口：生成简报并并发发布到所有渠道。

    调用 :func:`generate_daily_digest` 生成 Markdown / Telegram / 飞书三种格式，
    然后并发推送至所有已配置的渠道。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
        date: 日期字符串 ``YYYY-MM-DD``，``None`` 时默认当天（UTC）。
        top_n: 取前 N 篇，默认 5。
        feishu_publisher: 自定义飞书发布器实例，``None`` 时从环境变量构造。

    Returns:
        各渠道发布结果列表 :class:`PublishResult`。
    """
    digest = generate_daily_digest(
        knowledge_dir=knowledge_dir, date=date, top_n=top_n
    )

    publishers: list[BasePublisher] = []

    if feishu_publisher is None:
        feishu_publisher = FeishuPublisher()
    publishers.append(feishu_publisher)

    tasks = [pub.send_digest(digest) for pub in publishers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    publish_results: list[PublishResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            channel = publishers[i].channel_name
            logger.error("发布到 %s 异常: %s", channel, result)
            publish_results.append(
                PublishResult(
                    channel=channel,
                    success=False,
                    error=str(result),
                    attempted_at=datetime.now(UTC).isoformat(),
                )
            )
        else:
            if isinstance(result, PublishResult):
                publish_results.append(result)

    return publish_results


__all__ = [
    "BasePublisher",
    "FeishuPublisher",
    "PublishResult",
    "publish_daily_digest",
]
