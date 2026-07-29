"""LLM 供应商相关 SQLAlchemy ORM 模型。

对应 DB 表：
    - ``kb_llm_provider``: 供应商连接配置 + 鉴权信息（不含健康状态）
    - ``kb_llm_model``: 模型清单
    - ``kb_llm_health``: 模型级当前健康状态（upsert 语义）

DDL 见 ``deploy/sql/01-03_*.sql``，约定见 docs/specs/llm-provider.md §9。

``Base`` 和 ``BaseEntity`` 从 :mod:`src.common.base_entity` 导入并重新导出，
保持 ``from src.llm.orm import Base`` 的向后兼容。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_entity import Base, BaseEntity
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmModelSource,
    LlmProviderType,
)

__all__ = ["Base", "BaseEntity", "LlmHealth", "LlmModel", "LlmProvider", "LlmProviderConnectivity"]


class LlmProvider(BaseEntity):
    """LLM 供应商 ORM 模型，对应 ``kb_llm_provider`` 表。

    存储供应商连接配置和鉴权信息。健康状态已移至 :class:`LlmHealth`（模型级）。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。

    Attributes:
        provider_code: 供应商代码，如 ``deepseek`` / ``ark`` / ``openai``。
        display_name: 展示名称。
        provider_type: 供应商类型（cloud / local）。
        base_url: API 基础 URL。
        litellm_provider: LiteLLM 供应商标识，决定协议族和模型前缀。
        auth_type: 鉴权方式（bearer / oauth / header / none）。
        api_key_encrypted: 加密主凭证，none 类型为 None。
        secret_key_encrypted: 加密二次凭证，仅 oauth 使用。
        header_name: 自定义鉴权 header 名，仅 header 使用。
        token_url: OAuth token 交换地址，仅 oauth 使用。
        is_enabled: 是否启用。
        priority: 路由优先级，数值越小越高。
        timeout_seconds: 单次请求超时秒数。
        max_retries: 最大重试次数上限。
        rpm_limit: 每分钟请求上限，0=不限速（预留）。
    """

    __tablename__ = "kb_llm_provider"

    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_type: Mapped[LlmProviderType] = mapped_column(
        Integer, nullable=False, default=LlmProviderType.CLOUD
    )
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    litellm_provider: Mapped[str] = mapped_column(String(40), nullable=False)

    # 鉴权
    auth_type: Mapped[LlmAuthType] = mapped_column(
        Integer, nullable=False, default=LlmAuthType.BEARER
    )
    api_key_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_key_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    header_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 路由与限流
    is_enabled: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    rpm_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LlmModel(BaseEntity):
    """LLM 模型 ORM 模型，对应 ``kb_llm_model`` 表。

    每个供应商下可有多个模型，``is_default`` 标记供应商默认模型（至多一个）。
    模型能力/定价信息可通过 :mod:`src.llm.service` 的 ``discover_models`` 自动发现补全。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。

    Attributes:
        provider_id: 所属供应商 ID。
        model_code: 模型标识，如 ``deepseek-chat`` / ``llama3.2``。
        litellm_model: LiteLLM 完整模型标识，如 ``openai/deepseek-chat``。
        display_name: 展示名称。
        description: 模型描述。
        context_window: 上下文窗口大小 tokens。
        max_output_tokens: 最大输出 tokens。
        supports_streaming: 是否支持流式输出。
        supports_function_calling: 是否支持函数调用。
        supports_vision: 是否支持视觉/多模态。
        supports_reasoning: 是否为推理模型（回复在 reasoning_content
            或 thinking_blocks 而非 content）。
        task_type: 任务类型数组，如 ``["TextGeneration"]``、
            ``["VisualQuestionAnswering"]``，由模型发现时从 API 提取。
        input_price_per_1m: 输入每百万 token 价格 USD。
        output_price_per_1m: 输出每百万 token 价格 USD。
        is_enabled: 是否启用。
        is_default: 是否为该供应商默认模型。
        source: 模型记录来源（preset / discovered / manual）。
    """

    __tablename__ = "kb_llm_model"

    provider_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_code: Mapped[str] = mapped_column(String(80), nullable=False)
    litellm_model: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_window: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4096
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4096
    )
    supports_streaming: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )
    supports_function_calling: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    supports_vision: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    supports_reasoning: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    task_type: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    input_price_per_1m: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, default=0.0
    )
    output_price_per_1m: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, default=0.0
    )
    is_enabled: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )
    is_default: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    source: Mapped[LlmModelSource] = mapped_column(
        Integer, nullable=False, default=LlmModelSource.PRESET
    )


class LlmHealth(BaseEntity):
    """LLM 模型健康状态 ORM 模型，对应 ``kb_llm_health`` 表。

    模型级当前健康状态（upsert 语义），每个模型至多一行。
    创建模型时自动创建对应 health 行（``health_status=unknown``），
    删除模型时同步软删除。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。

    Attributes:
        provider_id: 供应商 ID。
        model_id: 模型 ID（每个模型一行）。
        health_status: 健康状态（healthy / degraded / unhealthy / unknown）。
        consecutive_failures: 连续失败次数，成功时归零。
        failure_threshold: 连续失败达此值时转 unhealthy。
        health_check_enabled: 是否启用健康检查。
        last_check_at: 最近健康检查时间。
        last_success_at: 最近成功时间。
        last_failure_at: 最近失败时间。
        last_latency_ms: 最近检查延迟毫秒。
        last_error: 最近错误信息（须脱敏）。
    """

    __tablename__ = "kb_llm_health"

    provider_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    health_status: Mapped[LlmHealthStatus] = mapped_column(
        Integer, nullable=False, default=LlmHealthStatus.UNKNOWN
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    health_check_enabled: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )
    last_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class LlmProviderConnectivity(BaseEntity):
    """LLM 供应商联通性 ORM 模型，对应 ``kb_llm_provider_connectivity`` 表。

    供应商级当前联通性（upsert 语义），每个供应商至多一行。
    由定时任务（每 5 分钟）或手动触发连通性测试时写入/更新。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。

    Attributes:
        provider_id: 供应商 ID。
        is_connected: 是否连通。
        latency_ms: 最近探测延迟毫秒。
        last_check_at: 最近探测时间。
        last_success_at: 最近成功时间。
        last_failure_at: 最近失败时间。
        last_error: 最近错误信息（须脱敏）。
    """

    __tablename__ = "kb_llm_provider_connectivity"

    provider_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_connected: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
