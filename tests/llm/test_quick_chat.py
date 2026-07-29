"""quick_chat 便捷函数的单元测试。

测试覆盖：
- 正常调用：自动路由 -> chat_completion_with_retry -> 返回文本
- system_prompt 注入
- 无可用供应商时抛 RuntimeError
- LLM 调用失败异常透传
- 参数透传（temperature / max_tokens）
- 优先级路由
- 推理模型 content 为空时走 reasoning_content 回退
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.client import LlmCallError, LlmErrorType, quick_chat
from src.llm.orm import Base, LlmHealth, LlmModel, LlmProvider
from src.models.enums import LlmAuthType, LlmHealthStatus, LlmProviderType

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


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


def _setup_provider_model_health(
    session: Session,
    *,
    supports_reasoning: bool = False,
) -> tuple[LlmProvider, LlmModel]:
    """在 DB 中创建一个可路由的 provider + default model + health(healthy)。"""
    provider = LlmProvider(
        provider_code="ark",
        display_name="Ark",
        provider_type=LlmProviderType.CLOUD,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        is_enabled=True,
        priority=10,
        timeout_seconds=30,
        max_retries=3,
    )
    session.add(provider)
    session.flush()

    model = LlmModel(
        provider_id=provider.id,
        model_code="doubao-pro",
        litellm_model="openai/doubao-pro",
        display_name="Doubao Pro",
        is_enabled=True,
        is_default=True,
        supports_reasoning=supports_reasoning,
    )
    session.add(model)
    session.flush()

    health = LlmHealth(
        provider_id=provider.id,
        model_id=model.id,
        health_status=LlmHealthStatus.HEALTHY,
    )
    session.add(health)
    session.flush()

    return provider, model


# ---------------------------------------------------------------------------
# quick_chat 测试
# ---------------------------------------------------------------------------


class TestQuickChat:
    """quick_chat 便捷函数测试。"""

    def test_basic_call(self, session: Session) -> None:
        """正常调用返回文本。"""
        _setup_provider_model_health(session)

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "你好！"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            result = quick_chat("你好", session)

        assert result == "你好！"
        mock_completion.assert_called_once()

    def test_with_system_prompt(self, session: Session) -> None:
        """system_prompt 被注入为第一条消息。"""
        _setup_provider_model_health(session)

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "摘要结果"}}],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            result = quick_chat(
                "请总结这段文字",
                session,
                system_prompt="你是一个摘要助手",
            )

        assert result == "摘要结果"

        call_kwargs = mock_completion.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "你是一个摘要助手"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "请总结这段文字"

    def test_no_system_prompt(self, session: Session) -> None:
        """无 system_prompt 时仅有一条 user 消息。"""
        _setup_provider_model_health(session)

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            quick_chat("hello", session)

        call_kwargs = mock_completion.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_no_available_provider(self, session: Session) -> None:
        """无可用供应商时抛 RuntimeError。"""
        with pytest.raises(RuntimeError, match="无可用 LLM 供应商"):
            quick_chat("test", session)

    def test_llm_error_propagated(self, session: Session) -> None:
        """LLM 调用失败异常透传。"""
        _setup_provider_model_health(session)

        import litellm.exceptions

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.side_effect = litellm.exceptions.Timeout(
                "timeout", "test-model", "openai"
            )
            with pytest.raises(LlmCallError) as exc_info:
                quick_chat("test", session)

        assert exc_info.value.error_type == LlmErrorType.TIMEOUT

    def test_temperature_passed_through(self, session: Session) -> None:
        """temperature 参数透传到 litellm.completion。"""
        _setup_provider_model_health(session)

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            quick_chat("test", session, temperature=0.1)

        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.1

    def test_max_tokens_passed_through(self, session: Session) -> None:
        """max_tokens 参数透传到 litellm.completion。"""
        _setup_provider_model_health(session)

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            quick_chat("test", session, max_tokens=256)

        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["max_tokens"] == 256

    def test_reasoning_model_content_present(self, session: Session) -> None:
        """推理模型 content 非空时直接返回 content。"""
        _setup_provider_model_health(session, supports_reasoning=True)

        mock_response: dict[str, object] = {
            "choices": [
                {
                    "message": {
                        "content": "最终答案",
                        "reasoning_content": "推理过程",
                    }
                }
            ],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            result = quick_chat("test", session)

        assert result == "最终答案"

    def test_reasoning_model_content_empty(self, session: Session) -> None:
        """推理模型 content 为空时回退 reasoning_content。"""
        _setup_provider_model_health(session, supports_reasoning=True)

        mock_response: dict[str, object] = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "推理结果",
                    }
                }
            ],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            result = quick_chat("test", session)

        assert result == "推理结果"

    def test_object_response(self, session: Session) -> None:
        """LLMResponse 返回体的 content 字段被正确提取。

        通过直接 mock chat_completion_with_retry 返回 LLMResponse，
        验证 quick_chat 从 .content 属性提取文本。
        """
        from src.llm.client import LLMResponse
        from src.llm.cost import CostEstimate, TokenUsage

        _setup_provider_model_health(session)

        mock_llm_response = LLMResponse(
            content="对象响应",
            usage=TokenUsage(5, 3, 8),
            cost=CostEstimate(
                usage=TokenUsage(5, 3, 8),
                input_cost=0.0,
                output_cost=0.0,
                total_cost=0.0,
                currency="CNY",
            ),
            model_code="doubao-pro",
            provider_code="ark",
            latency_ms=100,
            raw={},
        )

        with patch("src.llm.client.chat_completion_with_retry") as mock_retry:
            mock_retry.return_value = mock_llm_response
            result = quick_chat("test", session)

        assert result == "对象响应"

    def test_uses_priority_routing(self, session: Session) -> None:
        """多供应商时按 priority 选择优先级最高的。"""
        # 供应商 A: priority=50
        provider_a = LlmProvider(
            provider_code="provider-a",
            display_name="Provider A",
            provider_type=LlmProviderType.CLOUD,
            base_url="https://a.example.com",
            litellm_provider="openai",
            auth_type=LlmAuthType.NONE,
            is_enabled=True,
            priority=50,
            timeout_seconds=30,
            max_retries=3,
        )
        session.add(provider_a)
        session.flush()

        model_a = LlmModel(
            provider_id=provider_a.id,
            model_code="model-a",
            litellm_model="openai/model-a",
            display_name="Model A",
            is_enabled=True,
            is_default=True,
        )
        session.add(model_a)
        session.flush()

        health_a = LlmHealth(
            provider_id=provider_a.id,
            model_id=model_a.id,
            health_status=LlmHealthStatus.HEALTHY,
        )
        session.add(health_a)

        # 供应商 B: priority=10（更高优先级）
        provider_b = LlmProvider(
            provider_code="provider-b",
            display_name="Provider B",
            provider_type=LlmProviderType.CLOUD,
            base_url="https://b.example.com",
            litellm_provider="openai",
            auth_type=LlmAuthType.NONE,
            is_enabled=True,
            priority=10,
            timeout_seconds=30,
            max_retries=3,
        )
        session.add(provider_b)
        session.flush()

        model_b = LlmModel(
            provider_id=provider_b.id,
            model_code="model-b",
            litellm_model="openai/model-b",
            display_name="Model B",
            is_enabled=True,
            is_default=True,
        )
        session.add(model_b)
        session.flush()

        health_b = LlmHealth(
            provider_id=provider_b.id,
            model_id=model_b.id,
            health_status=LlmHealthStatus.HEALTHY,
        )
        session.add(health_b)
        session.flush()

        mock_response: dict[str, object] = {
            "choices": [{"message": {"content": "from B"}}],
        }

        with (
            patch("src.llm.client.litellm.completion") as mock_completion,
            patch("src.llm.client.time.sleep"),
        ):
            mock_completion.return_value = mock_response
            result = quick_chat("test", session)

        assert result == "from B"
        call_kwargs = mock_completion.call_args.kwargs
        assert "model-b" in call_kwargs["model"]
