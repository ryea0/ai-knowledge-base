"""CI 环境下 LLM 供应商种子数据初始化。

在 GitHub Actions 的临时 MySQL 中创建 LLM 供应商、模型和健康状态记录，
使 pipeline 的 LLM 路由链可正常工作。

多供应商 fallback：从 4 个独立环境变量读取不同供应商的密钥，
按优先级创建，router 自动按优先级排序尝试。
任一供应商调用失败（unhealthy）后，router 自动降级到次优供应商。

环境变量与供应商映射：
    - CODING_PLAN_API_KEY  -> ark-coding-plan (priority=10)
    - AGENT_PLAN_API_KEY   -> ark             (priority=20)
    - DEEPSEEK_API_KEY     -> DeepSeek        (priority=30)
    - DASHSCOPE_API_KEY    -> Qwen            (priority=40)

运行: uv run python -m scripts.seed_llm_providers
"""

from __future__ import annotations

import logging
import os
import sys
from typing import NamedTuple

from sqlalchemy import select

from src.config.database import session_scope
from src.llm.crypto import encrypt
from src.llm.orm import LlmHealth, LlmModel, LlmProvider
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmModelSource,
    LlmProviderType,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class ProviderSeed(NamedTuple):
    """供应商种子数据。

    Attributes:
        provider_code: 供应商代码（与本地 DB 保持一致）。
        display_name: 展示名称。
        base_url: API 基础 URL。
        litellm_provider: LiteLLM 供应商标识。
        api_key_env: 存放 API Key 的环境变量名。
        priority: 路由优先级（越小越高）。
        model_code: 默认模型标识。
        litellm_model: LiteLLM 完整模型标识。
    """

    provider_code: str
    display_name: str
    base_url: str
    litellm_provider: str
    api_key_env: str
    priority: int
    model_code: str
    litellm_model: str


_SEEDS: list[ProviderSeed] = [
    ProviderSeed(
        provider_code="ark",
        display_name="ARK Agent Plan",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        litellm_provider="openai",
        api_key_env="AGENT_PLAN_API_KEY",
        priority=10,
        model_code="doubao-seed-2-0-mini-260215",
        litellm_model="openai/doubao-seed-2-0-mini-260215",
    ),
    ProviderSeed(
        provider_code="ark-coding-plan",
        display_name="ARK Coding Plan",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        litellm_provider="openai",
        api_key_env="CODING_PLAN_API_KEY",
        priority=20,
        model_code="ark-code-latest",
        litellm_model="openai/ark-code-latest",
    ),
    ProviderSeed(
        provider_code="DeepSeek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com",
        litellm_provider="openai",
        api_key_env="DEEPSEEK_API_KEY",
        priority=30,
        model_code="deepseek-v4-flash",
        litellm_model="openai/deepseek-v4-flash",
    ),
    ProviderSeed(
        provider_code="Qwen",
        display_name="Qwen (DashScope)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode",
        litellm_provider="openai",
        api_key_env="DASHSCOPE_API_KEY",
        priority=40,
        model_code="qwen3.7-flash-2026-07-15",
        litellm_model="openai/qwen3.7-flash-2026-07-15",
    ),
]


def seed() -> int:
    """创建 LLM 供应商 + 模型 + 健康状态种子数据。

    只创建环境变量中有密钥的供应商，跳过无密钥的。
    已存在的供应商跳过（支持幂等重跑）。

    Returns:
        创建的供应商数量（含模型和健康状态）。
    """
    created = 0

    with session_scope() as session:
        for s in _SEEDS:
            api_key = os.environ.get(s.api_key_env, "").strip()
            if not api_key:
                logger.info(
                    "跳过 %s: 环境变量 %s 未设置",
                    s.provider_code,
                    s.api_key_env,
                )
                continue

            existing = session.execute(
                select(LlmProvider).where(
                    LlmProvider.provider_code == s.provider_code,
                    LlmProvider.is_deleted == False,  # noqa: E712
                )
            ).scalars().first()
            if existing is not None:
                logger.info("供应商 %s 已存在，跳过", s.provider_code)
                continue

            encrypted_key = encrypt(api_key)

            provider = LlmProvider(
                provider_code=s.provider_code,
                display_name=s.display_name,
                provider_type=LlmProviderType.CLOUD,
                base_url=s.base_url,
                litellm_provider=s.litellm_provider,
                auth_type=LlmAuthType.BEARER,
                api_key_encrypted=encrypted_key,
                is_enabled=True,
                priority=s.priority,
                timeout_seconds=60,
                max_retries=3,
            )
            session.add(provider)
            session.flush()

            model = LlmModel(
                provider_id=provider.id,
                model_code=s.model_code,
                litellm_model=s.litellm_model,
                display_name=f"{s.display_name} - {s.model_code}",
                context_window=128000,
                max_output_tokens=4096,
                supports_streaming=True,
                is_enabled=True,
                is_default=True,
                source=LlmModelSource.MANUAL,
            )
            session.add(model)
            session.flush()

            health = LlmHealth(
                provider_id=provider.id,
                model_id=model.id,
                health_status=LlmHealthStatus.UNKNOWN,
                consecutive_failures=0,
                failure_threshold=5,
                health_check_enabled=True,
            )
            session.add(health)
            session.flush()

            created += 1
            logger.info(
                "创建供应商: %s (priority=%d) + 模型: %s + 健康状态",
                s.provider_code,
                s.priority,
                s.model_code,
            )

    logger.info("种子数据创建完成: %d 个供应商", created)
    return created


if __name__ == "__main__":
    count = seed()
    if count == 0:
        logger.error(
            "未创建任何供应商，请检查 CODING_PLAN_API_KEY / AGENT_PLAN_API_KEY "
            "/ DEEPSEEK_API_KEY / DASHSCOPE_API_KEY 等环境变量是否已设置"
        )
        sys.exit(1)
    sys.exit(0)
