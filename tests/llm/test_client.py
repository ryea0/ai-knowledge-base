"""src.llm.client 的单元测试。

测试覆盖：
- sanitize_secrets 脱敏逻辑
- LlmErrorType 枚举完整性
- LlmCallError 异常构造与属性
- _classify_exception 异常映射（各类 LiteLLM 异常 -> LlmErrorType）
- RetryStrategy 各策略子类的 should_retry / max_attempts / backoff_seconds
- RetryPolicyFactory 按错误类型返回正确策略
- chat_completion 异常路径（mock litellm.completion 抛异常 -> LlmCallError）
- chat_completion_with_retry 重试流程（成功/失败/重试耗尽）
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import litellm.exceptions
import pytest

from src.llm.client import (
    LlmCallError,
    LlmErrorType,
    NetworkRetryStrategy,
    NoRetryStrategy,
    RateLimitRetryStrategy,
    RetryPolicyFactory,
    RetryStrategy,
    ServerErrorRetryStrategy,
    TimeoutRetryStrategy,
    _classify_exception,
    chat_completion,
    chat_completion_with_retry,
)
from src.llm.utils import sanitize_secrets
from src.models.enums import LlmAuthType


class TestSanitizeError:
    """sanitize_secrets 脱敏测试。"""

    def test_no_sensitive_data(self) -> None:
        """无敏感数据的消息原样返回。"""
        msg = "Connection timeout to https://api.example.com"
        assert sanitize_secrets(msg) == msg

    def test_redact_api_key(self) -> None:
        """api_key 被脱敏。"""
        msg = "Error: api_key=sk-abc123 is invalid"
        result = sanitize_secrets(msg)
        assert "sk-abc123" not in result
        assert "***REDACTED***" in result

    def test_redact_apikey(self) -> None:
        """apikey 被脱敏。"""
        msg = "apikey: sk-secret-value"
        result = sanitize_secrets(msg)
        assert "sk-secret-value" not in result
        assert "***REDACTED***" in result

    def test_redact_authorization(self) -> None:
        """authorization 被脱敏。"""
        msg = "authorization=Bearer-abc123"
        result = sanitize_secrets(msg)
        assert "Bearer-abc123" not in result
        assert "***REDACTED***" in result

    def test_redact_bearer(self) -> None:
        """bearer 被脱敏。"""
        msg = "bearer=my-secret-token"
        result = sanitize_secrets(msg)
        assert "my-secret-token" not in result
        assert "***REDACTED***" in result

    def test_redact_token(self) -> None:
        """token 被脱敏。"""
        msg = "token=ghp_abcdef123456"
        result = sanitize_secrets(msg)
        assert "ghp_abcdef123456" not in result

    def test_truncation(self) -> None:
        """超长消息截断至 500 字符。"""
        msg = "x" * 600
        result = sanitize_secrets(msg)
        assert len(result) <= 500

    def test_case_insensitive_redaction(self) -> None:
        """大小写不敏感脱敏。"""
        msg = "API_KEY=sk-secret"
        result = sanitize_secrets(msg)
        assert "sk-secret" not in result


class TestLlmErrorType:
    """LlmErrorType 枚举测试。"""

    def test_all_values(self) -> None:
        """枚举值与预期一致。"""
        assert LlmErrorType.TIMEOUT.value == "timeout"
        assert LlmErrorType.AUTH_FAILED.value == "auth_failed"
        assert LlmErrorType.RATE_LIMITED.value == "rate_limited"
        assert LlmErrorType.NETWORK.value == "network"
        assert LlmErrorType.SERVER_ERROR.value == "server_error"
        assert LlmErrorType.CLIENT_ERROR.value == "client_error"
        assert LlmErrorType.UNKNOWN.value == "unknown"

    def test_all_members(self) -> None:
        """共 7 个枚举成员。"""
        assert len(list(LlmErrorType)) == 7


class TestLlmCallError:
    """LlmCallError 异常构造测试。"""

    def test_basic_construction(self) -> None:
        """基本构造与属性。"""
        err = LlmCallError(
            "connection refused",
            provider_code="deepseek",
            model_code="deepseek-chat",
            error_type=LlmErrorType.NETWORK,
        )
        assert str(err) == (
            "[network] provider=deepseek model=deepseek-chat: connection refused"
        )
        assert err.provider_code == "deepseek"
        assert err.model_code == "deepseek-chat"
        assert err.error_type == LlmErrorType.NETWORK

    def test_default_values(self) -> None:
        """默认值为空串和 UNKNOWN。"""
        err = LlmCallError("something went wrong")
        assert err.provider_code == ""
        assert err.model_code == ""
        assert err.error_type == LlmErrorType.UNKNOWN

    def test_str_format(self) -> None:
        """__str__ 包含 error_type 和上下文。"""
        err = LlmCallError(
            "timeout after 30s",
            provider_code="ark",
            model_code="doubao-pro",
            error_type=LlmErrorType.TIMEOUT,
        )
        s = str(err)
        assert "[timeout]" in s
        assert "provider=ark" in s
        assert "model=doubao-pro" in s
        assert "timeout after 30s" in s

    def test_cause_chain(self) -> None:
        """异常链 (from exc) 保留。"""
        original = ValueError("original cause")
        err = LlmCallError(
            "wrapped", error_type=LlmErrorType.UNKNOWN
        )
        err.__cause__ = original
        assert err.__cause__ is original

    def test_is_exception_subclass(self) -> None:
        """LlmCallError 是 Exception 子类。"""
        assert issubclass(LlmCallError, Exception)


# ---------------------------------------------------------------------------
# _classify_exception 测试
# ---------------------------------------------------------------------------

def _make_litellm_exc(
    exc_cls: type[Exception],
    *,
    message: str = "test error",
) -> Exception:
    """构造 LiteLLM 异常实例。

    LiteLLM 异常统一需要 message / model / llm_provider 参数，
    PermissionDeniedError 额外需要 response（httpx.Response）。
    """
    import httpx

    common_kwargs: dict[str, Any] = {
        "message": message,
        "model": "test-model",
        "llm_provider": "test-provider",
    }
    # PermissionDeniedError 需要 response 参数，且 response 须关联 request
    if exc_cls is litellm.exceptions.PermissionDeniedError:
        req = httpx.Request("GET", "https://example.com")
        common_kwargs["response"] = httpx.Response(
            status_code=403, request=req
        )
    try:
        return exc_cls(**common_kwargs)  # type: ignore[call-arg]
    except TypeError:
        # Timeout 的参数顺序不同 (message, model, llm_provider)
        try:
            return exc_cls(message, "test-model", "test-provider")  # type: ignore[call-arg]
        except TypeError:
            return exc_cls(message, "test-model", "test-provider", None)  # type: ignore[call-arg]


class TestClassifyException:
    """_classify_exception 异常映射测试。"""

    def test_timeout(self) -> None:
        """Timeout -> TIMEOUT。"""
        exc = _make_litellm_exc(litellm.exceptions.Timeout)
        assert _classify_exception(exc) == LlmErrorType.TIMEOUT

    def test_authentication_error(self) -> None:
        """AuthenticationError -> AUTH_FAILED。"""
        exc = _make_litellm_exc(litellm.exceptions.AuthenticationError)
        assert _classify_exception(exc) == LlmErrorType.AUTH_FAILED

    def test_rate_limit_error(self) -> None:
        """RateLimitError -> RATE_LIMITED。"""
        exc = _make_litellm_exc(litellm.exceptions.RateLimitError)
        assert _classify_exception(exc) == LlmErrorType.RATE_LIMITED

    def test_internal_server_error(self) -> None:
        """InternalServerError -> SERVER_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.InternalServerError)
        assert _classify_exception(exc) == LlmErrorType.SERVER_ERROR

    def test_service_unavailable_error(self) -> None:
        """ServiceUnavailableError -> SERVER_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.ServiceUnavailableError)
        assert _classify_exception(exc) == LlmErrorType.SERVER_ERROR

    def test_bad_gateway_error(self) -> None:
        """BadGatewayError -> SERVER_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.BadGatewayError)
        assert _classify_exception(exc) == LlmErrorType.SERVER_ERROR

    def test_api_connection_error(self) -> None:
        """APIConnectionError -> NETWORK。"""
        exc = _make_litellm_exc(litellm.exceptions.APIConnectionError)
        assert _classify_exception(exc) == LlmErrorType.NETWORK

    def test_bad_request_error(self) -> None:
        """BadRequestError -> CLIENT_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.BadRequestError)
        assert _classify_exception(exc) == LlmErrorType.CLIENT_ERROR

    def test_not_found_error(self) -> None:
        """NotFoundError -> CLIENT_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.NotFoundError)
        assert _classify_exception(exc) == LlmErrorType.CLIENT_ERROR

    def test_permission_denied_error(self) -> None:
        """PermissionDeniedError -> CLIENT_ERROR。"""
        exc = _make_litellm_exc(litellm.exceptions.PermissionDeniedError)
        assert _classify_exception(exc) == LlmErrorType.CLIENT_ERROR

    def test_generic_exception(self) -> None:
        """未知异常 -> UNKNOWN。"""
        exc = ValueError("something unexpected")
        assert _classify_exception(exc) == LlmErrorType.UNKNOWN

    def test_plain_exception(self) -> None:
        """普通 Exception -> UNKNOWN。"""
        assert _classify_exception(Exception("plain")) == LlmErrorType.UNKNOWN


# ---------------------------------------------------------------------------
# RetryStrategy 测试
# ---------------------------------------------------------------------------

class TestNoRetryStrategy:
    """NoRetryStrategy 测试。"""

    def test_max_attempts_zero(self) -> None:
        assert NoRetryStrategy().max_attempts() == 0

    @pytest.mark.parametrize("attempt", [0, 1, 5])
    def test_should_retry_always_false(self, attempt: int) -> None:
        assert NoRetryStrategy().should_retry(attempt) is False

    def test_backoff_zero(self) -> None:
        assert NoRetryStrategy().backoff_seconds(1) == 0.0


class TestTimeoutRetryStrategy:
    """TimeoutRetryStrategy 测试。"""

    def test_max_attempts(self) -> None:
        assert TimeoutRetryStrategy().max_attempts() == 3

    def test_should_retry_within_limit(self) -> None:
        s = TimeoutRetryStrategy()
        assert s.should_retry(1) is True
        assert s.should_retry(2) is True
        assert s.should_retry(3) is False

    def test_backoff_exponential(self) -> None:
        s = TimeoutRetryStrategy()
        assert s.backoff_seconds(1) == 1.0
        assert s.backoff_seconds(2) == 2.0
        assert s.backoff_seconds(3) == 4.0


class TestRateLimitRetryStrategy:
    """RateLimitRetryStrategy 测试。"""

    def test_max_attempts(self) -> None:
        assert RateLimitRetryStrategy().max_attempts() == 3

    def test_should_retry_within_limit(self) -> None:
        s = RateLimitRetryStrategy()
        assert s.should_retry(1) is True
        assert s.should_retry(2) is True
        assert s.should_retry(3) is False

    def test_backoff_with_base_5s(self) -> None:
        s = RateLimitRetryStrategy()
        assert s.backoff_seconds(1) == 5.0
        assert s.backoff_seconds(2) == 10.0
        assert s.backoff_seconds(3) == 20.0


class TestNetworkRetryStrategy:
    """NetworkRetryStrategy 测试。"""

    def test_max_attempts(self) -> None:
        assert NetworkRetryStrategy().max_attempts() == 2

    def test_should_retry_within_limit(self) -> None:
        s = NetworkRetryStrategy()
        assert s.should_retry(1) is True
        assert s.should_retry(2) is False

    def test_backoff_linear(self) -> None:
        s = NetworkRetryStrategy()
        assert s.backoff_seconds(1) == 1.0
        assert s.backoff_seconds(2) == 2.0


class TestServerErrorRetryStrategy:
    """ServerErrorRetryStrategy 测试。"""

    def test_max_attempts(self) -> None:
        assert ServerErrorRetryStrategy().max_attempts() == 2

    def test_should_retry_within_limit(self) -> None:
        s = ServerErrorRetryStrategy()
        assert s.should_retry(1) is True
        assert s.should_retry(2) is False

    def test_backoff_exponential(self) -> None:
        s = ServerErrorRetryStrategy()
        assert s.backoff_seconds(1) == 2.0
        assert s.backoff_seconds(2) == 4.0


# ---------------------------------------------------------------------------
# RetryPolicyFactory 测试
# ---------------------------------------------------------------------------

class TestRetryPolicyFactory:
    """RetryPolicyFactory 测试。"""

    @pytest.mark.parametrize(
        "error_type, expected_cls",
        [
            (LlmErrorType.TIMEOUT, TimeoutRetryStrategy),
            (LlmErrorType.AUTH_FAILED, NoRetryStrategy),
            (LlmErrorType.RATE_LIMITED, RateLimitRetryStrategy),
            (LlmErrorType.NETWORK, NetworkRetryStrategy),
            (LlmErrorType.SERVER_ERROR, ServerErrorRetryStrategy),
            (LlmErrorType.CLIENT_ERROR, NoRetryStrategy),
            (LlmErrorType.UNKNOWN, NoRetryStrategy),
        ],
    )
    def test_get_strategy_returns_correct_type(
        self,
        error_type: LlmErrorType,
        expected_cls: type[RetryStrategy],
    ) -> None:
        """每种错误类型返回对应策略类实例。"""
        strategy = RetryPolicyFactory.get_strategy(error_type)
        assert isinstance(strategy, expected_cls)

    def test_strategy_cached(self) -> None:
        """策略实例被缓存（同一引用）。"""
        s1 = RetryPolicyFactory.get_strategy(LlmErrorType.TIMEOUT)
        s2 = RetryPolicyFactory.get_strategy(LlmErrorType.TIMEOUT)
        assert s1 is s2

    def test_retryable_error_types(self) -> None:
        """可重试的错误类型。"""
        retryable = [
            LlmErrorType.TIMEOUT,
            LlmErrorType.RATE_LIMITED,
            LlmErrorType.NETWORK,
            LlmErrorType.SERVER_ERROR,
        ]
        for et in retryable:
            assert RetryPolicyFactory.get_strategy(et).max_attempts() > 0

    def test_non_retryable_error_types(self) -> None:
        """不可重试的错误类型。"""
        non_retryable = [
            LlmErrorType.AUTH_FAILED,
            LlmErrorType.CLIENT_ERROR,
            LlmErrorType.UNKNOWN,
        ]
        for et in non_retryable:
            assert RetryPolicyFactory.get_strategy(et).max_attempts() == 0


# ---------------------------------------------------------------------------
# chat_completion 异常路径测试
# ---------------------------------------------------------------------------

def _make_provider_mock() -> MagicMock:
    """构造 provider mock。"""
    provider = MagicMock()
    provider.provider_code = "deepseek"
    provider.timeout_seconds = 30
    provider.max_retries = 3
    provider.api_key_encrypted = None
    provider.base_url = "https://api.deepseek.com/v1"
    provider.auth_type = LlmAuthType.NONE
    provider.id = 1
    return provider


def _make_model_mock() -> MagicMock:
    """构造 model mock。"""
    model = MagicMock()
    model.model_code = "deepseek-chat"
    model.litellm_model = "deepseek/deepseek-chat"
    model.id = 1
    return model


class TestChatCompletionErrorPath:
    """chat_completion 异常路径测试。"""

    def test_timeout_error_classified(self) -> None:
        """Timeout 异常被分类为 TIMEOUT。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.Timeout
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.TIMEOUT
        assert exc_info.value.provider_code == "deepseek"
        assert exc_info.value.model_code == "deepseek-chat"

    def test_auth_error_classified(self) -> None:
        """AuthenticationError 被分类为 AUTH_FAILED。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.AuthenticationError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.AUTH_FAILED

    def test_rate_limit_error_classified(self) -> None:
        """RateLimitError 被分类为 RATE_LIMITED。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.RateLimitError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.RATE_LIMITED

    def test_network_error_classified(self) -> None:
        """APIConnectionError 被分类为 NETWORK。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.APIConnectionError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.NETWORK

    def test_server_error_classified(self) -> None:
        """InternalServerError 被分类为 SERVER_ERROR。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.InternalServerError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.SERVER_ERROR

    def test_generic_error_classified_unknown(self) -> None:
        """未知异常被分类为 UNKNOWN。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = RuntimeError("unexpected")
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.error_type == LlmErrorType.UNKNOWN

    def test_error_message_sanitized(self) -> None:
        """异常消息中的 api_key 被脱敏。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = RuntimeError(
                "Request failed api_key=sk-secret123"
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert "sk-secret123" not in str(exc_info.value)

    def test_cause_preserved(self) -> None:
        """原始异常作为 __cause__ 保留。"""
        provider = _make_provider_mock()
        model = _make_model_mock()
        original = RuntimeError("original")

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = original
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# chat_completion_with_retry 测试
# ---------------------------------------------------------------------------

class TestChatCompletionWithRetry:
    """chat_completion_with_retry 重试流程测试。"""

    def test_success_no_retry(self) -> None:
        """首次成功，不重试。"""
        provider = _make_provider_mock()
        model = _make_model_mock()
        mock_response = {"choices": [{"message": {"content": "hello"}}]}

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.return_value = mock_response
            result = chat_completion_with_retry(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        assert result == mock_response
        assert mock_completion.call_count == 1
        mock_sleep.assert_not_called()

    def test_timeout_then_success(self) -> None:
        """超时后重试成功。"""
        provider = _make_provider_mock()
        model = _make_model_mock()
        mock_response = {"choices": [{"message": {"content": "hello"}}]}

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = [
                _make_litellm_exc(litellm.exceptions.Timeout),
                mock_response,
            ]
            result = chat_completion_with_retry(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        assert result == mock_response
        assert mock_completion.call_count == 2
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(1.0)

    def test_auth_failed_no_retry(self) -> None:
        """鉴权失败不重试。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.AuthenticationError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion_with_retry(
                    provider, model, [{"role": "user", "content": "hi"}]
                )

        assert exc_info.value.error_type == LlmErrorType.AUTH_FAILED
        assert mock_completion.call_count == 1
        mock_sleep.assert_not_called()

    def test_timeout_retries_exhausted(self) -> None:
        """超时重试耗尽后抛出异常。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.Timeout
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion_with_retry(
                    provider, model, [{"role": "user", "content": "hi"}]
                )

        assert exc_info.value.error_type == LlmErrorType.TIMEOUT
        assert mock_completion.call_count == 3  # 1 initial + 2 retries
        assert mock_sleep.call_count == 2
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_args == [1.0, 2.0]

    def test_rate_limit_backoff_sequence(self) -> None:
        """限流重试退避序列: 5s -> 10s -> 20s。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.RateLimitError
            )
            with pytest.raises(LlmCallError):
                chat_completion_with_retry(
                    provider, model, [{"role": "user", "content": "hi"}]
                )

        assert mock_sleep.call_count == 2
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_args == [5.0, 10.0]

    def test_network_retry_then_success(self) -> None:
        """网络异常重试后成功。"""
        provider = _make_provider_mock()
        model = _make_model_mock()
        mock_response = {"choices": [{"message": {"content": "ok"}}]}

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = [
                _make_litellm_exc(litellm.exceptions.APIConnectionError),
                mock_response,
            ]
            result = chat_completion_with_retry(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        assert result == mock_response
        assert mock_completion.call_count == 2
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(1.0)

    def test_server_error_retries_exhausted(self) -> None:
        """服务端 5xx 重试耗尽。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = _make_litellm_exc(
                litellm.exceptions.InternalServerError
            )
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion_with_retry(
                    provider, model, [{"role": "user", "content": "hi"}]
                )

        assert exc_info.value.error_type == LlmErrorType.SERVER_ERROR
        assert mock_completion.call_count == 2  # 1 initial + 1 retry (max_attempts=2 means 2 total)
        assert mock_sleep.call_count == 1
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_args == [2.0]

    def test_unknown_error_no_retry(self) -> None:
        """未知异常不重试。"""
        provider = _make_provider_mock()
        model = _make_model_mock()

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep") as mock_sleep,
        ):
            mock_completion.side_effect = RuntimeError("unexpected")
            with pytest.raises(LlmCallError) as exc_info:
                chat_completion_with_retry(
                    provider, model, [{"role": "user", "content": "hi"}]
                )

        assert exc_info.value.error_type == LlmErrorType.UNKNOWN
        assert mock_completion.call_count == 1
        mock_sleep.assert_not_called()
