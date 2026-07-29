"""src.llm.metadata_extractor 的单元测试。

测试覆盖：
- ModelMetadata dataclass 默认值
- ArkModelMetadataExtractor: token_limits / features / modalities 解析
- OllamaModelMetadataExtractor: /api/show 调用 + model_info / capabilities 解析
- LlamaCppModelMetadataExtractor: meta.n_ctx 解析
- OpenAICompatModelMetadataExtractor: 返回全 None
- get_metadata_extractor: 按 litellm_provider / base_url 分派
- merge_metadata: 优先级合并 API > LiteLLM > 默认值
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.llm.metadata_extractor import (
    ArkModelMetadataExtractor,
    LlamaCppModelMetadataExtractor,
    ModelMetadata,
    OllamaModelMetadataExtractor,
    OpenAICompatModelMetadataExtractor,
    get_metadata_extractor,
    merge_metadata,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_provider(
    *,
    litellm_provider: str = "openai",
    base_url: str = "https://api.example.com/v1",
    timeout_seconds: int = 30,
) -> MagicMock:
    """构造 provider mock。"""
    p = MagicMock()
    p.litellm_provider = litellm_provider
    p.base_url = base_url
    p.timeout_seconds = timeout_seconds
    return p


def _mock_response(
    status: int = 200,
    json_data: dict[str, Any] | None = None,
) -> httpx.Response:
    """构造带 request 的 httpx.Response（raise_for_status 需要 request）。"""
    req = httpx.Request("POST", "http://localhost:11434/api/show")
    return httpx.Response(status, json=json_data or {}, request=req)


# ---------------------------------------------------------------------------
# ModelMetadata dataclass
# ---------------------------------------------------------------------------


class TestModelMetadata:
    """ModelMetadata dataclass 测试。"""

    def test_defaults_all_none(self) -> None:
        """默认构造所有字段为 None。"""
        meta = ModelMetadata()
        assert meta.context_window is None
        assert meta.max_output_tokens is None
        assert meta.supports_function_calling is None
        assert meta.supports_vision is None
        assert meta.supports_reasoning is None
        assert meta.supports_streaming is None

    def test_frozen(self) -> None:
        """frozen=True，不可变。"""
        meta = ModelMetadata(context_window=4096)
        with pytest.raises(AttributeError):
            meta.context_window = 8192  # type: ignore[misc]

    def test_partial(self) -> None:
        """部分赋值。"""
        meta = ModelMetadata(context_window=128000, supports_vision=True)
        assert meta.context_window == 128000
        assert meta.supports_vision is True
        assert meta.max_output_tokens is None


# ---------------------------------------------------------------------------
# ArkModelMetadataExtractor
# ---------------------------------------------------------------------------


class TestArkModelMetadataExtractor:
    """ARK 系提取器测试。"""

    def test_full_metadata(self) -> None:
        """完整富字段响应。"""
        raw: dict[str, Any] = {
            "id": "glm-5-2-260617",
            "token_limits": {
                "context_window": 1048576,
                "max_input_token_length": 1048576,
                "max_output_token_length": 131072,
                "max_reasoning_token_length": 131072,
            },
            "features": {
                "tools": {"function_calling": True},
                "structured_outputs": {"json_object": True, "json_schema": False},
            },
            "modalities": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        extractor = ArkModelMetadataExtractor()
        meta = extractor.extract(raw, provider, {})

        assert meta.context_window == 1048576
        assert meta.max_output_tokens == 131072
        assert meta.supports_function_calling is True
        assert meta.supports_vision is True
        assert meta.supports_reasoning is True
        assert meta.supports_streaming is None

    def test_no_reasoning_tokens(self) -> None:
        """max_reasoning_token_length 不存在 -> supports_reasoning=None（未知）。"""
        raw: dict[str, Any] = {
            "id": "doubao-pro-32k",
            "token_limits": {
                "context_window": 32768,
                "max_input_token_length": 32768,
                "max_output_token_length": 16384,
            },
            "features": {"tools": {"function_calling": True}},
            "modalities": {"input_modalities": ["text"]},
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})

        assert meta.context_window == 32768
        assert meta.max_output_tokens == 16384
        assert meta.supports_function_calling is True
        assert meta.supports_vision is False
        assert meta.supports_reasoning is None

    def test_reasoning_tokens_zero(self) -> None:
        """max_reasoning_token_length=0 -> supports_reasoning=False。"""
        raw: dict[str, Any] = {
            "id": "model-x",
            "token_limits": {
                "context_window": 4096,
                "max_output_token_length": 2048,
                "max_reasoning_token_length": 0,
            },
            "features": {},
            "modalities": {},
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.supports_reasoning is False

    def test_empty_response(self) -> None:
        """空字段响应。"""
        raw: dict[str, Any] = {"id": "model-x"}
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.context_window is None
        assert meta.max_output_tokens is None
        assert meta.supports_function_calling is None
        assert meta.supports_vision is None
        assert meta.supports_reasoning is None

    def test_missing_token_limits(self) -> None:
        """无 token_limits 字段。"""
        raw: dict[str, Any] = {
            "id": "model-x",
            "features": {"tools": {"function_calling": False}},
            "modalities": {"input_modalities": ["text"]},
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.context_window is None
        assert meta.max_output_tokens is None
        assert meta.supports_function_calling is False
        assert meta.supports_vision is False
        assert meta.supports_reasoning is None

    def test_vision_from_image_modality(self) -> None:
        """input_modalities 含 image -> supports_vision=True。"""
        raw: dict[str, Any] = {
            "id": "model-vision",
            "modalities": {"input_modalities": ["image", "text"]},
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.supports_vision is True

    def test_no_modalities(self) -> None:
        """无 modalities 字段 -> supports_vision=None。"""
        raw: dict[str, Any] = {"id": "model-x", "features": {}}
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.supports_vision is None


# ---------------------------------------------------------------------------
# OllamaModelMetadataExtractor
# ---------------------------------------------------------------------------


class TestOllamaModelMetadataExtractor:
    """Ollama 提取器测试。"""

    def test_successful_extraction(self) -> None:
        """正常调 /api/show 提取 context_length + capabilities。"""
        raw: dict[str, Any] = {"model": "qwen3.5:9b", "name": "qwen3.5:9b"}
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )

        show_response = {
            "model_info": {
                "qwen35.context_length": 262144,
                "general.architecture": "qwen35",
            },
            "capabilities": ["completion", "vision", "tools", "thinking"],
        }

        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(
                raw, provider, {}
            )

        assert meta.context_window == 262144
        assert meta.supports_function_calling is True
        assert meta.supports_vision is True
        assert meta.supports_reasoning is True
        assert meta.max_output_tokens is None

    def test_base_url_strips_v1_suffix(self) -> None:
        """base_url 末尾 /v1 被移除后拼接 /api/show。"""
        raw: dict[str, Any] = {"model": "test:latest"}
        provider = _make_provider(
            base_url="http://localhost:11434/v1"
        )

        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"model_info": {}, "capabilities": []}
            )
            OllamaModelMetadataExtractor().extract(raw, provider, {})

        called_url = mock_post.call_args.args[0]
        assert called_url == "http://localhost:11434/api/show"

    def test_context_length_by_family_prefix(self) -> None:
        """不同 family 前缀的 context_length 键都能匹配。"""
        raw: dict[str, Any] = {"model": "bge-m3:latest"}
        provider = _make_provider(base_url="http://localhost:11434/v1")

        show_response = {
            "model_info": {"bert.context_length": 8192},
            "capabilities": ["embedding"],
        }

        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(
                raw, provider, {}
            )

        assert meta.context_window == 8192
        assert meta.supports_function_calling is False
        assert meta.supports_vision is False
        assert meta.supports_reasoning is False

    def test_empty_model_name(self) -> None:
        """无 model/name 字段 -> 返回空 metadata。"""
        raw: dict[str, Any] = {}
        provider = _make_provider(base_url="http://localhost:11434/v1")
        meta = OllamaModelMetadataExtractor().extract(raw, provider, {})
        assert meta.context_window is None

    def test_api_show_failure(self) -> None:
        """/api/show 请求失败 -> 返回空 metadata，不抛异常。"""
        raw: dict[str, Any] = {"model": "test:latest"}
        provider = _make_provider(base_url="http://localhost:11434/v1")

        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(500)
            meta = OllamaModelMetadataExtractor().extract(
                raw, provider, {}
            )

        assert meta.context_window is None
        assert meta.supports_function_calling is None

    def test_no_capabilities(self) -> None:
        """capabilities 为空列表。"""
        raw: dict[str, Any] = {"model": "test:latest"}
        provider = _make_provider(base_url="http://localhost:11434/v1")

        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(
                200,
                {"model_info": {"test.context_length": 4096}, "capabilities": []},
            )
            meta = OllamaModelMetadataExtractor().extract(
                raw, provider, {}
            )

        assert meta.context_window == 4096
        assert meta.supports_function_calling is False
        assert meta.supports_vision is False
        assert meta.supports_reasoning is False


# ---------------------------------------------------------------------------
# LlamaCppModelMetadataExtractor
# ---------------------------------------------------------------------------


class TestLlamaCppModelMetadataExtractor:
    """llama.cpp 提取器测试。"""

    def test_extract_n_ctx(self) -> None:
        """从 meta.n_ctx 提取上下文窗口。"""
        raw: dict[str, Any] = {
            "id": "test-model",
            "meta": {"n_ctx": 4096, "n_vocab": 32000, "n_params": 7000000000},
        }
        provider = _make_provider()
        meta = LlamaCppModelMetadataExtractor().extract(raw, provider, {})
        assert meta.context_window == 4096
        assert meta.max_output_tokens is None
        assert meta.supports_function_calling is None

    def test_no_meta(self) -> None:
        """无 meta 字段。"""
        raw: dict[str, Any] = {"id": "test-model"}
        meta = LlamaCppModelMetadataExtractor().extract(
            raw, _make_provider(), {}
        )
        assert meta.context_window is None

    def test_no_n_ctx(self) -> None:
        """meta 中无 n_ctx。"""
        raw: dict[str, Any] = {"id": "test-model", "meta": {"n_vocab": 32000}}
        meta = LlamaCppModelMetadataExtractor().extract(
            raw, _make_provider(), {}
        )
        assert meta.context_window is None


# ---------------------------------------------------------------------------
# OpenAICompatModelMetadataExtractor
# ---------------------------------------------------------------------------


class TestOpenAICompatModelMetadataExtractor:
    """OpenAI 兼容提取器测试。"""

    def test_returns_all_none(self) -> None:
        """始终返回全 None metadata。"""
        raw: dict[str, Any] = {
            "id": "deepseek-chat",
            "object": "model",
            "owned_by": "deepseek",
        }
        meta = OpenAICompatModelMetadataExtractor().extract(
            raw, _make_provider(), {}
        )
        assert meta.context_window is None
        assert meta.max_output_tokens is None
        assert meta.supports_function_calling is None
        assert meta.supports_vision is None
        assert meta.supports_reasoning is None
        assert meta.supports_streaming is None


# ---------------------------------------------------------------------------
# get_metadata_extractor
# ---------------------------------------------------------------------------


class TestGetMetadataExtractor:
    """工厂函数测试。"""

    def test_ark_by_base_url(self) -> None:
        """base_url 含 ark -> ArkModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="openai",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        assert isinstance(
            get_metadata_extractor(provider), ArkModelMetadataExtractor
        )

    def test_ark_coding_plan(self) -> None:
        """ark-coding-plan 也匹配。"""
        provider = _make_provider(
            litellm_provider="openai",
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        )
        assert isinstance(
            get_metadata_extractor(provider), ArkModelMetadataExtractor
        )

    def test_ollama(self) -> None:
        """litellm_provider=ollama -> OllamaModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )
        assert isinstance(
            get_metadata_extractor(provider), OllamaModelMetadataExtractor
        )

    def test_llamacpp(self) -> None:
        """litellm_provider=llamacpp -> LlamaCppModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="llamacpp",
            base_url="http://localhost:8080/v1",
        )
        assert isinstance(
            get_metadata_extractor(provider), LlamaCppModelMetadataExtractor
        )

    def test_deepseek_openai_compat(self) -> None:
        """DeepSeek -> OpenAICompatModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="openai",
            base_url="https://api.deepseek.com/v1",
        )
        assert isinstance(
            get_metadata_extractor(provider),
            OpenAICompatModelMetadataExtractor,
        )

    def test_qwen_openai_compat(self) -> None:
        """Qwen -> OpenAICompatModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="openai",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        assert isinstance(
            get_metadata_extractor(provider),
            OpenAICompatModelMetadataExtractor,
        )

    def test_unknown_provider_fallback(self) -> None:
        """未知 litellm_provider -> OpenAICompatModelMetadataExtractor。"""
        provider = _make_provider(
            litellm_provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1",
        )
        assert isinstance(
            get_metadata_extractor(provider),
            OpenAICompatModelMetadataExtractor,
        )


# ---------------------------------------------------------------------------
# merge_metadata
# ---------------------------------------------------------------------------


class TestMergeMetadata:
    """优先级合并测试。"""

    def test_api_takes_priority(self) -> None:
        """API 值优先于 LiteLLM 注册表。"""
        api_meta = ModelMetadata(
            context_window=1048576,
            max_output_tokens=131072,
            supports_function_calling=True,
            supports_vision=True,
            supports_reasoning=True,
        )
        litellm_info: dict[str, Any] = {
            "max_input_tokens": 4096,
            "max_output_tokens": 2048,
            "supports_function_calling": False,
            "supports_vision": False,
            "supports_reasoning": False,
        }
        merged = merge_metadata(api_meta, litellm_info)
        assert merged["context_window"] == 1048576
        assert merged["max_output_tokens"] == 131072
        assert merged["supports_function_calling"] is True
        assert merged["supports_vision"] is True
        assert merged["supports_reasoning"] is True

    def test_litellm_fills_api_gaps(self) -> None:
        """API None 的字段由 LiteLLM 注册表补全。"""
        api_meta = ModelMetadata(
            context_window=8192,
            supports_function_calling=True,
        )
        litellm_info: dict[str, Any] = {
            "max_input_tokens": 4096,
            "max_output_tokens": 2048,
            "supports_function_calling": False,
            "supports_vision": True,
            "supports_reasoning": False,
            "supports_streaming": False,
        }
        merged = merge_metadata(api_meta, litellm_info)
        assert merged["context_window"] == 8192
        assert merged["max_output_tokens"] == 2048
        assert merged["supports_function_calling"] is True
        assert merged["supports_vision"] is True
        assert merged["supports_reasoning"] is False
        assert merged["supports_streaming"] is False

    def test_defaults_when_both_missing(self) -> None:
        """API 和 LiteLLM 都无值 -> 默认值。"""
        api_meta = ModelMetadata()
        litellm_info: dict[str, Any] = {}
        merged = merge_metadata(api_meta, litellm_info)
        assert merged["context_window"] == 4096
        assert merged["max_output_tokens"] == 4096
        assert merged["supports_streaming"] is True
        assert merged["supports_function_calling"] is False
        assert merged["supports_vision"] is False
        assert merged["supports_reasoning"] is False

    def test_empty_api_and_empty_litellm(self) -> None:
        """两者都空 -> 全默认值。"""
        merged = merge_metadata(ModelMetadata(), {})
        assert merged["context_window"] == 4096
        assert merged["max_output_tokens"] == 4096
        assert merged["supports_streaming"] is True

    def test_api_none_litellm_present(self) -> None:
        """API None，LiteLLM 有值 -> 用 LiteLLM 值。"""
        api_meta = ModelMetadata()
        litellm_info: dict[str, Any] = {
            "max_input_tokens": 32768,
            "max_output_tokens": 8192,
            "supports_streaming": False,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": True,
        }
        merged = merge_metadata(api_meta, litellm_info)
        assert merged["context_window"] == 32768
        assert merged["max_output_tokens"] == 8192
        assert merged["supports_streaming"] is False
        assert merged["supports_function_calling"] is True
        assert merged["supports_vision"] is True
        assert merged["supports_reasoning"] is True

    def test_partial_api_overrides_partial_litellm(self) -> None:
        """部分 API 值覆盖部分 LiteLLM 值。"""
        api_meta = ModelMetadata(
            context_window=128000,
            supports_reasoning=True,
        )
        litellm_info: dict[str, Any] = {
            "max_input_tokens": 4096,
            "max_output_tokens": 8192,
            "supports_function_calling": True,
            "supports_reasoning": False,
            "supports_streaming": True,
        }
        merged = merge_metadata(api_meta, litellm_info)
        assert merged["context_window"] == 128000
        assert merged["max_output_tokens"] == 8192
        assert merged["supports_function_calling"] is True
        assert merged["supports_reasoning"] is True
        assert merged["supports_streaming"] is True

    def test_task_type_from_api(self) -> None:
        """task_type 从 API 提取。"""
        api_meta = ModelMetadata(task_type=["TextGeneration"])
        merged = merge_metadata(api_meta, {})
        assert merged["task_type"] == ["TextGeneration"]

    def test_task_type_none_when_api_missing(self) -> None:
        """API 无 task_type -> None。"""
        merged = merge_metadata(ModelMetadata(), {})
        assert merged["task_type"] is None


# ---------------------------------------------------------------------------
# task_type extraction
# ---------------------------------------------------------------------------


class TestTaskTypeExtraction:
    """task_type 提取测试。"""

    def test_ark_with_task_type(self) -> None:
        """ARK 响应含 task_type 数组。"""
        raw: dict[str, Any] = {
            "id": "doubao-pro-32k",
            "task_type": ["TextGeneration"],
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type == ["TextGeneration"]

    def test_ark_with_multiple_task_types(self) -> None:
        """ARK 多任务类型。"""
        raw: dict[str, Any] = {
            "id": "doubao-vision-pro",
            "task_type": ["VisualQuestionAnswering", "TextGeneration"],
        }
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type == ["VisualQuestionAnswering", "TextGeneration"]

    def test_ark_no_task_type(self) -> None:
        """ARK 无 task_type 字段 -> None。"""
        raw: dict[str, Any] = {"id": "model-x"}
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type is None

    def test_ark_task_type_not_list(self) -> None:
        """task_type 非数组 -> None。"""
        raw: dict[str, Any] = {"id": "model-x", "task_type": "TextGeneration"}
        provider = _make_provider(base_url="https://ark.example.com/api/v3")
        meta = ArkModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type is None

    def test_ollama_completion_caps(self) -> None:
        """Ollama completion -> TextGeneration。"""
        raw: dict[str, Any] = {"model": "test:latest"}
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )
        show_response: dict[str, Any] = {
            "model_info": {"test.context_length": 8192},
            "capabilities": ["completion"],
        }
        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(raw, provider, {})

        assert meta.task_type == ["TextGeneration"]

    def test_ollama_embedding_caps(self) -> None:
        """Ollama embedding -> TextEmbedding。"""
        raw: dict[str, Any] = {"model": "bge-m3:latest"}
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )
        show_response: dict[str, Any] = {
            "model_info": {"bert.context_length": 8192},
            "capabilities": ["embedding"],
        }
        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(raw, provider, {})

        assert meta.task_type == ["TextEmbedding"]

    def test_ollama_vision_caps(self) -> None:
        """Ollama vision+tools+thinking -> 多 task_type（去重）。"""
        raw: dict[str, Any] = {"model": "qwen3.5:9b"}
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )
        show_response: dict[str, Any] = {
            "model_info": {"qwen35.context_length": 262144},
            "capabilities": ["completion", "vision", "tools", "thinking"],
        }
        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(raw, provider, {})

        assert meta.task_type == [
            "TextGeneration",
            "VisualQuestionAnswering",
        ]

    def test_ollama_no_capabilities(self) -> None:
        """Ollama 无 capabilities -> task_type=None。"""
        raw: dict[str, Any] = {"model": "test:latest"}
        provider = _make_provider(
            litellm_provider="ollama",
            base_url="http://localhost:11434/v1",
        )
        show_response: dict[str, Any] = {
            "model_info": {"test.context_length": 4096},
        }
        with patch("src.llm.metadata_extractor.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, show_response)
            meta = OllamaModelMetadataExtractor().extract(raw, provider, {})

        assert meta.task_type is None

    def test_llamacpp_no_task_type(self) -> None:
        """llama.cpp 不返回 task_type。"""
        raw: dict[str, Any] = {"id": "test", "meta": {"n_ctx": 4096}}
        provider = _make_provider(
            litellm_provider="llamacpp",
            base_url="http://localhost:8080/v1",
        )
        meta = LlamaCppModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type is None

    def test_openai_compat_no_task_type(self) -> None:
        """OpenAI 兼容不返回 task_type。"""
        raw: dict[str, Any] = {"id": "deepseek-chat"}
        provider = _make_provider(
            litellm_provider="openai",
            base_url="https://api.deepseek.com/v1",
        )
        meta = OpenAICompatModelMetadataExtractor().extract(raw, provider, {})
        assert meta.task_type is None
