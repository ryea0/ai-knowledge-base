"""src.analyzers.base 的单元测试。

测试覆盖：
- BaseAnalyzer 抽象方法不可实例化
- 子类实现 analyze 方法
"""

from __future__ import annotations

from typing import Any

import pytest

from src.analyzers.base import BaseAnalyzer


class TestBaseAnalyzerAbstract:
    """BaseAnalyzer 抽象类行为测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """BaseAnalyzer 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseAnalyzer()  # type: ignore[abstract]

    def test_subclass_must_implement_analyze(self) -> None:
        """子类未实现 analyze 不能实例化。"""

        class IncompleteAnalyzer(BaseAnalyzer):
            pass

        with pytest.raises(TypeError):
            IncompleteAnalyzer()  # type: ignore[abstract]

    def test_subclass_with_analyze(self) -> None:
        """子类实现 analyze 可以实例化并调用。"""

        class DummyAnalyzer(BaseAnalyzer):
            def analyze(self, content_path: str, **kwargs: Any) -> dict[str, Any]:
                return {
                    "title": "test",
                    "summary": "测试摘要",
                    "highlights": ["亮点1"],
                    "score": 8,
                    "tags": ["llm"],
                    "category": "tool",
                    "language": "zh",
                }

        analyzer = DummyAnalyzer()
        result = analyzer.analyze("knowledge/raw/test.md")
        assert result["title"] == "test"
        assert result["score"] == 8
