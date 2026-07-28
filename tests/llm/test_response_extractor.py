"""src.llm.response_extractor 的单元测试。

测试覆盖：
- StandardExtractor: content 提取（dict / 对象）
- ReasoningExtractor: content 优先，空则 reasoning_content 回退
- ThinkingBlockExtractor: thinking_blocks 拆解，content/reasoning_content 回退
- get_extractor: 按 supports_reasoning 选择策略
- extract_content: 统一入口
- 边界场景：空 choices / None message / None content
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.llm.response_extractor import (
    ReasoningExtractor,
    ResponseExtractor,
    StandardExtractor,
    ThinkingBlockExtractor,
    extract_content,
    get_extractor,
)

# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------


def _dict_response(
    content: str = "",
    reasoning_content: str | None = None,
    thinking_blocks: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """构造 dict 形态的 LiteLLM 响应。"""
    message: dict[str, object] = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    if thinking_blocks is not None:
        message["thinking_blocks"] = thinking_blocks
    return {"choices": [{"message": message}]}


def _obj_response(
    content: str = "",
    reasoning_content: str | None = None,
    thinking_blocks: list[object] | None = None,
) -> SimpleNamespace:
    """构造 Pydantic-like 对象形态的 LiteLLM 响应。"""
    msg = SimpleNamespace(content=content)
    if reasoning_content is not None:
        msg.reasoning_content = reasoning_content
    else:
        msg.reasoning_content = None
    if thinking_blocks is not None:
        msg.thinking_blocks = thinking_blocks
    else:
        msg.thinking_blocks = None
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _make_model(*, supports_reasoning: bool = False) -> MagicMock:
    """构造 model mock。"""
    model = MagicMock()
    model.supports_reasoning = supports_reasoning
    return model


# ---------------------------------------------------------------------------
# StandardExtractor 测试
# ---------------------------------------------------------------------------


class TestStandardExtractor:
    """StandardExtractor 测试。"""

    def test_extract_content_from_dict(self) -> None:
        """从 dict 提取 content。"""
        resp = _dict_response(content="hello")
        assert StandardExtractor().extract(resp) == "hello"

    def test_extract_content_from_object(self) -> None:
        """从对象提取 content。"""
        resp = _obj_response(content="world")
        assert StandardExtractor().extract(resp) == "world"

    def test_empty_content(self) -> None:
        """content 为空返回空字符串。"""
        resp = _dict_response(content="")
        assert StandardExtractor().extract(resp) == ""

    def test_none_content(self) -> None:
        """content 为 None 返回空字符串。"""
        resp: dict[str, object] = {
            "choices": [{"message": {"content": None}}],
        }
        assert StandardExtractor().extract(resp) == ""

    def test_no_choices(self) -> None:
        """无 choices 返回空字符串。"""
        resp: dict[str, object] = {}
        assert StandardExtractor().extract(resp) == ""

    def test_empty_choices(self) -> None:
        """choices 为空列表返回空字符串。"""
        resp: dict[str, object] = {"choices": []}
        assert StandardExtractor().extract(resp) == ""

    def test_no_message(self) -> None:
        """choice 无 message 返回空字符串。"""
        resp: dict[str, object] = {"choices": [{}]}
        assert StandardExtractor().extract(resp) == ""

    def test_ignores_reasoning_content(self) -> None:
        """标准提取器不回退 reasoning_content。"""
        resp = _dict_response(content="", reasoning_content="推理内容")
        assert StandardExtractor().extract(resp) == ""


# ---------------------------------------------------------------------------
# ReasoningExtractor 测试
# ---------------------------------------------------------------------------


class TestReasoningExtractor:
    """ReasoningExtractor 测试。"""

    def test_content_takes_priority(self) -> None:
        """content 非空时优先使用。"""
        resp = _dict_response(
            content="正式回复", reasoning_content="推理过程"
        )
        assert ReasoningExtractor().extract(resp) == "正式回复"

    def test_fallback_to_reasoning_content_dict(self) -> None:
        """content 为空时回退 reasoning_content（dict）。"""
        resp = _dict_response(content="", reasoning_content="推理结果")
        assert ReasoningExtractor().extract(resp) == "推理结果"

    def test_fallback_to_reasoning_content_object(self) -> None:
        """content 为空时回退 reasoning_content（对象）。"""
        resp = _obj_response(content="", reasoning_content="对象推理")
        assert ReasoningExtractor().extract(resp) == "对象推理"

    def test_both_empty(self) -> None:
        """content 和 reasoning_content 都为空。"""
        resp = _dict_response(content="", reasoning_content="")
        assert ReasoningExtractor().extract(resp) == ""

    def test_no_reasoning_content_field(self) -> None:
        """无 reasoning_content 字段时返回空。"""
        resp = _dict_response(content="")
        assert ReasoningExtractor().extract(resp) == ""

    def test_none_reasoning_content(self) -> None:
        """reasoning_content 为 None 时返回空。"""
        resp = _dict_response(content="", reasoning_content=None)
        assert ReasoningExtractor().extract(resp) == ""


# ---------------------------------------------------------------------------
# ThinkingBlockExtractor 测试
# ---------------------------------------------------------------------------


class TestThinkingBlockExtractor:
    """ThinkingBlockExtractor 测试。"""

    def test_content_takes_priority(self) -> None:
        """content 非空时优先使用。"""
        resp = _dict_response(
            content="最终回复",
            thinking_blocks=[{"type": "thinking", "thinking": "思考中"}],
        )
        assert ThinkingBlockExtractor().extract(resp) == "最终回复"

    def test_extract_thinking_blocks_dict(self) -> None:
        """从 thinking_blocks 提取文本（dict 形态）。"""
        resp = _dict_response(
            content="",
            thinking_blocks=[
                {"type": "thinking", "thinking": "第一步分析"},
                {"type": "thinking", "thinking": "第二步推理"},
            ],
        )
        result = ThinkingBlockExtractor().extract(resp)
        assert "第一步分析" in result
        assert "第二步推理" in result
        assert "\n" in result

    def test_extract_thinking_blocks_object(self) -> None:
        """从 thinking_blocks 提取文本（对象形态）。"""
        blocks = [
            SimpleNamespace(type="thinking", thinking="对象思考"),
        ]
        resp = _obj_response(content="", thinking_blocks=blocks)
        assert ThinkingBlockExtractor().extract(resp) == "对象思考"

    def test_empty_thinking_blocks(self) -> None:
        """thinking_blocks 为空列表，回退 reasoning_content。"""
        resp = _dict_response(
            content="",
            reasoning_content="回退推理",
            thinking_blocks=[],
        )
        assert ThinkingBlockExtractor().extract(resp) == "回退推理"

    def test_no_thinking_blocks_field(self) -> None:
        """无 thinking_blocks 字段，回退 reasoning_content。"""
        resp = _dict_response(content="", reasoning_content="回退")
        assert ThinkingBlockExtractor().extract(resp) == "回退"

    def test_thinking_blocks_no_thinking_key(self) -> None:
        """thinking_blocks 项无 thinking 字段时跳过。"""
        resp = _dict_response(
            content="",
            thinking_blocks=[{"type": "thinking"}],
        )
        assert ThinkingBlockExtractor().extract(resp) == ""

    def test_all_empty(self) -> None:
        """content / thinking_blocks / reasoning_content 全空。"""
        resp = _dict_response(content="", reasoning_content=None)
        assert ThinkingBlockExtractor().extract(resp) == ""

    def test_single_thinking_block(self) -> None:
        """单个 thinking_block 不含换行。"""
        resp = _dict_response(
            content="",
            thinking_blocks=[{"type": "thinking", "thinking": "唯一思考"}],
        )
        assert ThinkingBlockExtractor().extract(resp) == "唯一思考"


# ---------------------------------------------------------------------------
# get_extractor 测试
# ---------------------------------------------------------------------------


class TestGetExtractor:
    """get_extractor 工厂测试。"""

    def test_standard_for_non_reasoning_model(self) -> None:
        """非推理模型返回 StandardExtractor。"""
        model = _make_model(supports_reasoning=False)
        assert isinstance(get_extractor(model), StandardExtractor)

    def test_reasoning_for_reasoning_model(self) -> None:
        """推理模型返回 ReasoningExtractor。"""
        model = _make_model(supports_reasoning=True)
        assert isinstance(get_extractor(model), ReasoningExtractor)

    def test_none_model_returns_standard(self) -> None:
        """model=None 返回 StandardExtractor。"""
        assert isinstance(get_extractor(None), StandardExtractor)

    def test_missing_field_returns_standard(self) -> None:
        """模型无 supports_reasoning 字段返回 StandardExtractor。"""
        model = MagicMock(spec=[])
        assert isinstance(get_extractor(model), StandardExtractor)

    def test_cached_instances(self) -> None:
        """提取器实例是缓存的（同一引用）。"""
        m1 = _make_model(supports_reasoning=False)
        m2 = _make_model(supports_reasoning=False)
        assert get_extractor(m1) is get_extractor(m2)

        r1 = _make_model(supports_reasoning=True)
        r2 = _make_model(supports_reasoning=True)
        assert get_extractor(r1) is get_extractor(r2)


# ---------------------------------------------------------------------------
# extract_content 统一入口测试
# ---------------------------------------------------------------------------


class TestExtractContent:
    """extract_content 统一入口测试。"""

    def test_standard_model(self) -> None:
        """非推理模型走 StandardExtractor。"""
        model = _make_model(supports_reasoning=False)
        resp = _dict_response(content="hello")
        assert extract_content(resp, model) == "hello"

    def test_reasoning_model_content_present(self) -> None:
        """推理模型 content 非空时直接返回。"""
        model = _make_model(supports_reasoning=True)
        resp = _dict_response(content="答案", reasoning_content="推理")
        assert extract_content(resp, model) == "答案"

    def test_reasoning_model_content_empty(self) -> None:
        """推理模型 content 为空时回退 reasoning_content。"""
        model = _make_model(supports_reasoning=True)
        resp = _dict_response(content="", reasoning_content="推理结果")
        assert extract_content(resp, model) == "推理结果"

    def test_none_model(self) -> None:
        """model=None 走 StandardExtractor。"""
        resp = _dict_response(content="test")
        assert extract_content(resp, None) == "test"

    def test_empty_response(self) -> None:
        """空响应返回空字符串。"""
        model = _make_model(supports_reasoning=True)
        resp: dict[str, object] = {}
        assert extract_content(resp, model) == ""

    def test_is_response_extractor_subclass(self) -> None:
        """所有提取器都是 ResponseExtractor 子类。"""
        assert issubclass(StandardExtractor, ResponseExtractor)
        assert issubclass(ReasoningExtractor, ResponseExtractor)
        assert issubclass(ThinkingBlockExtractor, ResponseExtractor)
