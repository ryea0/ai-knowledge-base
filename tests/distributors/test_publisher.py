"""src.distributors.publisher 的单元测试。

测试覆盖：
    - PublishResult 数据类
    - BasePublisher 抽象基类
    - FeishuPublisher token 管理 / Bot API / Webhook 发送
    - publish_daily_digest 统一入口
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.distributors.publisher import (
    BasePublisher,
    FeishuPublisher,
    PublishResult,
    publish_daily_digest,
)

# ---------------------------------------------------------------------------
# PublishResult
# ---------------------------------------------------------------------------


class TestPublishResult:
    """PublishResult 数据类测试。"""

    def test_success_result(self) -> None:
        """成功结果包含 channel / success / message_id。"""
        result = PublishResult(
            channel="feishu_bot",
            success=True,
            message_id="om_123456",
        )
        assert result.channel == "feishu_bot"
        assert result.success is True
        assert result.message_id == "om_123456"
        assert result.error is None
        assert result.attempted_at != ""

    def test_failure_result(self) -> None:
        """失败结果包含 error，message_id 为 None。"""
        result = PublishResult(
            channel="feishu_webhook",
            success=False,
            error="网络超时",
        )
        assert result.success is False
        assert result.error == "网络超时"
        assert result.message_id is None

    def test_default_attempted_at(self) -> None:
        """attempted_at 自动填充当前时间。"""
        result = PublishResult(channel="test", success=True)
        assert len(result.attempted_at) > 10


# ---------------------------------------------------------------------------
# BasePublisher
# ---------------------------------------------------------------------------


class TestBasePublisher:
    """BasePublisher 抽象基类测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """BasePublisher 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            BasePublisher()  # type: ignore[abstract]

    def test_subclass_must_implement_abstract_methods(self) -> None:
        """子类未实现所有抽象方法不能实例化。"""

        class IncompletePublisher(BasePublisher):
            pass

        with pytest.raises(TypeError):
            IncompletePublisher()  # type: ignore[abstract]

    def test_concrete_subclass_works(self) -> None:
        """完整实现的子类可正常实例化。"""

        class DummyPublisher(BasePublisher):
            @property
            def channel_name(self) -> str:
                return "dummy"

            async def send_message(
                self, content: str | dict[str, Any], **kwargs: Any
            ) -> PublishResult:
                return PublishResult(channel=self.channel_name, success=True)

            async def send_digest(self, digest: dict[str, Any]) -> PublishResult:
                return PublishResult(channel=self.channel_name, success=True)

        pub = DummyPublisher()
        assert pub.channel_name == "dummy"


# ---------------------------------------------------------------------------
# FeishuPublisher -- 辅助 mock 构造
# ---------------------------------------------------------------------------


def _mock_response(data: dict[str, Any]) -> MagicMock:
    """构造模拟的 aiohttp 响应上下文管理器。"""
    mock_resp = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_resp.json = AsyncMock(return_value=data)
    return mock_resp


def _mock_session(mock_post: MagicMock) -> MagicMock:
    """构造模拟的 aiohttp.ClientSession。"""
    session = MagicMock()
    session.post = mock_post
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


# ---------------------------------------------------------------------------
# FeishuPublisher -- token 管理
# ---------------------------------------------------------------------------


class TestFeishuToken:
    """FeishuPublisher token 管理测试。"""

    @pytest.mark.asyncio
    async def test_get_token_success(self) -> None:
        """成功获取 tenant_access_token。"""
        publisher = FeishuPublisher(
            app_id="cli_test", app_secret="secret_test", webhook_url=""
        )
        mock_post = MagicMock(return_value=_mock_response({
            "code": 0,
            "tenant_access_token": "t-xxx",
        }))
        session = _mock_session(mock_post)

        token = await publisher._get_tenant_access_token(session)  # type: ignore[report-private-use]
        assert token == "t-xxx"
        assert publisher._token == "t-xxx"

    @pytest.mark.asyncio
    async def test_get_token_missing_credentials(self) -> None:
        """app_id 或 app_secret 未配置时抛 ValueError。"""
        publisher = FeishuPublisher(app_id="", app_secret="", webhook_url="")
        session = _mock_session(MagicMock())

        with pytest.raises(ValueError, match="FEISHU_APP_ID"):
            await publisher._get_tenant_access_token(session)  # type: ignore[report-private-use]

    @pytest.mark.asyncio
    async def test_get_token_api_error(self) -> None:
        """飞书 API 返回错误时抛 RuntimeError。"""
        publisher = FeishuPublisher(
            app_id="cli_test", app_secret="secret_test", webhook_url=""
        )
        mock_post = MagicMock(return_value=_mock_response({
            "code": 99991663,
            "msg": "app_id or app_secret is invalid",
        }))
        session = _mock_session(mock_post)

        with pytest.raises(RuntimeError, match="app_id or app_secret"):
            await publisher._get_tenant_access_token(session)  # type: ignore[report-private-use]

    @pytest.mark.asyncio
    async def test_token_cache_reuse(self) -> None:
        """token 未过期时复用缓存，不重复请求。"""
        publisher = FeishuPublisher(
            app_id="cli_test", app_secret="secret_test", webhook_url=""
        )
        publisher._token = "cached-token"
        publisher._token_expire_at = time.monotonic() + 1000

        mock_post = MagicMock()
        session = _mock_session(mock_post)

        token = await publisher._get_tenant_access_token(session)  # type: ignore[report-private-use]
        assert token == "cached-token"
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# FeishuPublisher -- Bot API 发送
# ---------------------------------------------------------------------------


class TestFeishuBotAPI:
    """FeishuPublisher Bot API 模式测试。"""

    @pytest.mark.asyncio
    async def test_send_via_bot_api_success(self) -> None:
        """Bot API 发送成功返回 message_id。"""
        publisher = FeishuPublisher(
            app_id="cli_test",
            app_secret="secret_test",
            webhook_url="",
            receive_id="ou_test",
        )
        token_resp = _mock_response({"code": 0, "tenant_access_token": "t-xxx"})
        msg_resp = _mock_response({
            "code": 0,
            "data": {"message_id": "om_123"},
        })
        mock_post = MagicMock(side_effect=[token_resp, msg_resp])
        session = _mock_session(mock_post)

        result = await publisher._send_via_bot_api(  # type: ignore[report-private-use]
            "hello", "text", session
        )
        assert result.success is True
        assert result.message_id == "om_123"
        assert result.channel == "feishu_bot"

    @pytest.mark.asyncio
    async def test_send_via_bot_api_no_receive_id(self) -> None:
        """未设置 receive_id 时返回失败结果。"""
        publisher = FeishuPublisher(
            app_id="cli_test", app_secret="secret_test", webhook_url=""
        )
        session = _mock_session(MagicMock())

        result = await publisher._send_via_bot_api(  # type: ignore[report-private-use]
            "hello", "text", session
        )
        assert result.success is False
        assert "receive_id" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_via_bot_api_token_failure(self) -> None:
        """token 获取失败时返回失败结果（非抛异常）。"""
        publisher = FeishuPublisher(
            app_id="bad", app_secret="bad", webhook_url="", receive_id="ou_test"
        )
        mock_post = MagicMock(return_value=_mock_response({
            "code": 99991663,
            "msg": "invalid",
        }))
        session = _mock_session(mock_post)

        result = await publisher._send_via_bot_api(  # type: ignore[report-private-use]
            "hello", "text", session
        )
        assert result.success is False
        assert "invalid" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_via_bot_api_api_error(self) -> None:
        """飞书 IM API 返回业务错误。"""
        publisher = FeishuPublisher(
            app_id="cli_test",
            app_secret="secret_test",
            webhook_url="",
            receive_id="ou_test",
        )
        token_resp = _mock_response({"code": 0, "tenant_access_token": "t-xxx"})
        msg_resp = _mock_response({"code": 230002, "msg": "user not found"})
        mock_post = MagicMock(side_effect=[token_resp, msg_resp])
        session = _mock_session(mock_post)

        result = await publisher._send_via_bot_api(  # type: ignore[report-private-use]
            "hello", "text", session
        )
        assert result.success is False
        assert "user not found" in (result.error or "")


# ---------------------------------------------------------------------------
# FeishuPublisher -- Webhook 发送
# ---------------------------------------------------------------------------


class TestFeishuWebhook:
    """FeishuPublisher Webhook 模式测试。"""

    @pytest.mark.asyncio
    async def test_send_via_webhook_success(self) -> None:
        """Webhook 发送卡片成功。"""
        publisher = FeishuPublisher(webhook_url="https://open.feishu.cn/dummy")
        card = {"msg_type": "interactive", "card": {"elements": []}}
        mock_post = MagicMock(return_value=_mock_response({
            "code": 0,
            "msg": "success",
        }))
        session = _mock_session(mock_post)

        result = await publisher._send_via_webhook(card, session)  # type: ignore[report-private-use]
        assert result.success is True
        assert result.channel == "feishu_webhook"

    @pytest.mark.asyncio
    async def test_send_via_webhook_no_url(self) -> None:
        """未配置 webhook_url 时返回失败结果。"""
        publisher = FeishuPublisher(webhook_url="")
        session = _mock_session(MagicMock())

        result = await publisher._send_via_webhook(  # type: ignore[report-private-use]
            {"msg_type": "interactive"}, session
        )
        assert result.success is False
        assert "FEISHU_WEBHOOK_URL" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_via_webhook_api_error(self) -> None:
        """Webhook 返回业务错误。"""
        publisher = FeishuPublisher(webhook_url="https://open.feishu.cn/dummy")
        mock_post = MagicMock(return_value=_mock_response({
            "code": 19021,
            "msg": "invalid card",
        }))
        session = _mock_session(mock_post)

        result = await publisher._send_via_webhook(  # type: ignore[report-private-use]
            {"msg_type": "interactive"}, session
        )
        assert result.success is False
        assert "invalid card" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_via_webhook_statuscode_success(self) -> None:
        """Webhook 返回 StatusCode=0 也视为成功。"""
        publisher = FeishuPublisher(webhook_url="https://open.feishu.cn/dummy")
        mock_post = MagicMock(return_value=_mock_response({
            "StatusCode": 0,
            "StatusMessage": "success",
        }))
        session = _mock_session(mock_post)

        result = await publisher._send_via_webhook(  # type: ignore[report-private-use]
            {"msg_type": "interactive"}, session
        )
        assert result.success is True


# ---------------------------------------------------------------------------
# FeishuPublisher -- send_message / send_digest 公共接口
# ---------------------------------------------------------------------------


class TestFeishuPublicInterface:
    """FeishuPublisher 公共接口测试。"""

    @pytest.mark.asyncio
    async def test_send_message_str_uses_bot_api(self) -> None:
        """send_message 传 str 走 Bot API。"""
        publisher = FeishuPublisher(
            app_id="cli_test",
            app_secret="secret_test",
            webhook_url="",
            receive_id="ou_test",
        )

        token_resp = _mock_response({"code": 0, "tenant_access_token": "t-xxx"})
        msg_resp = _mock_response({"code": 0, "data": {"message_id": "om_1"}})
        mock_post = MagicMock(side_effect=[token_resp, msg_resp])

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = _mock_session(mock_post)
            result = await publisher.send_message("hello text")

        assert result.success is True
        assert result.channel == "feishu_bot"

    @pytest.mark.asyncio
    async def test_send_message_dict_uses_webhook(self) -> None:
        """send_message 传 dict 走 Webhook。"""
        publisher = FeishuPublisher(webhook_url="https://open.feishu.cn/dummy")

        mock_post = MagicMock(return_value=_mock_response({"code": 0, "msg": "ok"}))

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = _mock_session(mock_post)
            result = await publisher.send_message({"msg_type": "interactive"})

        assert result.success is True
        assert result.channel == "feishu_webhook"

    @pytest.mark.asyncio
    async def test_send_digest_webhook_success(self) -> None:
        """send_digest 优先用 Webhook 发送卡片。"""
        publisher = FeishuPublisher(webhook_url="https://open.feishu.cn/dummy")

        mock_post = MagicMock(return_value=_mock_response({"code": 0, "msg": "ok"}))

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = _mock_session(mock_post)
            digest = {"markdown": "md", "feishu": {"msg_type": "interactive"}}
            result = await publisher.send_digest(digest)

        assert result.success is True
        assert result.channel == "feishu_webhook"

    @pytest.mark.asyncio
    async def test_send_digest_fallback_to_bot_api(self) -> None:
        """Webhook 未配置但 Bot API 可用时，回退到 Bot API。"""
        publisher = FeishuPublisher(
            app_id="cli_test",
            app_secret="secret_test",
            webhook_url="",
            receive_id="ou_test",
        )

        token_resp = _mock_response({"code": 0, "tenant_access_token": "t-xxx"})
        msg_resp = _mock_response({"code": 0, "data": {"message_id": "om_2"}})
        mock_post = MagicMock(side_effect=[token_resp, msg_resp])

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = _mock_session(mock_post)
            digest = {"markdown": "# Digest", "feishu": {"msg_type": "interactive"}}
            result = await publisher.send_digest(digest)

        assert result.success is True
        assert result.channel == "feishu_bot"

    @pytest.mark.asyncio
    async def test_send_digest_no_channel_configured(self) -> None:
        """未配置任何渠道时返回失败。"""
        publisher = FeishuPublisher(app_id="", app_secret="", webhook_url="")

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = _mock_session(MagicMock())
            digest = {"markdown": "# Digest", "feishu": {"msg_type": "interactive"}}
            result = await publisher.send_digest(digest)

        assert result.success is False


# ---------------------------------------------------------------------------
# publish_daily_digest
# ---------------------------------------------------------------------------


class TestPublishDailyDigest:
    """publish_daily_digest 统一入口测试。"""

    @pytest.mark.asyncio
    async def test_publish_returns_results_list(self, tmp_path: Any) -> None:
        """publish_daily_digest 返回 PublishResult 列表。"""
        mock_publisher = AsyncMock(spec=FeishuPublisher)
        mock_publisher.send_digest = AsyncMock(
            return_value=PublishResult(
                channel="feishu_webhook", success=True
            )
        )

        results = await publish_daily_digest(
            knowledge_dir=str(tmp_path),
            feishu_publisher=mock_publisher,
        )

        assert len(results) == 1
        assert results[0].success is True
        mock_publisher.send_digest.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_handles_exception(self, tmp_path: Any) -> None:
        """发布器抛异常时转为失败的 PublishResult。"""
        mock_publisher = AsyncMock(spec=FeishuPublisher)
        mock_publisher.send_digest = AsyncMock(side_effect=RuntimeError("boom"))
        mock_publisher.channel_name = "feishu"

        results = await publish_daily_digest(
            knowledge_dir=str(tmp_path),
            feishu_publisher=mock_publisher,
        )

        assert len(results) == 1
        assert results[0].success is False
        assert "boom" in (results[0].error or "")

    @pytest.mark.asyncio
    async def test_publish_uses_default_publisher(self, tmp_path: Any) -> None:
        """未传入 publisher 时从环境变量构造 FeishuPublisher。"""
        with (
            patch.dict(os.environ, {
                "FEISHU_APP_ID": "",
                "FEISHU_APP_SECRET": "",
                "FEISHU_WEBHOOK_URL": "",
            }),
            patch("aiohttp.ClientSession") as mock_session_cls,
        ):
            mock_session_cls.return_value = _mock_session(MagicMock())
            results = await publish_daily_digest(knowledge_dir=str(tmp_path))

        assert len(results) == 1
        assert results[0].success is False
