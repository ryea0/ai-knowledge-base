"""src.llm.auth_adapter 的单元测试。

测试覆盖：
- BearerAuthAdapter: 解密 api_key_encrypted -> AuthContext.api_key
- HeaderAuthAdapter: 解密 api_key_encrypted -> AuthContext.extra_headers
- NoneAuthAdapter: 仅设置 api_base
- OAuthAuthAdapter: 抛 NotImplementedError（二期）
- build_auth_context: 按 auth_type 分派到正确 adapter
- build_httpx_headers: 从 AuthContext 提取 httpx headers
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.auth_adapter import (
    AuthContext,
    BearerAuthAdapter,
    HeaderAuthAdapter,
    NoneAuthAdapter,
    OAuthAuthAdapter,
    build_auth_context,
    build_httpx_headers,
)
from src.llm.crypto import encrypt
from src.llm.orm import Base, LlmProvider
from src.models.enums import LlmAuthType, LlmProviderType


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """设置加密所需的环境变量。"""
    monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")


def _make_provider(
    session: Session,
    *,
    auth_type: LlmAuthType = LlmAuthType.BEARER,
    api_key_encrypted: str | None = None,
    secret_key_encrypted: str | None = None,
    header_name: str | None = None,
    token_url: str | None = None,
) -> LlmProvider:
    """创建测试用供应商。"""
    provider = LlmProvider(
        provider_code="test",
        display_name="Test",
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com",
        litellm_provider="openai",
        auth_type=auth_type,
        api_key_encrypted=api_key_encrypted,
        secret_key_encrypted=secret_key_encrypted,
        header_name=header_name,
        token_url=token_url,
    )
    session.add(provider)
    session.flush()
    return provider


class TestBearerAuthAdapter:
    """BearerAuthAdapter 测试。"""

    def test_build_with_key(self, session: Session) -> None:
        """有加密 key 时解密并填入 api_key。"""
        enc = encrypt("sk-secret")
        provider = _make_provider(
            session, api_key_encrypted=enc
        )
        adapter = BearerAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.api_key == "sk-secret"
        assert ctx.api_base == "https://api.example.com"
        assert ctx.extra_headers is None

    def test_build_without_key(self, session: Session) -> None:
        """无加密 key 时 api_key 为 None。"""
        provider = _make_provider(session, api_key_encrypted=None)
        adapter = BearerAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.api_key is None
        assert ctx.api_base == "https://api.example.com"


class TestHeaderAuthAdapter:
    """HeaderAuthAdapter 测试。"""

    def test_build_with_header_name(self, session: Session) -> None:
        """解密 key 并填入 extra_headers。"""
        enc = encrypt("sk-secret")
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=enc,
            header_name="x-api-key",
        )
        adapter = HeaderAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.api_key is None
        assert ctx.api_base == "https://api.example.com"
        assert ctx.extra_headers == {"x-api-key": "sk-secret"}

    def test_build_default_header_name(self, session: Session) -> None:
        """header_name 为 None 时回退到 x-api-key。"""
        enc = encrypt("sk-secret")
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=enc,
            header_name=None,
        )
        adapter = HeaderAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.extra_headers == {"x-api-key": "sk-secret"}

    def test_build_without_key(self, session: Session) -> None:
        """无加密 key 时 extra_headers 为 None。"""
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=None,
        )
        adapter = HeaderAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.extra_headers is None
        assert ctx.api_base == "https://api.example.com"


class TestNoneAuthAdapter:
    """NoneAuthAdapter 测试。"""

    def test_build(self, session: Session) -> None:
        """仅设置 api_base。"""
        provider = _make_provider(
            session, auth_type=LlmAuthType.NONE
        )
        adapter = NoneAuthAdapter()
        ctx = adapter.build(provider)

        assert ctx.api_key is None
        assert ctx.api_base == "https://api.example.com"
        assert ctx.extra_headers is None


class TestOAuthAuthAdapter:
    """OAuthAuthAdapter 测试（二期，预留接口）。"""

    def test_raises_not_implemented(self, session: Session) -> None:
        """oauth 类型抛 NotImplementedError。"""
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.OAUTH,
            api_key_encrypted=encrypt("key"),
            secret_key_encrypted=encrypt("secret"),
            token_url="https://oauth.example.com/token",
        )
        adapter = OAuthAuthAdapter()
        with pytest.raises(NotImplementedError):
            adapter.build(provider)


class TestBuildAuthContext:
    """build_auth_context 分派逻辑测试。"""

    def test_bearer(self, session: Session) -> None:
        """bearer 类型分派到 BearerAuthAdapter。"""
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.BEARER,
            api_key_encrypted=encrypt("sk-test"),
        )
        ctx = build_auth_context(provider)

        assert ctx.api_key == "sk-test"
        assert ctx.api_base == "https://api.example.com"

    def test_header(self, session: Session) -> None:
        """header 类型分派到 HeaderAuthAdapter。"""
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=encrypt("sk-test"),
            header_name="x-custom",
        )
        ctx = build_auth_context(provider)

        assert ctx.extra_headers == {"x-custom": "sk-test"}
        assert ctx.api_key is None

    def test_none(self, session: Session) -> None:
        """none 类型分派到 NoneAuthAdapter。"""
        provider = _make_provider(
            session, auth_type=LlmAuthType.NONE
        )
        ctx = build_auth_context(provider)

        assert ctx.api_key is None
        assert ctx.api_base == "https://api.example.com"

    def test_oauth_raises(self, session: Session) -> None:
        """oauth 类型抛 NotImplementedError。"""
        provider = _make_provider(
            session,
            auth_type=LlmAuthType.OAUTH,
            api_key_encrypted=encrypt("key"),
            secret_key_encrypted=encrypt("secret"),
            token_url="https://oauth.example.com/token",
        )
        with pytest.raises(NotImplementedError):
            build_auth_context(provider)


class TestBuildHttpxHeaders:
    """build_httpx_headers 测试。"""

    def test_bearer_headers(self) -> None:
        """bearer 类型生成 Authorization header。"""
        ctx = AuthContext(api_key="sk-test")
        headers = build_httpx_headers(ctx)

        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Accept"] == "application/json"

    def test_header_auth_headers(self) -> None:
        """header 类型生成自定义 header。"""
        ctx = AuthContext(
            extra_headers={"x-api-key": "sk-test"}
        )
        headers = build_httpx_headers(ctx)

        assert headers["x-api-key"] == "sk-test"
        assert "Authorization" not in headers

    def test_none_headers(self) -> None:
        """none 类型仅 Accept header。"""
        ctx = AuthContext()
        headers = build_httpx_headers(ctx)

        assert headers == {"Accept": "application/json"}

    def test_combined_headers(self) -> None:
        """api_key + extra_headers 同时存在时都包含。"""
        ctx = AuthContext(
            api_key="sk-test",
            extra_headers={"x-custom": "val"},
        )
        headers = build_httpx_headers(ctx)

        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["x-custom"] == "val"
