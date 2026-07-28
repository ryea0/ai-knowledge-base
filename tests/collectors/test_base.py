"""src.collectors.base 的单元测试。

测试覆盖：
- BaseCollector.is_ai_related 关键词匹配
- BaseCollector 抽象方法不可实例化
- 子类实现 collect 方法
"""

from __future__ import annotations

from typing import Any

import pytest

from src.collectors.base import BaseCollector


class TestIsAiRelated:
    """is_ai_related 关键词匹配测试。"""

    def test_match_in_title(self) -> None:
        """标题包含关键词返回 True。"""
        assert BaseCollector.is_ai_related(
            "GPT-5 发布", "", ["gpt", "llm"]
        )

    def test_match_in_summary(self) -> None:
        """摘要包含关键词返回 True。"""
        assert BaseCollector.is_ai_related(
            "无关标题", "这是一个 LLM 模型", ["llm"]
        )

    def test_no_match(self) -> None:
        """标题和摘要均不含关键词返回 False。"""
        assert not BaseCollector.is_ai_related(
            "量子计算突破", "量子比特数创新高", ["llm", "gpt", "agent"]
        )

    def test_case_insensitive(self) -> None:
        """关键词匹配不区分大小写（文本转小写，关键词须也传小写）。"""
        assert BaseCollector.is_ai_related(
            "LLM Framework", "", ["llm"]
        )
        assert BaseCollector.is_ai_related(
            "GPT-5 Release", "New model", ["gpt"]
        )

    def test_empty_keywords(self) -> None:
        """空关键词列表返回 False。"""
        assert not BaseCollector.is_ai_related(
            "GPT-5 发布", "LLM 相关", []
        )

    def test_empty_text(self) -> None:
        """空标题和空摘要返回 False。"""
        assert not BaseCollector.is_ai_related(
            "", "", ["llm"]
        )


class TestBaseCollectorAbstract:
    """BaseCollector 抽象类行为测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """BaseCollector 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseCollector()  # type: ignore[abstract]

    def test_subclass_must_implement_collect(self) -> None:
        """子类未实现 collect 不能实例化。"""

        class IncompleteCollector(BaseCollector):
            pass

        with pytest.raises(TypeError):
            IncompleteCollector()  # type: ignore[abstract]

    def test_subclass_with_collect(self) -> None:
        """子类实现 collect 可以实例化并调用。"""

        class DummyCollector(BaseCollector):
            def collect(self, **kwargs: Any) -> list[dict[str, Any]]:
                return [{"title": "test", "url": "https://example.com"}]

        collector = DummyCollector()
        result = collector.collect()
        assert len(result) == 1
        assert result[0]["title"] == "test"
