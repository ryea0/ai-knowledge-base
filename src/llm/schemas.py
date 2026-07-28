"""LLM 供应商管理 Pydantic 请求/响应模型。

用于前端 API 层校验，与 :mod:`src.llm.orm` 的 ORM 模型对应但不耦合。
ORM -> Schema 转换在 :mod:`src.llm.service` 中完成。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.json_config import JsonDateTime
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmModelSource,
    LlmProviderType,
)


class ProviderBase(BaseModel):
    """供应商创建/更新的公共字段。"""

    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(..., min_length=1, max_length=40, description="供应商代码")
    display_name: str = Field(..., min_length=1, max_length=80, description="展示名称")
    provider_type: LlmProviderType = Field(
        default=LlmProviderType.CLOUD, description="供应商类型 cloud/local"
    )
    base_url: str = Field(..., min_length=1, max_length=255, description="API 基础 URL")
    litellm_provider: str = Field(
        ..., min_length=1, max_length=40, description="LiteLLM 供应商标识"
    )
    auth_type: LlmAuthType = Field(
        default=LlmAuthType.BEARER, description="鉴权方式 bearer/oauth/header/none"
    )
    auth_config: dict[str, Any] | None = Field(
        None, description="鉴权附加配置，结构由 auth_type 决定"
    )
    is_enabled: bool = Field(True, description="是否启用")
    priority: int = Field(100, ge=0, description="路由优先级，数值越小越高")
    timeout_seconds: int = Field(30, ge=1, le=600, description="请求超时秒数")
    max_retries: int = Field(3, ge=0, le=10, description="最大重试次数")
    rpm_limit: int = Field(0, ge=0, description="每分钟请求上限，0=不限速")
    health_check_enabled: bool = Field(True, description="是否启用健康检查")
    failure_threshold: int = Field(5, ge=1, le=100, description="连续失败转 unhealthy 阈值")


class ProviderCreate(ProviderBase):
    """创建供应商请求。"""

    api_key: str | None = Field(
        None, description="明文 API Key（创建时传入，服务端加密存储，不返回）"
    )


class ProviderUpdate(BaseModel):
    """更新供应商请求（所有字段可选）。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=80)
    base_url: str | None = Field(None, min_length=1, max_length=255)
    litellm_provider: str | None = Field(None, min_length=1, max_length=40)
    auth_type: LlmAuthType | None = None
    api_key: str | None = Field(
        None, description="明文 API Key，传入则更新加密凭证，None 表示不修改"
    )
    auth_config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    priority: int | None = Field(None, ge=0)
    timeout_seconds: int | None = Field(None, ge=1, le=600)
    max_retries: int | None = Field(None, ge=0, le=10)
    rpm_limit: int | None = Field(None, ge=0)
    health_check_enabled: bool | None = None
    failure_threshold: int | None = Field(None, ge=1, le=100)


class ProviderResponse(BaseModel):
    """供应商响应（不含 API Key）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_code: str
    display_name: str
    provider_type: LlmProviderType
    base_url: str
    litellm_provider: str
    auth_type: LlmAuthType
    auth_config: dict[str, Any] | None
    is_enabled: bool
    priority: int
    timeout_seconds: int
    max_retries: int
    rpm_limit: int
    health_status: LlmHealthStatus
    health_check_enabled: bool
    last_check_at: JsonDateTime | None
    last_success_at: JsonDateTime | None
    last_failure_at: JsonDateTime | None
    consecutive_failures: int
    failure_threshold: int
    last_error: str | None
    is_deleted: bool
    deleted_at: JsonDateTime | None
    created_at: JsonDateTime
    updated_at: JsonDateTime


class ModelBase(BaseModel):
    """模型创建/更新的公共字段。"""

    model_config = ConfigDict(extra="forbid")

    model_code: str = Field(..., min_length=1, max_length=80, description="模型标识")
    litellm_model: str = Field(
        ..., min_length=1, max_length=120, description="LiteLLM 完整模型标识"
    )
    display_name: str = Field(..., min_length=1, max_length=120, description="展示名称")
    description: str | None = Field(None, max_length=255, description="模型描述")
    context_window: int = Field(4096, ge=1, description="上下文窗口 tokens")
    max_output_tokens: int = Field(4096, ge=1, description="最大输出 tokens")
    supports_streaming: bool = Field(True, description="是否支持流式")
    supports_function_calling: bool = Field(False, description="是否支持函数调用")
    supports_vision: bool = Field(False, description="是否支持多模态")
    input_price_per_1m: float = Field(0.0, ge=0, description="输入每百万 token 价格 USD")
    output_price_per_1m: float = Field(0.0, ge=0, description="输出每百万 token 价格 USD")
    is_enabled: bool = Field(True, description="是否启用")
    is_default: bool = Field(False, description="是否为该供应商默认模型")


class ModelCreate(ModelBase):
    """创建模型请求。"""


class ModelUpdate(BaseModel):
    """更新模型请求（所有字段可选）。"""

    model_config = ConfigDict(extra="forbid")

    litellm_model: str | None = Field(None, min_length=1, max_length=120)
    display_name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=255)
    context_window: int | None = Field(None, ge=1)
    max_output_tokens: int | None = Field(None, ge=1)
    supports_streaming: bool | None = None
    supports_function_calling: bool | None = None
    supports_vision: bool | None = None
    input_price_per_1m: float | None = Field(None, ge=0)
    output_price_per_1m: float | None = Field(None, ge=0)
    is_enabled: bool | None = None
    is_default: bool | None = None


class ModelResponse(BaseModel):
    """模型响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    model_code: str
    litellm_model: str
    display_name: str
    description: str | None
    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_function_calling: bool
    supports_vision: bool
    input_price_per_1m: float
    output_price_per_1m: float
    is_enabled: bool
    is_default: bool
    source: LlmModelSource
    is_deleted: bool
    deleted_at: JsonDateTime | None
    created_at: JsonDateTime
    updated_at: JsonDateTime


class DiscoveredModel(BaseModel):
    """模型自动发现返回的单个候选模型。"""

    model_code: str = Field(..., description="从 /v1/models 获取的模型 ID")
    litellm_model: str = Field(..., description="拼好的 LiteLLM 模型标识")
    display_name: str = Field(..., description="展示名称，默认同 model_code")
    context_window: int = Field(4096, ge=1, description="上下文窗口，来自 LiteLLM 注册表")
    max_output_tokens: int = Field(4096, ge=1, description="最大输出 tokens")
    supports_streaming: bool = Field(True, description="是否支持流式")
    supports_function_calling: bool = Field(False, description="是否支持函数调用")
    supports_vision: bool = Field(False, description="是否支持多模态")
    input_price_per_1m: float = Field(0.0, ge=0, description="输入价格，来自 LiteLLM 注册表")
    output_price_per_1m: float = Field(0.0, ge=0, description="输出价格，来自 LiteLLM 注册表")
    already_exists: bool = Field(
        False, description="DB 中已存在该 model_code，前端可跳过"
    )


class HealthLogResponse(BaseModel):
    """健康检查日志响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    model_id: int | None
    check_at: JsonDateTime
    latency_ms: int | None
    is_success: bool
    error_msg: str | None
