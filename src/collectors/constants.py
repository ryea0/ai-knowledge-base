"""采集器共享常量。

本模块零依赖，供 ``src/collectors/`` 和 ``src/pipeline/`` 两层共同引用，
避免 ``pipeline`` 采集器导入 ``src.collectors.base`` 时触发
``src.collectors.__init__`` 的循环导入。

限流与重试约束见 docs/specs/content-spec.md §6.1。
"""

from __future__ import annotations

MAX_WORKERS = 5
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0
RETRY_BACKOFF_MAX = 60.0

__all__ = [
    "HTTP_TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "MAX_WORKERS",
    "RETRY_BACKOFF_BASE",
    "RETRY_BACKOFF_MAX",
]
