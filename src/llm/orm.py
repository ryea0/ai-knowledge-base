"""LLM 供应商相关 SQLAlchemy ORM 模型。

对应 DB 表：
    - ``kb_llm_provider``: 供应商配置 + 健康当前状态
    - ``kb_llm_model``: 模型清单
    - ``kb_llm_health_log``: 健康检查日志（append-only）

DDL 见 ``deploy/sql/01-04_*.sql``，约定见 AGENTS.md §9。

``Base`` 和 ``BaseEntity`` 从 :mod:`src.common.base_entity` 导入并重新导出，
保持 ``from src.llm.orm import Base`` 的向后兼容。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_entity import Base, BaseEntity
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmModelSource,
    LlmProviderType,
)

__all__ = ["Base", "BaseEntity", "LlmHealthLog", "LlmModel", "LlmProvider"]


class LlmProvider(BaseEntity):
    """LLM 供应商 ORM 模型，对应 ``kb_llm_provider`` 表。

    存储供应商连接配置、鉴权信息和健康状态快照。
    健康状态为内联当前值，历史记录见 :class:`LlmHealthLog`。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。
    """

    __tablename__ = "kb_llm_provider"

    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_type: Mapped[LlmProviderType] = mapped_column(
        Integer, nullable=False, default=LlmProviderType.CLOUD
    )
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    litellm_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    auth_type: Mapped[LlmAuthType] = mapped_column(
        Integer, nullable=False, default=LlmAuthType.BEARER
    )
    api_key_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    rpm_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    health_status: Mapped[LlmHealthStatus] = mapped_column(
        Integer, nullable=False, default=LlmHealthStatus.UNKNOWN
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
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class LlmModel(BaseEntity):
    """LLM 模型 ORM 模型，对应 ``kb_llm_model`` 表。

    每个供应商下可有多个模型，``is_default`` 标记供应商默认模型（至多一个）。
    模型能力/定价信息可通过 :mod:`src.llm.service` 的 ``discover_models`` 自动发现补全。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。
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


class LlmHealthLog(Base):
    """LLM 供应商健康检查日志 ORM 模型，对应 ``kb_llm_health_log`` 表。

    Append-only，每次健康检查追加一行，用于监控面板和趋势分析。
    可定期清理（建议保留 30 天），清理脚本放 ``scripts/`` 下。

    纯追加日志表，不继承 :class:`BaseEntity`（无 ``updated_at`` / ``is_deleted`` /
    ``deleted_at``），仅保留 ``id`` + ``created_at``（见 §7.1 例外说明）。
    """

    __tablename__ = "kb_llm_health_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_success: Mapped[bool] = mapped_column(Integer, nullable=False)
    error_msg: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=datetime.utcnow
    )
