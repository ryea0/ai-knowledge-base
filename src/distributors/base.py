"""分发器抽象基类。

分发器职责（见 AGENTS.md §5、docs/specs/content-spec.md §6.6）：
    1. 接收已审核（``reviewed``）的知识条目。
    2. 格式化为渠道特定消息格式。
    3. 调用渠道 API 推送消息。
    4. 推送成功后在同一事务内更新 ``published_channels`` 和 ``status``/``published_at``。

分发幂等（见 docs/specs/content-spec.md §6.6 第 5 条）：
    - 推送前须先查 ``published_channels`` 是否已含目标渠道，含则跳过。
    - 状态须在 ``reviewed`` 时方可分发。
    - 禁止从 ``pending`` 直接推送。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseDistributor(ABC):
    """多渠道分发器抽象基类。

    子类须实现 :meth:`distribute` 和 :meth:`format_message` 方法。
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """渠道标识名（如 ``telegram`` / ``feishu``）。"""
        ...

    @abstractmethod
    def distribute(self, article: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """推送知识条目至当前渠道。

        Args:
            article: 标准知识条目 dict（见 docs/specs/article-format.md §4 字段定义）。
            **kwargs: 子类特定参数。

        Returns:
            分发结果 dict，包含以下键:
                - ``article_id`` (str): 条目业务 ID。
                - ``channel`` (str): 渠道名。
                - ``status`` (str): 推送结果 success/skipped/failed。
                - ``attempted_at`` (str): 推送尝试时间 ISO 8601 UTC。
                - ``published_at`` (str | None): 成功时填发布时间，否则 null。
                - ``error`` (str | None): 失败原因，成功/跳过为 null。

        Raises:
            RuntimeError: 推送过程中发生不可恢复的错误。
        """
        ...

    @abstractmethod
    def format_message(self, article: dict[str, Any]) -> str:
        """将知识条目格式化为渠道特定的消息文本。

        Args:
            article: 标准知识条目 dict。

        Returns:
            格式化后的消息字符串。
        """
        ...

    def should_skip(self, article: dict[str, Any]) -> bool:
        """检查是否应跳过推送（幂等检查）。

        Args:
            article: 标准知识条目 dict。

        Returns:
            ``published_channels`` 已含当前渠道则返回 ``True``。
        """
        published_channels = article.get("published_channels")
        if published_channels is None:
            return False
        return self.channel_name in published_channels
