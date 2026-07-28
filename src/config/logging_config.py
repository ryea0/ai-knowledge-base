"""统一日志配置。

按环境区分日志输出格式：

    - **开发环境**（``APP_ENV != production``）：控制台彩色输出，格式可读。
    - **生产环境**（``APP_ENV == production``）：JSON 格式输出到文件（按天滚动，
      保留 30 天），同时输出到控制台（JSON 格式）。

日志格式包含 traceId（通过 :class:`~src.common.trace.TraceIdFilter` 注入）：
    ``%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s``

对应 docs/specs/trace-spec.md §10.4 日志注入规则。

Usage::

    from src.config.logging_config import setup_logging

    # 应用启动时调用一次
    setup_logging()
    # 或指定环境
    setup_logging(environment="production", log_dir="logs", log_level="INFO")
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any

from src.common.trace import TraceIdFilter

# 日志格式常量（开发环境）
_DEV_FORMAT = (
    "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
)
_DEV_DATE_FORMAT = "%H:%M:%S"

# 慢请求阈值（秒）
SLOW_REQUEST_THRESHOLD = 1.0

# 文件滚动保留天数
_LOG_BACKUP_DAYS = 30

# ANSI 颜色码
_ANSI_COLORS = {
    "DEBUG": "\033[36m",      # cyan
    "INFO": "\033[32m",       # green
    "WARNING": "\033[33m",    # yellow
    "ERROR": "\033[31m",      # red
    "CRITICAL": "\033[35m",   # magenta
}
_ANSI_RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """开发环境彩色控制台 Formatter。

    在日志级别和消息前添加 ANSI 颜色码，提升开发体验。
    非 TTY 环境（如管道重定向）自动降级为无颜色输出。
    """

    def __init__(self, fmt: str, datefmt: str | None = None) -> None:
        """初始化彩色 Formatter。

        Args:
            fmt: 日志格式字符串。
            datefmt: 日期格式字符串。
        """
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._is_tty = sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，添加颜色。

        Args:
            record: 日志记录对象。

        Returns:
            格式化后的日志字符串。
        """
        if not self._is_tty:
            return super().format(record)

        color = _ANSI_COLORS.get(record.levelname, "")
        if color:
            # 仅给级别名加颜色，消息保持默认
            record.levelname = f"{color}{record.levelname}{_ANSI_RESET}"
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """生产环境 JSON Formatter。

    输出结构化 JSON 日志，便于 ELK / Loki 等日志系统采集和检索。
    """

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON 字符串。

        Args:
            record: 日志记录对象。

        Returns:
            JSON 格式的日志字符串。
        """
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "-"),
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    *,
    environment: str | None = None,
    log_dir: str = "logs",
    log_level: str = "INFO",
) -> None:
    """配置全局日志（应用启动时调用一次）。

    按环境区分输出方式：
        - 开发环境：控制台彩色输出。
        - 生产环境：JSON 格式输出到文件（按天滚动，保留 30 天）+ 控制台。

    Args:
        environment: 环境标识，未指定时从 ``APP_ENV`` 环境变量读取。
        log_dir: 日志文件目录（仅生产环境使用）。
        log_level: 日志级别，默认 INFO。
    """
    if environment is None:
        environment = os.environ.get("APP_ENV", "development")

    level = getattr(logging, log_level.upper(), logging.INFO)

    # 清除已有配置，避免重复添加 handler
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 创建 traceId filter（所有 handler 共用）
    trace_filter = TraceIdFilter()

    if environment == "production":
        _setup_production(root_logger, level, log_dir, trace_filter)
    else:
        _setup_development(root_logger, level, trace_filter)

    # 降低第三方库日志噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def _setup_development(
    root_logger: logging.Logger,
    level: int,
    trace_filter: TraceIdFilter,
) -> None:
    """配置开发环境日志：控制台彩色输出。

    Args:
        root_logger: 根日志器。
        level: 日志级别。
        trace_filter: traceId 过滤器。
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.addFilter(trace_filter)
    handler.setFormatter(
        ColoredFormatter(fmt=_DEV_FORMAT, datefmt=_DEV_DATE_FORMAT)
    )
    root_logger.addHandler(handler)


def _setup_production(
    root_logger: logging.Logger,
    level: int,
    log_dir: str,
    trace_filter: TraceIdFilter,
) -> None:
    """配置生产环境日志：JSON 格式 + 按天滚动文件 + 控制台。

    文件滚动策略：每天一个文件，保留最近 30 天。
    文件名格式：``app.log``（当天）、``app.log.2026-07-28``（历史）。

    Args:
        root_logger: 根日志器。
        level: 日志级别。
        log_dir: 日志文件目录。
        trace_filter: traceId 过滤器。
    """
    os.makedirs(log_dir, exist_ok=True)
    json_formatter = JsonFormatter()

    # 文件 handler（按天滚动，保留 30 天）
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "app.log"),
        when="midnight",
        interval=1,
        backupCount=_LOG_BACKUP_DAYS,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.addFilter(trace_filter)
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)

    # 控制台 handler（JSON 格式，便于容器化环境采集）
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.addFilter(trace_filter)
    console_handler.setFormatter(json_formatter)
    root_logger.addHandler(console_handler)


__all__ = [
    "ColoredFormatter",
    "JsonFormatter",
    "setup_logging",
]
