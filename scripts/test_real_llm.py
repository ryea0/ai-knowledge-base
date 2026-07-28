"""真实 LLM 调用集成测试。

需要真实 DB + API Key，非 CI 用途。
运行: uv run python -m scripts.test_real_llm
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from src.config.database import session_scope
from src.llm.client import chat_completion_with_retry, quick_chat
from src.llm.orm import LlmModel, LlmProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def test_quick_chat() -> None:
    """测试 quick_chat 便捷函数（自动路由）。"""
    print("\n" + "=" * 60)
    print("1. quick_chat -- 自动路由调用")
    print("=" * 60)

    with session_scope() as session:
        try:
            result = quick_chat(
                "用一句话解释什么是大语言模型",
                session,
                system_prompt="你是一个技术科普助手，回答简洁明了。",
                temperature=0.3,
                max_tokens=200,
            )
            print(f"回复: {result}")
        except Exception as exc:
            print(f"失败: {exc}")


def test_chat_completion_with_cost() -> None:
    """测试 chat_completion_with_retry + 成本估算（指定 ark）。"""
    print("\n" + "=" * 60)
    print("2. chat_completion_with_retry + estimate_cost -- 指定 ark")
    print("=" * 60)

    with session_scope() as session:
        provider = session.execute(
            select(LlmProvider).where(
                LlmProvider.provider_code == "ark",
                LlmProvider.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()
        if provider is None:
            print("ark 供应商不存在")
            return

        model = session.execute(
            select(LlmModel).where(
                LlmModel.provider_id == provider.id,
                LlmModel.is_default == True,  # noqa: E712
                LlmModel.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()
        if model is None:
            print("ark 无默认模型")
            return

        print(f"供应商: {provider.provider_code}")
        print(f"模型: {model.model_code} (litellm: {model.litellm_model})")
        print(f"定价: input=${model.input_price_per_1m}/1M  output=${model.output_price_per_1m}/1M")

        try:
            response = chat_completion_with_retry(
                provider,
                model,
                [
                    {"role": "system", "content": "你是技术助手"},
                    {"role": "user", "content": "RAG 和微调有什么区别？各一句话。"},
                ],
                temperature=0.3,
                max_tokens=300,
                session=session,
            )

            print(f"\n回复:\n{response.content}")

            print("\nToken 用量:")
            print(f"  prompt_tokens:     {response.usage.prompt_tokens}")
            print(f"  completion_tokens: {response.usage.completion_tokens}")
            print(f"  total_tokens:      {response.usage.total_tokens}")
            print("成本估算 (USD):")
            print(f"  input_cost:  ${response.cost.input_cost_usd:.6f}")
            print(f"  output_cost: ${response.cost.output_cost_usd:.6f}")
            print(f"  total_cost:  ${response.cost.total_cost_usd:.6f}")

        except Exception as exc:
            print(f"失败: {exc}")
            import traceback

            traceback.print_exc()

        # 检查调用后的健康状态
        from src.llm.orm import LlmHealth

        health = session.execute(
            select(LlmHealth).where(
                LlmHealth.model_id == model.id,
                LlmHealth.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()
        if health:
            print(f"\n调用后健康状态: {health.health_status}")
            print(f"  consecutive_failures: {health.consecutive_failures}")
            print(f"  last_latency_ms: {health.last_latency_ms}")
            print(f"  last_success_at: {health.last_success_at}")


def test_deepseek() -> None:
    """测试 DeepSeek 供应商调用。"""
    print("\n" + "=" * 60)
    print("3. chat_completion_with_retry -- 指定 DeepSeek")
    print("=" * 60)

    with session_scope() as session:
        provider = session.execute(
            select(LlmProvider).where(
                LlmProvider.provider_code == "DeepSeek",
                LlmProvider.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()
        if provider is None:
            print("DeepSeek 供应商不存在")
            return

        model = session.execute(
            select(LlmModel).where(
                LlmModel.provider_id == provider.id,
                LlmModel.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()
        if model is None:
            print("DeepSeek 无模型")
            return

        print(f"供应商: {provider.provider_code}")
        print(f"模型: {model.model_code} (litellm: {model.litellm_model})")
        print(f"定价: input=${model.input_price_per_1m}/1M  output=${model.output_price_per_1m}/1M")

        try:
            response = chat_completion_with_retry(
                provider,
                model,
                [{"role": "user", "content": "1+1等于几？只回答数字。"}],
                temperature=0.0,
                max_tokens=10,
                session=session,
            )

            print(f"回复: {response.content}")
            print(
                f"Token: prompt={response.usage.prompt_tokens}"
                f" completion={response.usage.completion_tokens}"
                f" total={response.usage.total_tokens}"
            )
            print(f"成本: ${response.cost.total_cost_usd:.6f}")

        except Exception as exc:
            print(f"失败: {exc}")
            import traceback

            traceback.print_exc()


"""
DeepSeek 推理模型（deepseek-v4-flash）的响应结构与非推理模型不同：
非推理模型:  message.content = "2"
推理模型:    message.content = ""                    ← 空
             message.reasoning_content = "推理过程..." ← 实际内容在这
"""

if __name__ == "__main__":
    test_quick_chat()
    test_chat_completion_with_cost()
    test_deepseek()
    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)
