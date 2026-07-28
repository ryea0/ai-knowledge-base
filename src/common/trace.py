"""链路追踪 traceId 基础设施。

基于 ``contextvars.ContextVar`` 实现线程安全的 traceId 传递，
配合 :class:`TraceIdFilter` 自动注入日志记录，业务代码无需手动拼接。

对应 AGENTS.md §10.2 ~ §10.4 规范。

核心组件：
    - :data:`trace_id_var`: ContextVar，存储当前上下文的 traceId。
    - :class:`TraceIdFilter`: 日志过滤器，将 traceId 注入 LogRecord。
    - :func:`generate_trace_id`: 生成 8 位十六进制 traceId。
    - :func:`get_trace_id`: 获取当前上下文的 traceId。

Usage::

    from src.common.trace import trace_id_var, TraceIdFilter, generate_trace_id

    # 链路入口
    trace_id_var.set(generate_trace_id())

    # 日志自动携带 trace_id（需注册 TraceIdFilter）
    # 格式: %(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s
"""

from __future__ import annotations

import contextvars
import logging
import uuid

# ContextVar 默认值 "-" 表示未设置 traceId（如非请求上下文的 CLI 调用）
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="-"
)

_DEFAULT_TRACE_ID = "-"


def generate_trace_id() -> str:
    """生成 8 位十六进制 traceId（UUIDv4 前 8 位）。

    Returns:
        如 ``a1b2c3d4`` 格式的全小写十六进制字符串。
    """
    return uuid.uuid4().hex[:8]


def get_trace_id() -> str:
    """获取当前上下文的 traceId。

    Returns:
        当前 traceId，未设置时返回 ``"-"``。
    """
    return trace_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """设置当前上下文的 traceId。

    Args:
        trace_id: 要设置的 traceId。

    Returns:
        ContextVar Token，可用于恢复原值（``trace_id_var.reset(token)``）。
    """
    return trace_id_var.set(trace_id)


class TraceIdFilter(logging.Filter):
    """日志过滤器，将 traceId 注入 LogRecord。

    注册到 handler 后，所有日志记录自动携带 ``trace_id`` 属性，
    格式字符串中使用 ``%(trace_id)s`` 即可输出。

    Usage::

        handler = logging.StreamHandler()
        handler.addFilter(TraceIdFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
            )
        )
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """注入当前 traceId 到日志记录。

        Args:
            record: 日志记录对象。

        Returns:
            始终返回 True（不过滤任何记录，仅注入属性）。
        """
        record.trace_id = trace_id_var.get()
        return True


__all__ = [
    "TraceIdFilter",
    "generate_trace_id",
    "get_trace_id",
    "set_trace_id",
    "trace_id_var",
]
