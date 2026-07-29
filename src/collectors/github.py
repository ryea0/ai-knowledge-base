"""GitHub 采集器 -- 适配 LangGraph 工作流。

复用 :class:`src.pipeline.github_collector.GitHubCollector` 的采集逻辑，
继承 :class:`BaseCollector` 并注册到 :data:`default_registry`，
输出统一为 ``KBState.sources`` 格式。

注册后 ``collect_node`` 自动发现并调用，无需修改图结构。
"""

from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, default_registry
from src.pipeline.github_collector import GitHubCollector as _PipelineGitHub

logger = logging.getLogger(__name__)


class GitHubCollector(BaseCollector):
    """GitHub Search API 采集器。

    通过 GitHub Search API 搜索 AI/LLM/Agent 相关仓库，
    按 star 数降序排列，输出 ``KBState.sources`` 格式的候选列表。

    Attributes:
        name: 注册名 ``"github"``。
        limit: 默认最大采集条数。
    """

    name = "github"

    def __init__(self, limit: int = 3) -> None:
        """初始化 GitHub 采集器。

        Args:
            limit: 最大采集条数。
        """
        self.limit = limit
        self._inner = _PipelineGitHub(limit=limit)

    def collect(self, **kwargs: Any) -> list[dict[str, Any]]:
        """执行 GitHub 采集，返回 ``KBState.sources`` 格式候选列表。

        Args:
            **kwargs: 透传给底层 ``GitHubCollector.collect()``。

        Returns:
            候选条目列表，每条包含:
                ``title``/``url``/``source_platform``/``source_score``/``summary``/``content_path``。
        """
        raw_items = self._inner.collect()
        return [_to_source(item) for item in raw_items]


def _to_source(item: dict[str, Any]) -> dict[str, Any]:
    """将 pipeline 采集器输出转换为 ``KBState.sources`` 格式。

    Args:
        item: pipeline 采集器的原始条目，含 ``title``/``url``/``source``/
            ``popularity``/``summary``。

    Returns:
        ``KBState.sources`` 格式条目，含 ``title``/``url``/``source_platform``/
        ``source_score``/``summary``/``content_path``。
    """
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source_platform": "github_trending",
        "source_score": item.get("popularity", 0),
        "summary": item.get("summary", ""),
        "content_path": "",
    }


# 注册到全局注册中心
default_registry.register("github", GitHubCollector())

__all__ = ["GitHubCollector"]
