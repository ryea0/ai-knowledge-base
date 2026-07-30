"""src.pipeline.llm_call_adapter 的单元测试。

测试覆盖:
- chat_for_analysis 调用 chat_completion (非 chat_completion_with_retry)
- 成功时返回 LLMResponse.content
- 可重试的 LlmCallError (TIMEOUT/RATE_LIMITED) 触发 fallback 到下一个供应商
- 不可重试的 LlmCallError (AUTH_FAILED/CLIENT_ERROR/UNKNOWN) 触发 fallback
- 所有供应商均失败：可重试错误原样抛出 / 不可重试错误转换为 NonRetryableLlmError
- BudgetExceededError 原样穿透（不触发 fallback）
- 无可用供应商时抛出 RuntimeError
- fallback 到第二个供应商成功
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.budget import BudgetExceededError
from src.llm.client import LlmCallError, LlmErrorType, LLMResponse
from src.llm.retry_decorator import NonRetryableLlmError
from src.pipeline.llm_call_adapter import chat_for_analysis


def _make_llm_response(content: str = "response") -> LLMResponse:
    """构造一个测试用 LLMResponse。"""
    return LLMResponse(
        content=content,
        usage=MagicMock(),
        cost=MagicMock(),
        model_code="test-model",
        provider_code="test-provider",
        latency_ms=100,
        raw=None,
    )


def _make_provider_model(code: str = "test"):
    """构造一个 (provider, model) mock 对。"""
    provider = MagicMock()
    provider.provider_code = code
    model = MagicMock()
    model.model_code = f"{code}-model"
    return provider, model


class TestChatForAnalysisCallTarget:
    """验证 chat_for_analysis 调用 chat_completion 而非 chat_completion_with_retry。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_calls_chat_completion_not_with_retry(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """chat_for_analysis 调用 chat_completion, 不调用 chat_completion_with_retry。"""
        provider, model = _make_provider_model("p1")
        mock_chain.return_value = [(provider, model)]
        mock_chat_completion.return_value = _make_llm_response()

        chat_for_analysis("test prompt", MagicMock())

        mock_chat_completion.assert_called_once()
        call_args = mock_chat_completion.call_args
        assert call_args.args[0] is provider
        assert call_args.args[1] is model

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_returns_response_content(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """成功时返回 LLMResponse.content。"""
        mock_chain.return_value = [_make_provider_model("p1")]
        mock_chat_completion.return_value = _make_llm_response("hello world")

        result = chat_for_analysis("test", MagicMock())

        assert result == "hello world"

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_system_prompt_included_in_messages(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """system_prompt 被正确加入 messages。"""
        mock_chain.return_value = [_make_provider_model("p1")]
        mock_chat_completion.return_value = _make_llm_response()

        chat_for_analysis("test", MagicMock(), system_prompt="you are an expert")

        call_args = mock_chat_completion.call_args
        messages = call_args.args[2]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "you are an expert"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test"


class TestFallbackOnRetryableError:
    """可重试的 LlmCallError 触发 fallback 到下一个供应商。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_timeout_triggers_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """TIMEOUT 后尝试下一个供应商并成功。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        mock_chat_completion.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            _make_llm_response("fallback success"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "fallback success"
        assert mock_chat_completion.call_count == 2

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_rate_limited_triggers_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """RATE_LIMITED 后尝试下一个供应商并成功。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        mock_chat_completion.side_effect = [
            LlmCallError("rate limited", error_type=LlmErrorType.RATE_LIMITED),
            _make_llm_response("fallback success"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "fallback success"
        assert mock_chat_completion.call_count == 2

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_network_error_triggers_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """NETWORK 后尝试下一个供应商并成功。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        mock_chat_completion.side_effect = [
            LlmCallError("network", error_type=LlmErrorType.NETWORK),
            _make_llm_response("ok"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "ok"

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_server_error_triggers_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """SERVER_ERROR 后尝试下一个供应商并成功。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        mock_chat_completion.side_effect = [
            LlmCallError("server error", error_type=LlmErrorType.SERVER_ERROR),
            _make_llm_response("ok"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "ok"


class TestFallbackOnNonRetryableError:
    """不可重试的 LlmCallError 也触发 fallback。"""

    @pytest.mark.parametrize(
        "error_type",
        [
            LlmErrorType.AUTH_FAILED,
            LlmErrorType.CLIENT_ERROR,
            LlmErrorType.UNKNOWN,
        ],
    )
    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_non_retryable_triggers_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
        error_type: LlmErrorType,
    ) -> None:
        """AUTH_FAILED / CLIENT_ERROR / UNKNOWN 也触发 fallback。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        mock_chat_completion.side_effect = [
            LlmCallError(f"{error_type.value} error", error_type=error_type),
            _make_llm_response("fallback ok"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "fallback ok"
        assert mock_chat_completion.call_count == 2


class TestAllProvidersFail:
    """所有供应商均失败时的行为。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_all_fail_retryable_raises_llm_call_error(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """全部失败且最后错误为可重试类型，原样抛出 LlmCallError。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        last_error = LlmCallError(
            "rate limited",
            error_type=LlmErrorType.RATE_LIMITED,
            provider_code="p2",
            model_code="p2-model",
        )
        mock_chat_completion.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            last_error,
        ]

        with pytest.raises(LlmCallError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value is last_error
        assert exc_info.value.error_type == LlmErrorType.RATE_LIMITED
        assert mock_chat_completion.call_count == 2

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_all_fail_non_retryable_raises_non_retryable(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """全部失败且最后错误为不可重试类型，抛出 NonRetryableLlmError。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        last_error = LlmCallError(
            "auth failed",
            error_type=LlmErrorType.AUTH_FAILED,
            provider_code="p2",
            model_code="p2-model",
        )
        mock_chat_completion.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            last_error,
        ]

        with pytest.raises(NonRetryableLlmError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value.original is last_error
        assert mock_chat_completion.call_count == 2

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_single_provider_fail_retryable(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """路由链仅一个供应商且失败（可重试），原样抛出。"""
        p1, m1 = _make_provider_model("p1")
        mock_chain.return_value = [(p1, m1)]
        original_error = LlmCallError(
            "timeout",
            error_type=LlmErrorType.TIMEOUT,
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(LlmCallError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value is original_error

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_single_provider_fail_non_retryable(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """路由链仅一个供应商且失败（不可重试），转换为 NonRetryableLlmError。"""
        p1, m1 = _make_provider_model("p1")
        mock_chain.return_value = [(p1, m1)]
        original_error = LlmCallError(
            "auth failed",
            error_type=LlmErrorType.AUTH_FAILED,
            provider_code="p1",
            model_code="p1-model",
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(NonRetryableLlmError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value.original is original_error
        assert exc_info.value.original.provider_code == "p1"


class TestBudgetExceededPassthrough:
    """BudgetExceededError 原样穿透，不触发 fallback。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_budget_exceeded_no_fallback(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """BudgetExceededError 原样穿透，不尝试下一个供应商。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        mock_chain.return_value = [(p1, m1), (p2, m2)]
        budget_error = BudgetExceededError(
            "budget exceeded",
            daily_limit=100.0,
            daily_spent=90.0,
            estimated_cost=20.0,
            currency="CNY",
        )
        mock_chat_completion.side_effect = budget_error

        with pytest.raises(BudgetExceededError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value is budget_error
        assert mock_chat_completion.call_count == 1


class TestNoProviderAvailable:
    """无可用供应商时抛出 RuntimeError。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    def test_no_provider_raises_runtime_error(
        self,
        mock_chain: patch,
    ) -> None:
        """无可用供应商-模型组合时抛出 RuntimeError。"""
        mock_chain.return_value = []

        with pytest.raises(RuntimeError, match="无可用 LLM 供应商-模型组合"):
            chat_for_analysis("test", MagicMock())


class TestThreeProviderFallback:
    """三个供应商的 fallback 场景。"""

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_third_provider_succeeds(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """前两个失败，第三个成功。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        p3, m3 = _make_provider_model("p3")
        mock_chain.return_value = [(p1, m1), (p2, m2), (p3, m3)]
        mock_chat_completion.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            LlmCallError("auth", error_type=LlmErrorType.AUTH_FAILED),
            _make_llm_response("third time lucky"),
        ]

        result = chat_for_analysis("test", MagicMock())

        assert result == "third time lucky"
        assert mock_chat_completion.call_count == 3

    @patch("src.pipeline.llm_call_adapter.get_routable_chain")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_mixed_errors_all_fail(
        self,
        mock_chat_completion: patch,
        mock_chain: patch,
    ) -> None:
        """三个供应商混合错误全部失败，按最后一个错误类型决定异常类型。"""
        p1, m1 = _make_provider_model("p1")
        p2, m2 = _make_provider_model("p2")
        p3, m3 = _make_provider_model("p3")
        mock_chain.return_value = [(p1, m1), (p2, m2), (p3, m3)]
        last_error = LlmCallError(
            "client error",
            error_type=LlmErrorType.CLIENT_ERROR,
            provider_code="p3",
            model_code="p3-model",
        )
        mock_chat_completion.side_effect = [
            LlmCallError("timeout", error_type=LlmErrorType.TIMEOUT),
            LlmCallError("rate", error_type=LlmErrorType.RATE_LIMITED),
            last_error,
        ]

        with pytest.raises(NonRetryableLlmError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value.original is last_error
        assert mock_chat_completion.call_count == 3
