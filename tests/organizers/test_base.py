"""src.organizers.base 的单元测试。

测试覆盖：
- BaseOrganizer 抽象方法不可实例化
- 子类实现 organize 方法
"""

from __future__ import annotations

from typing import Any

import pytest

from src.organizers.base import BaseOrganizer


class TestBaseOrganizerAbstract:
    """BaseOrganizer 抽象类行为测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """BaseOrganizer 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseOrganizer()  # type: ignore[abstract]

    def test_subclass_must_implement_organize(self) -> None:
        """子类未实现 organize 不能实例化。"""

        class IncompleteOrganizer(BaseOrganizer):
            pass

        with pytest.raises(TypeError):
            IncompleteOrganizer()  # type: ignore[abstract]

    def test_subclass_with_organize(self) -> None:
        """子类实现 organize 可以实例化并调用。"""

        class DummyOrganizer(BaseOrganizer):
            def organize(
                self,
                collected_meta: dict[str, Any],
                analysis_result: dict[str, Any],
                **kwargs: Any,
            ) -> dict[str, Any] | None:
                return {
                    "article_id": "kb-20260728-0001",
                    "title": collected_meta.get("title", ""),
                    "summary": analysis_result.get("summary", ""),
                }

        organizer = DummyOrganizer()
        result = organizer.organize(
            collected_meta={"title": "测试标题"},
            analysis_result={"summary": "测试摘要"},
        )
        assert result is not None
        assert result["article_id"] == "kb-20260728-0001"
        assert result["title"] == "测试标题"

    def test_subclass_return_none_for_duplicate(self) -> None:
        """子类可返回 None 表示去重跳过。"""

        class DedupOrganizer(BaseOrganizer):
            def organize(
                self,
                collected_meta: dict[str, Any],
                analysis_result: dict[str, Any],
                **kwargs: Any,
            ) -> dict[str, Any] | None:
                return None

        organizer = DedupOrganizer()
        result = organizer.organize(
            collected_meta={},
            analysis_result={},
        )
        assert result is None
