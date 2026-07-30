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

.. note::

    ``GitHubCollector`` / ``RSSCollector`` 采用 ``__getattr__`` 惰性导入，
    避免 ``src.pipeline`` 采集器导入 ``src.collectors.constants`` 时触发
    ``__init__`` 中的子模块导入，进而形成循环依赖
    (``pipeline -> collectors.__init__ -> collectors.github -> pipeline``)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.collectors.base import BaseCollector, CollectorRegistry, default_registry

if TYPE_CHECKING:
    from src.collectors.github import GitHubCollector as GitHubCollector
    from src.collectors.rss import RSSCollector as RSSCollector

__all__ = [
    "BaseCollector",
    "CollectorRegistry",
    "GitHubCollector",
    "RSSCollector",
    "default_registry",
    "ensure_registered",
]

_LAZY_MODULES: dict[str, str] = {
    "GitHubCollector": "src.collectors.github",
    "RSSCollector": "src.collectors.rss",
}

_registered = False


def ensure_registered() -> None:
    """确保所有内置采集器已注册到 :data:`default_registry`。

    子模块（``github`` / ``rss``）在模块级执行 ``register()`` 自注册，
    但惰性导入下它们不会在 ``import src.collectors`` 时自动加载。
    本函数显式触发子模块导入以完成注册，保证 ``collect_node`` 能发现采集器。

    幂等：多次调用安全，已注册的采集器不会重复注册
    （``CollectorRegistry.register`` 对同名采集器抛 ``ValueError``，
    本函数捕获并忽略）。
    """
    global _registered
    if _registered:
        return
    import importlib

    for module_path in _LAZY_MODULES.values():
        importlib.import_module(module_path)
    _registered = True


def __getattr__(name: str) -> Any:
    """惰性导入 GitHubCollector / RSSCollector，打破循环依赖。

    Args:
        name: 属性名。

    Returns:
        对应的类对象。

    Raises:
        AttributeError: 属性不存在。
    """
    module_path = _LAZY_MODULES.get(name)
    if module_path is not None:
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, name)
        globals()[name] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """返回模块的公共属性列表。"""
    return list(__all__)
