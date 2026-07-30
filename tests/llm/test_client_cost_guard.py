"""src.llm.client 的 get_cost_guard + node_name 成本追踪测试。

测试覆盖：
- get_cost_guard: ContextVar 优先 / 懒加载单例 / BUDGET_YUAN 环境变量 / 默认值
- chat_completion: node_name 透传 -> CostGuard.record / CostGuard.check
- chat_completion_with_retry: node_name 透传
- BudgetExceededError: 超预算时 chat_completion 抛出
- 向后兼容: 不传 node_name 使用默认值 "unknown"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import litellm.exceptions
import pytest

from src.common.cost_guard import BudgetExceededError, CostGuard
from src.llm.client import (
    LLMResponse,
    chat_completion,
    chat_completion_with_retry,
    get_cost_guard,
)
from src.models.enums import LlmAuthType


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
    model.supports_reasoning = False
    model.input_price_per_1m = 1.0
    model.output_price_per_1m = 2.0
    model.currency = "CNY"
    model.id = 1
    return model


def _make_usage_response(content: str = "hello") -> dict[str, Any]:
    """构造含 usage 的 mock LLM 响应。"""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


@pytest.fixture(autouse=True)
def _reset_cost_guard() -> Any:
    """每个测试前重置全局 CostGuard 单例和 ContextVar，避免测试间状态泄漏。"""
    import src.llm.client as client_mod
    from src.common.cost_guard import cost_guard_var

    original = client_mod._cost_guard_instance
    client_mod._cost_guard_instance = None
    # 清除可能残留的 ContextVar（工作流注入的 guard）
    cv_token = cost_guard_var.set(None)
    yield
    client_mod._cost_guard_instance = original
    cost_guard_var.reset(cv_token)


# ---------------------------------------------------------------------------
# get_cost_guard 测试
# ---------------------------------------------------------------------------


class TestGetCostGuard:
    """get_cost_guard 查找优先级测试。"""

    def test_contextvar_takes_priority(self) -> None:
        """ContextVar 注入的 guard 优先于全局懒加载单例。"""
        import src.llm.client as client_mod
        from src.common.cost_guard import cost_guard_var

        # 预先创建全局单例
        global_guard = get_cost_guard()
        assert client_mod._cost_guard_instance is not None

        # 注入 ContextVar guard
        cv_guard = CostGuard(budget_yuan=99.0)
        token = cost_guard_var.set(cv_guard)
        try:
            result = get_cost_guard()
            assert result is cv_guard
            assert result is not global_guard
        finally:
            cost_guard_var.reset(token)

    def test_lazy_init_default(self) -> None:
        """未设置 BUDGET_YUAN 时使用默认值 1.0。"""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("BUDGET_YUAN", None)
            guard = get_cost_guard()
            assert guard.budget_yuan == 1.0

    def test_env_override(self) -> None:
        """BUDGET_YUAN 环境变量覆盖默认值。"""

        import src.llm.client as client_mod

        client_mod._cost_guard_instance = None
        with patch.dict("os.environ", {"BUDGET_YUAN": "5.0"}):
            guard = get_cost_guard()
            assert guard.budget_yuan == 5.0

    def test_invalid_env_fallback(self) -> None:
        """BUDGET_YUAN 无法解析时回退到默认值 1.0。"""

        import src.llm.client as client_mod

        client_mod._cost_guard_instance = None
        with patch.dict("os.environ", {"BUDGET_YUAN": "not-a-number"}):
            guard = get_cost_guard()
            assert guard.budget_yuan == 1.0

    def test_singleton_reuse(self) -> None:
        """多次调用返回同一实例。"""
        guard1 = get_cost_guard()
        guard2 = get_cost_guard()
        assert guard1 is guard2

    def test_returns_cost_guard_type(self) -> None:
        """返回类型为 CostGuard。"""
        guard = get_cost_guard()
        assert isinstance(guard, CostGuard)


# ---------------------------------------------------------------------------
# chat_completion node_name + CostGuard 集成测试
# ---------------------------------------------------------------------------


class TestChatCompletionNodeName:
    """chat_completion 的 node_name 透传与 CostGuard 集成测试。"""

    def test_record_called_with_node_name(self) -> None:
        """成功调用后 CostGuard.record 被调用，node_name 正确传入。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = _make_usage_response()
            chat_completion(
                provider,
                model,
                [{"role": "user", "content": "hi"}],
                node_name="analyze",
            )

        mock_guard.record.assert_called_once()
        call_args = mock_guard.record.call_args
        assert call_args[0][0] == "analyze"
        assert call_args[0][1]["prompt_tokens"] == 10
        assert call_args[0][1]["completion_tokens"] == 5
        assert call_args[1]["model"] == "deepseek-chat"

    def test_check_called_after_record(self) -> None:
        """record 后调用 check。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = _make_usage_response()
            chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        mock_guard.record.assert_called_once()
        mock_guard.check.assert_called_once()

    def test_default_node_name_unknown(self) -> None:
        """不传 node_name 时使用默认值 'unknown'。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = _make_usage_response()
            chat_completion(provider, model, [{"role": "user", "content": "hi"}])

        call_args = mock_guard.record.call_args
        assert call_args[0][0] == "unknown"

    def test_budget_exceeded_raises(self) -> None:
        """CostGuard.check 抛 BudgetExceededError 时穿透。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        mock_guard.check.side_effect = BudgetExceededError(
            total_cost=2.0, budget=1.0
        )
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = _make_usage_response()
            with pytest.raises(BudgetExceededError):
                chat_completion(
                    provider,
                    model,
                    [{"role": "user", "content": "hi"}],
                    node_name="analyze",
                )

    def test_stream_skips_cost_guard(self) -> None:
        """流式调用不触发 CostGuard record/check（无 usage）。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        mock_stream_response = MagicMock()
        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = mock_stream_response
            result = chat_completion(
                provider,
                model,
                [{"role": "user", "content": "hi"}],
                stream=True,
                node_name="analyze",
            )

        assert result is mock_stream_response
        mock_guard.record.assert_not_called()
        mock_guard.check.assert_not_called()

    def test_call_failure_skips_cost_guard(self) -> None:
        """LLM 调用失败时不触发 CostGuard record/check。"""
        import src.llm.client as client_mod
        from src.llm.client import LlmCallError

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.side_effect = RuntimeError("connection failed")
            with pytest.raises(LlmCallError):
                chat_completion(
                    provider,
                    model,
                    [{"role": "user", "content": "hi"}],
                    node_name="analyze",
                )

        mock_guard.record.assert_not_called()
        mock_guard.check.assert_not_called()


# ---------------------------------------------------------------------------
# chat_completion_with_retry node_name 透传测试
# ---------------------------------------------------------------------------


class TestChatCompletionWithRetryNodeName:
    """chat_completion_with_retry 的 node_name 透传测试。"""

    def test_node_name_passthrough(self) -> None:
        """node_name 透传给 chat_completion。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = _make_usage_response()
            result = chat_completion_with_retry(
                provider,
                model,
                [{"role": "user", "content": "hi"}],
                node_name="review",
            )

        assert isinstance(result, LLMResponse)
        call_args = mock_guard.record.call_args
        assert call_args[0][0] == "review"

    def test_default_node_name(self) -> None:
        """不传 node_name 时透传默认值 'unknown'。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = _make_usage_response()
            chat_completion_with_retry(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        call_args = mock_guard.record.call_args
        assert call_args[0][0] == "unknown"

    def test_retry_records_each_attempt(self) -> None:
        """重试时每次成功的尝试都 record 一次（重试失败不 record）。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.side_effect = [
                _make_litellm_exc(litellm.exceptions.Timeout),
                _make_usage_response("ok"),
            ]
            result = chat_completion_with_retry(
                provider,
                model,
                [{"role": "user", "content": "hi"}],
                node_name="analyze",
            )

        assert isinstance(result, LLMResponse)
        # 只有一次成功调用触发了 record（失败的不 record）
        mock_guard.record.assert_called_once()
        assert mock_guard.record.call_args[0][0] == "analyze"


# ---------------------------------------------------------------------------
# 向后兼容测试
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """向后兼容：现有调用方不传 node_name 也能正常工作。"""

    def test_chat_completion_no_node_name(self) -> None:
        """chat_completion 不传 node_name 正常工作。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with patch("src.llm.client.litellm.completion") as mock_completion:
            mock_completion.return_value = _make_usage_response()
            result = chat_completion(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        assert isinstance(result, LLMResponse)
        assert result.content == "hello"
        mock_guard.record.assert_called_once()
        mock_guard.check.assert_called_once()

    def test_chat_completion_with_retry_no_node_name(self) -> None:
        """chat_completion_with_retry 不传 node_name 正常工作。"""
        import src.llm.client as client_mod

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_guard = MagicMock(spec=CostGuard)
        client_mod._cost_guard_instance = mock_guard

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = _make_usage_response()
            result = chat_completion_with_retry(
                provider, model, [{"role": "user", "content": "hi"}]
            )

        assert isinstance(result, LLMResponse)
        assert result.content == "hello"

    def test_quick_chat_no_node_name(self) -> None:
        """quick_chat 不传 node_name 正常工作，默认 'unknown' 透传。"""
        from src.llm.client import LLMResponse
        from src.llm.cost import CostEstimate, TokenUsage

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_response = LLMResponse(
            content="reply",
            usage=TokenUsage(5, 3, 8),
            cost=CostEstimate(
                usage=TokenUsage(5, 3, 8),
                input_cost=0.0,
                output_cost=0.0,
                total_cost=0.0,
                currency="CNY",
            ),
            model_code="deepseek-chat",
            provider_code="deepseek",
            latency_ms=100,
            raw={},
        )

        with (
            patch("src.llm.router.select_first_available") as mock_select,
            patch("src.llm.client.chat_completion_with_retry") as mock_retry,
        ):
            mock_select.return_value = (provider, model)
            mock_retry.return_value = mock_response
            from src.llm.client import quick_chat

            result = quick_chat("hi", MagicMock())

        assert result == "reply"
        mock_retry.assert_called_once()
        assert mock_retry.call_args[1]["node_name"] == "unknown"

    def test_quick_chat_passes_node_name(self) -> None:
        """quick_chat 传入 node_name 时透传给 chat_completion_with_retry。"""
        from src.llm.client import LLMResponse
        from src.llm.cost import CostEstimate, TokenUsage

        provider = _make_provider_mock()
        model = _make_model_mock()

        mock_response = LLMResponse(
            content="reply",
            usage=TokenUsage(5, 3, 8),
            cost=CostEstimate(
                usage=TokenUsage(5, 3, 8),
                input_cost=0.0,
                output_cost=0.0,
                total_cost=0.0,
                currency="CNY",
            ),
            model_code="deepseek-chat",
            provider_code="deepseek",
            latency_ms=100,
            raw={},
        )

        with (
            patch("src.llm.router.select_first_available") as mock_select,
            patch("src.llm.client.chat_completion_with_retry") as mock_retry,
        ):
            mock_select.return_value = (provider, model)
            mock_retry.return_value = mock_response
            from src.llm.client import quick_chat

            quick_chat("hi", MagicMock(), node_name="summarize")

        mock_retry.assert_called_once()
        assert mock_retry.call_args[1]["node_name"] == "summarize"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_litellm_exc(
    exc_cls: Any,
    message: str = "test error",
) -> Any:
    """构造 LiteLLM 异常实例。"""
    try:
        return exc_cls(message=message, model="test", llm_provider="deepseek")
    except TypeError:
        try:
            return exc_cls(message)
        except TypeError:
            return exc_cls()
