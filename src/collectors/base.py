"""采集器抽象基类。

所有数据源采集器须继承此类，实现 ``collect`` 方法。
采集器职责：
    1. 从外部数据源获取候选条目列表。
    2. 按 AI/LLM/Agent 关键词筛选。
    3. 按热度排序并截取 top N。
    4. 返回结构化 JSON 候选列表（不落盘）。

约束（见 docs/specs/content-spec.md §6.1）：
    - 采集前须查重（DB ``kb_article.source_url`` 或 ``knowledge/raw/``），已存在则跳过。
    - 速率限制、重试策略、并发控制须遵守 docs/specs/content-spec.md §6.1 限流与重试约束。
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
    """

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
