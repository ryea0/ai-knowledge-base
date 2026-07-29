"""数据源采集器模块。

提供从外部数据源采集 AI/LLM/Agent 领域技术动态的能力。
采集器通过 :data:`CollectorRegistry` 注册，``collect_node`` 自动发现并调用。

可扩展设计：
    新增数据源只需三步：
        1. 创建 ``src/collectors/<name>.py``，实现 ``class XxxCollector(BaseCollector)``
        2. 在本文件中导入并 ``default_registry.register("xxx", XxxCollector())``
        3. ``collect_node`` 自动发现并调用，无需修改图结构

已注册采集器：
    - ``github``: GitHub Search API 采集器（:mod:`src.collectors.github`）
    - ``rss``: RSS 源采集器（:mod:`src.collectors.rss`）

子模块：
    - ``base``: 采集器抽象基类 + 注册中心
    - ``github``: GitHub 采集器
    - ``rss``: RSS 采集器
"""

from src.collectors.base import BaseCollector, CollectorRegistry, default_registry
from src.collectors.github import GitHubCollector
from src.collectors.rss import RSSCollector

__all__ = [
    "BaseCollector",
    "CollectorRegistry",
    "GitHubCollector",
    "RSSCollector",
    "default_registry",
]
