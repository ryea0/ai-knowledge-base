"""src.pipeline.llm_call_adapter 的单元测试。

测试覆盖:
- chat_for_analysis 调用 chat_completion (非 chat_completion_with_retry)
- 可重试的 LlmCallError (TIMEOUT) 原样抛出
- 不可重试的 LlmCallError (AUTH_FAILED/CLIENT_ERROR/UNKNOWN) 转换为 NonRetryableLlmError
- NonRetryableLlmError.original 指向原始异常
- BudgetExceededError 原样穿透
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


class TestChatForAnalysisCallTarget:
    """验证 chat_for_analysis 调用 chat_completion 而非 chat_completion_with_retry。"""

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_calls_chat_completion_not_with_retry(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """chat_for_analysis 调用 chat_completion, 不调用 chat_completion_with_retry。"""
        mock_provider = MagicMock()
        mock_model = MagicMock()
        mock_select.return_value = (mock_provider, mock_model)
        mock_chat_completion.return_value = _make_llm_response()

        mock_session = MagicMock()
        chat_for_analysis("test prompt", mock_session)

        mock_chat_completion.assert_called_once()
        call_args = mock_chat_completion.call_args
        assert call_args.args[0] is mock_provider
        assert call_args.args[1] is mock_model

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_returns_response_content(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """成功时返回 LLMResponse.content。"""
        mock_select.return_value = (MagicMock(), MagicMock())
        mock_chat_completion.return_value = _make_llm_response("hello world")

        result = chat_for_analysis("test", MagicMock())

        assert result == "hello world"


class TestRetryableLlmErrorPassthrough:
    """可重试的 LlmCallError 原样抛出。"""

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_timeout_error_not_converted(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """TIMEOUT 的 LlmCallError 原样抛出。"""
        mock_select.return_value = (MagicMock(), MagicMock())
        original_error = LlmCallError(
            "timeout",
            error_type=LlmErrorType.TIMEOUT,
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(LlmCallError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value is original_error
        assert exc_info.value.error_type == LlmErrorType.TIMEOUT

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_rate_limited_error_not_converted(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """RATE_LIMITED 的 LlmCallError 原样抛出。"""
        mock_select.return_value = (MagicMock(), MagicMock())
        original_error = LlmCallError(
            "rate limited",
            error_type=LlmErrorType.RATE_LIMITED,
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(LlmCallError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value is original_error


class TestNonRetryableLlmErrorConversion:
    """不可重试的 LlmCallError 转换为 NonRetryableLlmError。"""

    @pytest.mark.parametrize(
        "error_type",
        [
            LlmErrorType.AUTH_FAILED,
            LlmErrorType.CLIENT_ERROR,
            LlmErrorType.UNKNOWN,
        ],
    )
    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_non_retryable_converted(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
        error_type: LlmErrorType,
    ) -> None:
        """AUTH_FAILED / CLIENT_ERROR / UNKNOWN 转换为 NonRetryableLlmError。"""
        mock_select.return_value = (MagicMock(), MagicMock())
        original_error = LlmCallError(
            f"{error_type.value} error",
            error_type=error_type,
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(NonRetryableLlmError) as exc_info:
            chat_for_analysis("test", MagicMock())

        assert exc_info.value.original is original_error

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_original_attribute_points_to_source(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """NonRetryableLlmError.original 指向原始 LlmCallError 实例。"""
        mock_select.return_value = (MagicMock(), MagicMock())
        original_error = LlmCallError(
            "auth failed",
            error_type=LlmErrorType.AUTH_FAILED,
            provider_code="test-provider",
            model_code="test-model",
        )
        mock_chat_completion.side_effect = original_error

        with pytest.raises(NonRetryableLlmError) as exc_info:
            chat_for_analysis("test", MagicMock())

        wrapped = exc_info.value
        assert wrapped.original is original_error
        assert wrapped.original.error_type == LlmErrorType.AUTH_FAILED
        assert wrapped.original.provider_code == "test-provider"


class TestBudgetExceededPassthrough:
    """BudgetExceededError 原样穿透，不被捕获。"""

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    @patch("src.pipeline.llm_call_adapter.chat_completion")
    def test_budget_exceeded_not_caught(
        self,
        mock_chat_completion: patch,
        mock_select: patch,
    ) -> None:
        """BudgetExceededError 原样穿透。"""
        mock_select.return_value = (MagicMock(), MagicMock())
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


class TestNoProviderAvailable:
    """无可用供应商时抛出 RuntimeError。"""

    @patch("src.pipeline.llm_call_adapter.select_first_available")
    def test_no_provider_raises_runtime_error(
        self,
        mock_select: patch,
    ) -> None:
        """无可用供应商-模型组合时抛出 RuntimeError。"""
        mock_select.return_value = None

        with pytest.raises(RuntimeError, match="无可用 LLM 供应商-模型组合"):
            chat_for_analysis("test", MagicMock())
