"""采集器抽象基类与注册中心。

所有数据源采集器须继承 :class:`BaseCollector`，实现 ``collect`` 方法，
并通过 :class:`CollectorRegistry` 注册，供 ``collect_node`` 统一调度。

采集器职责：
    1. 从外部数据源获取候选条目列表。
    2. 按 AI/LLM/Agent 关键词筛选。
    3. 按热度排序并截取 top N。
    4. 返回结构化 JSON 候选列表（不落盘）。

约束（见 docs/specs/content-spec.md §6.1）：
    - 采集前须查重（DB ``kb_article.source_url`` 或 ``knowledge/raw/``），已存在则跳过。
    - 速率限制、重试策略、并发控制须遵守 docs/specs/content-spec.md §6.1 限流与重试约束。

可扩展设计：
    新增数据源只需三步：
        1. 创建 ``src/collectors/<name>.py``，实现 ``class XxxCollector(BaseCollector)``
        2. 在 ``src/collectors/__init__.py`` 中导入并 ``register("xxx", XxxCollector())``
        3. ``collect_node`` 自动发现并调用，无需修改图结构
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

MAX_WORKERS = 5
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0
RETRY_BACKOFF_MAX = 60.0


class BaseCollector(ABC):
    """数据源采集器抽象基类。

    子类须实现 :meth:`collect` 方法，返回候选条目列表。
    每个条目为 dict，至少包含 ``title``/``url``/``source``/``popularity``/``summary`` 字段。

    Attributes:
        name: 采集器名称，用于注册和日志标识。
        limit: 默认最大采集条数。
    """

    name: str = "base"
    limit: int = 10

    @abstractmethod
    def collect(self, **kwargs: Any) -> list[dict[str, Any]]:
        """执行采集，返回候选条目列表。

        Args:
            **kwargs: 子类特定参数（如关键词、数量上限等）。

        Returns:
            候选条目列表，每条至少包含:
                - ``title`` (str): 条目标题。
                - ``url`` (str): 原始链接。
                - ``source`` (str): 来源平台标识。
                - ``popularity`` (int): 来源热度。
                - ``summary`` (str): 初步摘要。

        Raises:
            RuntimeError: 采集过程中发生不可恢复的错误。
        """
        ...

    @staticmethod
    def is_ai_related(title: str, summary: str, keywords: list[str]) -> bool:
        """判断条目是否与 AI/LLM/Agent 领域相关。

        Args:
            title: 条目标题。
            summary: 条目摘要。
            keywords: 关键词列表（小写）。

        Returns:
            标题或摘要中包含任一关键词则返回 ``True``。
        """
        text = f"{title} {summary}".lower()
        return any(kw in text for kw in keywords)


class CollectorRegistry:
    """采集器注册中心。

    管理所有已注册的 :class:`BaseCollector` 实例，供 ``collect_node``
    统一调度。新增数据源时只需注册即可被自动发现。

    Usage::

        registry = CollectorRegistry()
        registry.register("github", GitHubCollector())
        registry.register("rss", RSSCollector())

        # 获取所有已注册采集器
        for name, collector in registry.get_all():
            items = collector.collect()
    """

    def __init__(self) -> None:
        """初始化空注册中心。"""
        self._collectors: dict[str, BaseCollector] = {}

    def register(self, name: str, collector: BaseCollector) -> None:
        """注册采集器。

        Args:
            name: 采集器名称（唯一标识）。
            collector: 采集器实例。

        Raises:
            ValueError: 名称已注册。
        """
        if name in self._collectors:
            raise ValueError(f"采集器已注册: {name}")
        self._collectors[name] = collector
        logger.debug("采集器已注册: %s -> %s", name, type(collector).__name__)

    def get(self, name: str) -> BaseCollector | None:
        """按名称获取采集器。

        Args:
            name: 采集器名称。

        Returns:
            采集器实例，未注册返回 ``None``。
        """
        return self._collectors.get(name)

    def get_all(self) -> list[tuple[str, BaseCollector]]:
        """获取所有已注册采集器。

        Returns:
            ``(name, collector)`` 元组列表，按注册顺序。
        """
        return list(self._collectors.items())

    def names(self) -> list[str]:
        """获取所有已注册采集器名称。

        Returns:
            名称列表。
        """
        return list(self._collectors.keys())


# 全局默认注册中心实例
default_registry = CollectorRegistry()


__all__ = [
    "BaseCollector",
    "CollectorRegistry",
    "default_registry",
]
