"""LLM 供应商管理模块。

提供多 LLM 供应商的统一管理、路由、健康检查和模型发现能力。
基于 LiteLLM 封装，支持 OpenAI / DeepSeek / Ark / Qwen / Ollama / llama.cpp 等。

子模块：
    - ``orm``: SQLAlchemy ORM 模型（kb_llm_provider / kb_llm_model / kb_llm_health_log）
    - ``schemas``: Pydantic 请求/响应模型（前端 API 层校验）
    - ``crypto``: API Key 加解密工具
    - ``client``: LiteLLM 封装，统一 LLM 调用入口
    - ``router``: 供应商路由，按优先级 + 健康状态选择可用供应商
    - ``health``: 健康检查服务，类熔断器状态机 + 日志记录
    - ``service``: 供应商/模型 CRUD + 模型发现服务
"""

from src.llm.client import chat_completion
from src.llm.orm import LlmHealthLog, LlmModel, LlmProvider
from src.llm.router import select_first_available
from src.llm.schemas import (
    DiscoveredModel,
    HealthLogResponse,
    ModelCreate,
    ModelResponse,
    ModelUpdate,
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)
from src.llm.service import (
    create_model,
    create_provider,
    delete_model,
    delete_provider,
    discover_models,
    get_provider,
    list_models,
    list_providers,
    update_model,
    update_provider,
)

__all__ = [
    "DiscoveredModel",
    "HealthLogResponse",
    "LlmHealthLog",
    "LlmModel",
    "LlmProvider",
    "ModelCreate",
    "ModelResponse",
    "ModelUpdate",
    "ProviderCreate",
    "ProviderResponse",
    "ProviderUpdate",
    "chat_completion",
    "create_model",
    "create_provider",
    "delete_model",
    "delete_provider",
    "discover_models",
    "get_provider",
    "list_models",
    "list_providers",
    "select_first_available",
    "update_model",
    "update_provider",
]
