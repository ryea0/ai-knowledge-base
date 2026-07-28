"""src.distributors.base 的单元测试。

测试覆盖：
- BaseDistributor 抽象方法不可实例化
- should_skip 幂等检查
- 子类实现 distribute / format_message
"""

from __future__ import annotations

from typing import Any

import pytest

from src.distributors.base import BaseDistributor


class TestBaseDistributorAbstract:
    """BaseDistributor 抽象类行为测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """BaseDistributor 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseDistributor()  # type: ignore[abstract]

    def test_subclass_must_implement_abstract_methods(self) -> None:
        """子类未实现所有抽象方法不能实例化。"""

        class IncompleteDistributor(BaseDistributor):
            pass

        with pytest.raises(TypeError):
            IncompleteDistributor()  # type: ignore[abstract]


class TestShouldSkip:
    """should_skip 幂等检查测试。"""

    def test_skip_when_channel_already_published(self) -> None:
        """published_channels 已含当前渠道时跳过。"""

        class TelegramDistributor(BaseDistributor):
            @property
            def channel_name(self) -> str:
                return "telegram"

            def distribute(self, article: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                return {}

            def format_message(self, article: dict[str, Any]) -> str:
                return ""

        dist = TelegramDistributor()
        article = {
            "published_channels": ["telegram", "feishu"],
        }
        assert dist.should_skip(article) is True

    def test_no_skip_when_channel_not_in_published(self) -> None:
        """published_channels 不含当前渠道时不跳过。"""

        class FeishuDistributor(BaseDistributor):
            @property
            def channel_name(self) -> str:
                return "feishu"

            def distribute(self, article: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                return {}

            def format_message(self, article: dict[str, Any]) -> str:
                return ""

        dist = FeishuDistributor()
        article = {
            "published_channels": ["telegram"],
        }
        assert dist.should_skip(article) is False

    def test_no_skip_when_published_channels_none(self) -> None:
        """published_channels 为 None 时不跳过。"""

        class TelegramDistributor(BaseDistributor):
            @property
            def channel_name(self) -> str:
                return "telegram"

            def distribute(self, article: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                return {}

            def format_message(self, article: dict[str, Any]) -> str:
                return ""

        dist = TelegramDistributor()
        article = {"published_channels": None}
        assert dist.should_skip(article) is False

    def test_no_skip_when_published_channels_missing(self) -> None:
        """published_channels 键不存在时不跳过。"""

        class TelegramDistributor(BaseDistributor):
            @property
            def channel_name(self) -> str:
                return "telegram"

            def distribute(self, article: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                return {}

            def format_message(self, article: dict[str, Any]) -> str:
                return ""

        dist = TelegramDistributor()
        article: dict[str, Any] = {}
        assert dist.should_skip(article) is False
