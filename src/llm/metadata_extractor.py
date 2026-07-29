"""模型元数据提取器 -- 策略模式。

不同供应商的 ``/models`` 响应结构差异较大：

+----------+--------------------------+-------------------------------------------+
| 供应商   | 字段来源                 | 示例                                      |
+==========+==========================+===========================================+
| ARK 系   | 内联 token_limits /      | {"token_limits": {"context_window": ...}, |
|          | features / modalities    |  "features": {"tools": {...}}}            |
+----------+--------------------------+-------------------------------------------+
| Ollama   | POST /api/show 返回      | {"model_info": {"qwen3.context_length":   |
|          | model_info / capabilities|  262144}, "capabilities": ["tools"]}      |
+----------+--------------------------+-------------------------------------------+
| llama.cpp| /models 内联 meta.n_ctx  | {"meta": {"n_ctx": 4096}}                 |
+----------+--------------------------+-------------------------------------------+
| DeepSeek | 仅 id / object / owned_by| API 无富字段，回退 LiteLLM 注册表          |
| Qwen     |                          |                                           |
+----------+--------------------------+-------------------------------------------+

每个提取器返回 :class:`ModelMetadata`（所有字段 ``Optional``），
``None`` 表示 API 未提供该字段，由 ``discover_models`` 按
**API > LiteLLM 注册表 > 默认值** 的优先级合并。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.llm.orm import LlmProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelMetadata:
    """从供应商 API 提取的模型元数据。

    所有字段均为 ``Optional``，``None`` 表示该供应商 API 未提供此信息，
    由调用方按优先级回退到 LiteLLM 注册表或默认值。

    Attributes:
        context_window: 上下文窗口大小（tokens）。
        max_output_tokens: 最大输出 tokens。
        supports_function_calling: 是否支持函数调用。
        supports_vision: 是否支持视觉/多模态。
        supports_reasoning: 是否为推理模型。
        supports_streaming: 是否支持流式输出。
        task_type: 任务类型列表，如 ``["TextGeneration"]``。
    """

    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_function_calling: bool | None = None
    supports_vision: bool | None = None
    supports_reasoning: bool | None = None
    supports_streaming: bool | None = None
    task_type: list[str] | None = None


class ModelMetadataExtractor(ABC):
    """模型元数据提取器抽象基类（策略模式）。

    每个子类对应一种供应商的 ``/models`` 响应格式，
    从中提取归一化的 :class:`ModelMetadata`。
    """

    @abstractmethod
    def extract(
        self,
        raw_model: dict[str, Any],
        provider: LlmProvider,
        headers: dict[str, str],
    ) -> ModelMetadata:
        """从单个模型的原始响应中提取元数据。

        Args:
            raw_model: ``/models`` 响应中单个模型对象。
            provider: 供应商 ORM 对象。
            headers: 已构造的鉴权 headers（部分供应商需额外请求）。

        Returns:
            :class:`ModelMetadata` 实例，未提供的字段为 ``None``。
        """


class ArkModelMetadataExtractor(ModelMetadataExtractor):
    """ARK 系提取器 -- 从 ``token_limits`` / ``features`` / ``modalities`` 解析。

    适用于 ark / ark-plan / ark-coding-plan 等火山引擎系列供应商。
    响应中的富字段内联在 ``/models`` 列表里，无需额外请求。
    """

    def extract(
        self,
        raw_model: dict[str, Any],
        provider: LlmProvider,
        headers: dict[str, str],
    ) -> ModelMetadata:
        token_limits = raw_model.get("token_limits") or {}
        features = raw_model.get("features") or {}
        modalities = raw_model.get("modalities") or {}

        context_window = _get_int(token_limits, "context_window")
        max_output_tokens = _get_int(token_limits, "max_output_token_length")

        # reasoning: 有 max_reasoning_token_length 且 > 0
        max_reasoning = _get_int(token_limits, "max_reasoning_token_length")
        supports_reasoning: bool | None = None
        if max_reasoning is not None:
            supports_reasoning = max_reasoning > 0

        # function_calling: features.tools.function_calling
        tools = features.get("tools") or {}
        supports_function_calling = _get_bool(tools, "function_calling")

        # vision: input_modalities 含 "image"
        input_mods = modalities.get("input_modalities") or []
        supports_vision: bool | None = None
        if input_mods:
            supports_vision = "image" in input_mods

        # task_type: ARK 直接返回数组
        raw_task_type = raw_model.get("task_type")
        task_type = (
            [str(t) for t in raw_task_type]
            if isinstance(raw_task_type, list)
            else None
        )

        return ModelMetadata(
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            supports_function_calling=supports_function_calling,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            supports_streaming=None,
            task_type=task_type,
        )


class OllamaModelMetadataExtractor(ModelMetadataExtractor):
    """Ollama 提取器 -- 调 ``POST /api/show`` 获取模型详情。

    ``/api/tags`` 仅返回基础信息（name / size），无上下文窗口等。
    需对每个模型额外调 ``POST /api/show`` 获取 ``model_info`` 和
    ``capabilities``。

    ``model_info`` 中的 context_length 键名按模型 family 前缀变化
    （如 ``qwen3.context_length`` / ``bert.context_length``），
    通过后缀匹配 ``.context_length`` 提取。
    """

    def extract(
        self,
        raw_model: dict[str, Any],
        provider: LlmProvider,
        headers: dict[str, str],
    ) -> ModelMetadata:
        model_name = raw_model.get("model") or raw_model.get("name") or ""
        if not model_name:
            return ModelMetadata()

        base_url = provider.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        try:
            resp = httpx.post(
                f"{base_url}/api/show",
                json={"name": model_name},
                timeout=provider.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug(
                "Ollama /api/show 失败: model=%s error=%s",
                model_name,
                exc,
            )
            return ModelMetadata()

        info = resp.json()
        model_info = info.get("model_info") or {}

        # context_length: 键名格式为 "{family}.context_length"
        context_window: int | None = None
        for key, val in model_info.items():
            if key.endswith(".context_length") and isinstance(val, int):
                context_window = val
                break

        raw_caps = info.get("capabilities")
        if raw_caps is not None:
            supports_function_calling = "tools" in raw_caps
            supports_vision = "vision" in raw_caps
            supports_reasoning = "thinking" in raw_caps
            # Ollama capabilities -> task_type 映射
            task_type = _ollama_caps_to_task_type(raw_caps)
        else:
            supports_function_calling = None
            supports_vision = None
            supports_reasoning = None
            task_type = None

        return ModelMetadata(
            context_window=context_window,
            max_output_tokens=None,
            supports_function_calling=supports_function_calling,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            supports_streaming=None,
            task_type=task_type,
        )


class LlamaCppModelMetadataExtractor(ModelMetadataExtractor):
    """llama.cpp 提取器 -- 从 ``meta.n_ctx`` 解析上下文窗口。

    ``/models`` 返回的 ``meta`` 字段包含 ``n_ctx``（运行时上下文长度），
    但不包含 capabilities 信息。
    """

    def extract(
        self,
        raw_model: dict[str, Any],
        provider: LlmProvider,
        headers: dict[str, str],
    ) -> ModelMetadata:
        meta = raw_model.get("meta") or {}
        context_window = _get_int(meta, "n_ctx")

        return ModelMetadata(
            context_window=context_window,
            max_output_tokens=None,
            supports_function_calling=None,
            supports_vision=None,
            supports_reasoning=None,
            supports_streaming=None,
        )


class OpenAICompatModelMetadataExtractor(ModelMetadataExtractor):
    """OpenAI 兼容提取器 -- DeepSeek / Qwen 等。

    这些供应商的 ``/models`` 仅返回 ``id`` / ``object`` / ``owned_by``，
    不含元数据富字段。返回全 ``None``，由调用方回退到 LiteLLM 注册表。
    """

    def extract(
        self,
        raw_model: dict[str, Any],
        provider: LlmProvider,
        headers: dict[str, str],
    ) -> ModelMetadata:
        return ModelMetadata()


_EXTRACTORS: dict[str, ModelMetadataExtractor] = {
    "openai": OpenAICompatModelMetadataExtractor(),
    "ollama": OllamaModelMetadataExtractor(),
    "llamacpp": LlamaCppModelMetadataExtractor(),
}


def get_metadata_extractor(provider: LlmProvider) -> ModelMetadataExtractor:
    """根据供应商的 ``litellm_provider`` 返回对应的元数据提取器。

    ARK 系供应商的 ``litellm_provider`` 为 ``openai``，但其响应包含
    ``token_limits`` 等富字段，通过检测 ``base_url`` 中的 ``ark`` 标识
    区分。

    Args:
        provider: 供应商 ORM 对象。

    Returns:
        :class:`ModelMetadataExtractor` 实例。
    """
    # ARK 系: litellm_provider=openai 但 base_url 含 ark
    if "ark" in provider.base_url.lower():
        return ArkModelMetadataExtractor()

    extractor = _EXTRACTORS.get(provider.litellm_provider)
    if extractor is not None:
        return extractor

    logger.debug(
        "未知 litellm_provider=%s，使用 OpenAI 兼容提取器",
        provider.litellm_provider,
    )
    return _EXTRACTORS["openai"]


def merge_metadata(
    api_meta: ModelMetadata,
    litellm_info: dict[str, Any],
) -> dict[str, Any]:
    """按优先级合并 API 元数据与 LiteLLM 注册表数据。

    优先级：API 响应 > LiteLLM 注册表 > 默认值。

    Args:
        api_meta: 从供应商 API 提取的元数据。
        litellm_info: LiteLLM 注册表中该模型的信息。

    Returns:
        合并后的字段字典，可直接传给 :class:`DiscoveredModel` 构造。
    """
    def pick(api_val: Any, litellm_key: str, default: Any) -> Any:
        if api_val is not None:
            return api_val
        return litellm_info.get(litellm_key, default)

    return {
        "context_window": pick(
            api_meta.context_window, "max_input_tokens", 4096
        ),
        "max_output_tokens": pick(
            api_meta.max_output_tokens, "max_output_tokens", 4096
        ),
        "supports_streaming": pick(
            api_meta.supports_streaming, "supports_streaming", True
        ),
        "supports_function_calling": pick(
            api_meta.supports_function_calling,
            "supports_function_calling",
            False,
        ),
        "supports_vision": pick(
            api_meta.supports_vision, "supports_vision", False
        ),
        "supports_reasoning": pick(
            api_meta.supports_reasoning, "supports_reasoning", False
        ),
        "task_type": api_meta.task_type,
    }


def _get_int(obj: dict[str, Any], key: str) -> int | None:
    """从字典中安全提取整数值。

    Args:
        obj: 字典对象。
        key: 字段名。

    Returns:
        整数值，不存在或非整数时返回 None。
    """
    val = obj.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _get_bool(obj: dict[str, Any], key: str) -> bool | None:
    """从字典中安全提取布尔值。

    Args:
        obj: 字典对象。
        key: 字段名。

    Returns:
        布尔值，不存在时返回 None。
    """
    val = obj.get(key)
    if val is None:
        return None
    return bool(val)


_OLLAMA_CAPS_TO_TASK_TYPE: dict[str, str] = {
    "completion": "TextGeneration",
    "embedding": "TextEmbedding",
    "vision": "VisualQuestionAnswering",
    "tools": "TextGeneration",
    "thinking": "TextGeneration",
}


def _ollama_caps_to_task_type(caps: list[str]) -> list[str]:
    """将 Ollama capabilities 映射为 ARK 风格 task_type。

    Ollama capabilities: completion / embedding / vision / tools / thinking / audio

    映射规则:
        - completion -> TextGeneration
        - embedding  -> TextEmbedding
        - vision     -> VisualQuestionAnswering
        - tools/thinking -> 归入 TextGeneration（LLM 能力子集）
        - audio      -> SpeechToText（如有）

    多个 capability 会映射为多个 task_type（去重）。

    Args:
        caps: Ollama ``/api/show`` 返回的 capabilities 列表。

    Returns:
        映射后的 task_type 列表（去重，保序）。空输入返回 ``["TextGeneration"]``
        作为默认值。
    """
    if not caps:
        return ["TextGeneration"]

    result: list[str] = []
    seen: set[str] = set()
    for cap in caps:
        mapped = _OLLAMA_CAPS_TO_TASK_TYPE.get(cap)
        if mapped and mapped not in seen:
            result.append(mapped)
            seen.add(mapped)

    return result if result else ["TextGeneration"]


__all__ = [
    "ArkModelMetadataExtractor",
    "LlamaCppModelMetadataExtractor",
    "ModelMetadata",
    "ModelMetadataExtractor",
    "OpenAICompatModelMetadataExtractor",
    "OllamaModelMetadataExtractor",
    "get_metadata_extractor",
    "merge_metadata",
]
