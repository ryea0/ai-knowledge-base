"""RSS 采集器 -- 适配 LangGraph 工作流。

复用 :class:`src.pipeline.rss_collector.RSSCollector` 的采集逻辑，
继承 :class:`BaseCollector` 并注册到 :data:`default_registry`，
输出统一为 ``KBState.sources`` 格式。

RSS 源配置见 ``src/pipeline/rss_sources.yaml``，仅采集 ``enabled: true`` 的源。
注册后 ``collect_node`` 自动发现并调用，无需修改图结构。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.collectors.base import BaseCollector, default_registry
from src.pipeline.rss_collector import RSSCollector as _PipelineRSS

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """RSS 源采集器。

    从 YAML 配置读取 RSS 源列表，逐个获取 RSS/Atom XML，
    用正则解析条目，输出 ``KBState.sources`` 格式的候选列表。

    Attributes:
        name: 注册名 ``"rss"``。
        limit: 每个源最大采集条数。
    """

    name = "rss"

    def __init__(
        self,
        limit: int = 3,
        *,
        config_path: Path | None = None,
    ) -> None:
        """初始化 RSS 采集器。

        Args:
            limit: 每个源最大采集条数。
            config_path: RSS 源配置路径，默认使用 ``rss_sources.yaml``。
        """
        self.limit = limit
        self._inner = _PipelineRSS(limit=limit, config_path=config_path)

    def collect(self, **kwargs: Any) -> list[dict[str, Any]]:
        """执行 RSS 采集，返回 ``KBState.sources`` 格式候选列表。

        Args:
            **kwargs: 透传给底层 ``RSSCollector.collect()``。

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
        ``KBState.sources`` 格式条目。
    """
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source_platform": item.get("source", "hackernews"),
        "source_score": item.get("popularity", 0),
        "summary": item.get("summary", ""),
        "content_path": "",
    }


# 注册到全局注册中心
default_registry.register("rss", RSSCollector())

__all__ = ["RSSCollector"]
