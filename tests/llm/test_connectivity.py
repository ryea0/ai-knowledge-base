"""src.llm.connectivity 的单元测试。

测试覆盖：
- OpenAIConnectivityProbe: GET {base_url}/models, Bearer Token
- AnthropicConnectivityProbe: GET {base_url}/models, x-api-key + anthropic-version
- OllamaConnectivityProbe: GET {base_url}/api/tags, 无认证
- test_connectivity: 按 litellm_provider 分派到正确探测器
- 未知协议族回退到 OpenAI 探测
- HTTP 错误 / 超时 / 网络异常处理
- ConnectivityResult 字段正确性
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.connectivity import (
    ANTHROPIC_API_VERSION,
    AnthropicConnectivityProbe,
    ConnectivityResult,
    LlamaCppConnectivityProbe,
    OllamaConnectivityProbe,
    OpenAIConnectivityProbe,
    build_openai_models_url,
)
from src.llm.connectivity import test_connectivity as run_connectivity_test
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
    litellm_provider: str = "openai",
    auth_type: LlmAuthType = LlmAuthType.BEARER,
    base_url: str = "https://api.example.com/v1",
    api_key_encrypted: str | None = None,
    header_name: str | None = None,
) -> LlmProvider:
    """创建测试用供应商。"""
    provider = LlmProvider(
        provider_code="test",
        display_name="Test",
        provider_type=LlmProviderType.CLOUD,
        base_url=base_url,
        litellm_provider=litellm_provider,
        auth_type=auth_type,
        api_key_encrypted=api_key_encrypted,
        header_name=header_name,
        timeout_seconds=10,
    )
    session.add(provider)
    session.flush()
    return provider


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
) -> MagicMock:
    """构造 mock httpx.Response。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or ""
    resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# OpenAIConnectivityProbe
# ---------------------------------------------------------------------------


class TestOpenAIConnectivityProbe:
    """OpenAI 兼容协议探测测试。"""

    @patch("src.llm.connectivity.httpx")
    def test_success_with_bearer(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """Bearer Token 鉴权，GET /models 成功。"""
        mock_httpx.get.return_value = _mock_response(200, {"data": []})
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            api_key_encrypted=encrypt("sk-test"),
        )
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is True
        assert result.status_code == 200
        assert result.latency_ms is not None
        assert result.error is None
        assert result.endpoint == "https://api.example.com/v1/models"

        # 验证 Bearer header
        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"

    @patch("src.llm.connectivity.httpx")
    def test_success_without_key(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """无 API Key 时不发送 Authorization header（llamacpp 等 none 鉴权）。"""
        mock_httpx.get.return_value = _mock_response(200, {"data": []})
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            auth_type=LlmAuthType.NONE,
            api_key_encrypted=None,
        )
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is True

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "Authorization" not in headers

    @patch("src.llm.connectivity.httpx")
    def test_http_error(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """HTTP 4xx/5xx 返回失败结果。"""
        mock_httpx.get.return_value = _mock_response(
            401, text='{"error": "invalid api key"}'
        )
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            api_key_encrypted=encrypt("sk-test"),
        )
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is False
        assert result.status_code == 401
        assert "HTTP 401" in result.error

    @patch("src.llm.connectivity.httpx")
    def test_timeout(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """请求超时返回失败结果。"""
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError
        mock_httpx.get.side_effect = httpx.TimeoutException("timed out")

        provider = _make_provider(session)
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is False
        assert result.status_code is None
        assert "超时" in result.error

    @patch("src.llm.connectivity.httpx")
    def test_network_error(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """网络异常返回失败结果。"""
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError
        mock_httpx.get.side_effect = httpx.ConnectError("connection refused")

        provider = _make_provider(session)
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is False
        assert result.status_code is None
        assert "网络错误" in result.error

    @patch("src.llm.connectivity.httpx")
    def test_url_construction(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """验证 URL 拼接正确（base_url 末尾 / 被移除）。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            base_url="https://api.example.com/v1/",
        )
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.endpoint == "https://api.example.com/v1/models"

    @patch("src.llm.connectivity.httpx")
    def test_url_auto_inserts_v1(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """base_url 缺 /v1 时自动补全。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            base_url="https://dashscope.aliyuncs.com/compatible-mode",
        )
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.endpoint == (
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
        )


# ---------------------------------------------------------------------------
# AnthropicConnectivityProbe
# ---------------------------------------------------------------------------


class TestAnthropicConnectivityProbe:
    """Anthropic 协议探测测试。"""

    @patch("src.llm.connectivity.httpx")
    def test_success_with_header_auth(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """header 鉴权：x-api-key + anthropic-version。"""
        mock_httpx.get.return_value = _mock_response(200, {"data": []})
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="anthropic",
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=encrypt("sk-ant-test"),
            header_name="x-api-key",
            base_url="https://api.anthropic.com/v1",
        )
        probe = AnthropicConnectivityProbe()
        result = probe.test(provider)

        assert result.success is True
        assert result.endpoint == "https://api.anthropic.com/v1/models"

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == ANTHROPIC_API_VERSION

    @patch("src.llm.connectivity.httpx")
    def test_anthropic_version_header(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """始终包含 anthropic-version header。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="anthropic",
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=encrypt("sk-test"),
            header_name="x-api-key",
        )
        probe = AnthropicConnectivityProbe()
        probe.test(provider)

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["anthropic-version"] == "2023-06-01"

    @patch("src.llm.connectivity.httpx")
    def test_no_bearer_for_anthropic(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """Anthropic 不使用 Authorization: Bearer，使用 x-api-key。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="anthropic",
            auth_type=LlmAuthType.BEARER,
            api_key_encrypted=encrypt("sk-test"),
        )
        probe = AnthropicConnectivityProbe()
        probe.test(provider)

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        # bearer auth_type 时，ctx.api_key 有值，应填入 x-api-key 而非 Authorization
        assert "Authorization" not in headers
        assert headers["x-api-key"] == "sk-test"


# ---------------------------------------------------------------------------
# OllamaConnectivityProbe
# ---------------------------------------------------------------------------


class TestOllamaConnectivityProbe:
    """Ollama 协议探测测试。"""

    @patch("src.llm.connectivity.httpx")
    def test_success_no_auth(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """无认证，GET /api/tags 成功。"""
        mock_httpx.get.return_value = _mock_response(
            200, {"models": [{"name": "llama3.2"}]}
        )
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="ollama",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:11434",
        )
        probe = OllamaConnectivityProbe()
        result = probe.test(provider)

        assert result.success is True
        assert result.endpoint == "http://localhost:11434/api/tags"

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "Authorization" not in headers
        assert "x-api-key" not in headers

    @patch("src.llm.connectivity.httpx")
    def test_url_construction(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """Ollama URL 拼接为 /api/tags 而非 /models。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="ollama",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:11434/",
        )
        probe = OllamaConnectivityProbe()
        result = probe.test(provider)

        assert result.endpoint == "http://localhost:11434/api/tags"


# ---------------------------------------------------------------------------
# test_connectivity 分派逻辑
# ---------------------------------------------------------------------------


class TestTestConnectivity:
    """test_connectivity 分派逻辑测试。"""

    @patch("src.llm.connectivity.httpx")
    def test_dispatch_openai(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """litellm_provider=openai 分派到 OpenAIConnectivityProbe。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="openai",
            api_key_encrypted=encrypt("sk-test"),
        )
        result = run_connectivity_test(provider)

        assert result.success is True
        assert result.endpoint.endswith("/models")

    @patch("src.llm.connectivity.httpx")
    def test_dispatch_anthropic(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """litellm_provider=anthropic 分派到 AnthropicConnectivityProbe。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="anthropic",
            auth_type=LlmAuthType.HEADER,
            api_key_encrypted=encrypt("sk-test"),
            header_name="x-api-key",
        )
        result = run_connectivity_test(provider)

        assert result.success is True

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "anthropic-version" in headers

    @patch("src.llm.connectivity.httpx")
    def test_dispatch_ollama(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """litellm_provider=ollama 分派到 OllamaConnectivityProbe。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="ollama",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:11434",
        )
        result = run_connectivity_test(provider)

        assert result.success is True
        assert result.endpoint.endswith("/api/tags")

    @patch("src.llm.connectivity.httpx")
    def test_unknown_protocol_fallback(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """未知 litellm_provider 回退到 OpenAI 兼容探测。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="gemini",
            api_key_encrypted=encrypt("sk-test"),
        )
        result = run_connectivity_test(provider)

        assert result.success is True
        assert result.endpoint.endswith("/models")


# ---------------------------------------------------------------------------
# ConnectivityResult
# ---------------------------------------------------------------------------


class TestConnectivityResult:
    """ConnectivityResult 数据类测试。"""

    def test_success_fields(self) -> None:
        """成功结果的字段。"""
        result = ConnectivityResult(
            success=True,
            latency_ms=42,
            status_code=200,
            error=None,
            endpoint="https://api.example.com/v1/models",
        )
        assert result.success is True
        assert result.latency_ms == 42
        assert result.status_code == 200
        assert result.error is None

    def test_failure_fields(self) -> None:
        """失败结果的字段。"""
        result = ConnectivityResult(
            success=False,
            latency_ms=None,
            status_code=None,
            error="网络错误: connection refused",
            endpoint="http://localhost:11434/api/tags",
        )
        assert result.success is False
        assert result.latency_ms is None
        assert result.status_code is None
        assert "网络错误" in result.error

    @patch("src.llm.connectivity.httpx")
    def test_error_sanitized(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """错误信息中的 API Key 被脱敏。"""
        mock_httpx.get.return_value = _mock_response(
            401, text='{"error": "invalid api_key=sk-secret123"}'
        )
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(session)
        probe = OpenAIConnectivityProbe()
        result = probe.test(provider)

        assert result.success is False
        assert "sk-secret123" not in result.error
        assert "REDACTED" in result.error


# ---------------------------------------------------------------------------
# LlamaCppConnectivityProbe
# ---------------------------------------------------------------------------


class TestLlamaCppConnectivityProbe:
    """llama.cpp 协议探测测试。"""

    @patch("src.llm.connectivity.httpx")
    def test_success_no_auth(self, mock_httpx: MagicMock, session: Session) -> None:
        """无认证，GET /v1/models 成功。"""
        mock_httpx.get.return_value = _mock_response(200, {"data": []})
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="llamacpp",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:8080/v1",
        )
        probe = LlamaCppConnectivityProbe()
        result = probe.test(provider)

        assert result.success is True
        assert result.endpoint == "http://localhost:8080/v1/models"

        call_kwargs = mock_httpx.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "Authorization" not in headers
        assert "x-api-key" not in headers

    @patch("src.llm.connectivity.httpx")
    def test_url_auto_inserts_v1(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """base_url 缺 /v1 时自动补全。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="llamacpp",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:8080",
        )
        probe = LlamaCppConnectivityProbe()
        result = probe.test(provider)

        assert result.endpoint == "http://localhost:8080/v1/models"

    @patch("src.llm.connectivity.httpx")
    def test_dispatch_llamacpp(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """litellm_provider=llamacpp 分派到 LlamaCppConnectivityProbe。"""
        mock_httpx.get.return_value = _mock_response(200)
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        provider = _make_provider(
            session,
            litellm_provider="llamacpp",
            auth_type=LlmAuthType.NONE,
            base_url="http://localhost:8080/v1",
        )
        result = run_connectivity_test(provider)

        assert result.success is True
        assert result.endpoint.endswith("/models")


# ---------------------------------------------------------------------------
# build_openai_models_url
# ---------------------------------------------------------------------------


class TestBuildOpenaiModelsUrl:
    """build_openai_models_url URL 拼接测试。"""

    @pytest.mark.parametrize(
        ("base_url", "expected"),
        [
            # 含 /v1，直接追加
            ("https://api.openai.com/v1", "https://api.openai.com/v1/models"),
            # 末尾 / 被移除
            ("https://api.openai.com/v1/", "https://api.openai.com/v1/models"),
            # 缺 /v1，自动补
            ("https://api.deepseek.com", "https://api.deepseek.com/v1/models"),
            # Qwen compatible-mode 缺 /v1
            (
                "https://dashscope.aliyuncs.com/compatible-mode",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            ),
            # Qwen compatible-mode 含 /v1
            (
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            ),
            # ark 含 /api/v3，不补 /v1
            (
                "https://ark.cn-beijing.volces.com/api/v3",
                "https://ark.cn-beijing.volces.com/api/v3/models",
            ),
            # 本地 llama.cpp 含 /v1
            ("http://localhost:8080/v1", "http://localhost:8080/v1/models"),
            # 本地 llama.cpp 缺 /v1
            ("http://localhost:8080", "http://localhost:8080/v1/models"),
            # ollama OpenAI 兼容端口含 /v1
            ("http://localhost:11434/v1", "http://localhost:11434/v1/models"),
        ],
    )
    def test_url_construction(self, base_url: str, expected: str) -> None:
        """各类 base_url 正确拼接为 /models 端点。"""
        assert build_openai_models_url(base_url) == expected

    def test_missing_v1_auto_inserted(self) -> None:
        """缺版本段时自动补 /v1。"""
        url = build_openai_models_url("https://api.deepseek.com")
        assert "/v1/models" in url

    def test_existing_v3_not_doubled(self) -> None:
        """已含 /api/v3 时不重复追加 /v1。"""
        url = build_openai_models_url("https://ark.cn-beijing.volces.com/api/v3")
        assert url == "https://ark.cn-beijing.volces.com/api/v3/models"
        assert "/v1" not in url.split("/api/v3")[1]
