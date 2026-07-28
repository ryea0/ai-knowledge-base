"""src.config.logging_config 的单元测试。

测试覆盖：
- ColoredFormatter: 基本格式化、颜色注入、非 TTY 降级
- JsonFormatter: JSON 结构、字段完整性、异常信息
- setup_logging: 开发环境配置、生产环境配置、重复调用安全
- 环境区分: APP_ENV 环境变量读取
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from collections.abc import Generator
from pathlib import Path

import pytest

from src.common.trace import TraceIdFilter, set_trace_id, trace_id_var
from src.config.logging_config import (
    ColoredFormatter,
    JsonFormatter,
    setup_logging,
)


class TestColoredFormatter:
    """ColoredFormatter 测试。"""

    def test_basic_format(self) -> None:
        """基本格式化包含 trace_id。"""
        token = set_trace_id("abc12345")
        try:
            formatter = ColoredFormatter(
                fmt="%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
            formatter._is_tty = False  # noqa: SLF001
            record = logging.LogRecord(
                name="test.module",
                level=logging.INFO,
                pathname="",
                lineno=1,
                msg="hello world",
                args=(),
                exc_info=None,
            )
            # TraceIdFilter 注入 trace_id 属性
            TraceIdFilter().filter(record)
            output = formatter.format(record)
            assert "[INFO]" in output
            assert "[abc12345]" in output
            assert "test.module" in output
            assert "hello world" in output
        finally:
            trace_id_var.reset(token)

    def test_color_injected_in_tty(self) -> None:
        """TTY 环境下级别名注入颜色码。"""
        formatter = ColoredFormatter(
            fmt="[%(levelname)s] %(message)s",
        )
        formatter._is_tty = True  # noqa: SLF001
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=1,
            msg="warn msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "\033[33m" in output  # yellow for WARNING
        assert "\033[0m" in output   # reset

    def test_no_color_in_non_tty(self) -> None:
        """非 TTY 环境无颜色码。"""
        formatter = ColoredFormatter(
            fmt="[%(levelname)s] %(message)s",
        )
        formatter._is_tty = False  # noqa: SLF001
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=1,
            msg="error msg",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "\033[" not in output


class TestJsonFormatter:
    """JsonFormatter 测试。"""

    def test_basic_json_structure(self) -> None:
        """JSON 包含必要字段。"""
        token = set_trace_id("def67890")
        try:
            formatter = JsonFormatter()
            record = logging.LogRecord(
                name="test.json",
                level=logging.INFO,
                pathname="",
                lineno=1,
                msg="test message",
                args=(),
                exc_info=None,
            )
            TraceIdFilter().filter(record)
            output = formatter.format(record)
            data = json.loads(output)
            assert data["level"] == "INFO"
            assert data["trace_id"] == "def67890"
            assert data["logger"] == "test.json"
            assert data["message"] == "test message"
            assert "timestamp" in data
        finally:
            trace_id_var.reset(token)

    def test_default_trace_id(self) -> None:
        """未设置 traceId 时输出 '-'。"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        data = json.loads(formatter.format(record))
        assert data["trace_id"] == "-"

    def test_exception_included(self) -> None:
        """异常信息包含在 JSON 中。"""
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=1,
                msg="failed",
                args=(),
                exc_info=exc_info,
            )
            data = json.loads(formatter.format(record))
            assert "exception" in data
            assert "ValueError" in data["exception"]
            assert "test error" in data["exception"]

    def test_timestamp_format(self) -> None:
        """时间戳为 ISO 8601 格式。"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        data = json.loads(formatter.format(record))
        assert "T" in data["timestamp"]
        assert data["timestamp"].endswith("Z")


class TestSetupLogging:
    """setup_logging 测试。"""

    @pytest.fixture(autouse=True)
    def _cleanup_handlers(self) -> Generator[None, None, None]:
        """测试后恢复 root logger 原始状态。"""
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_level = root.level
        yield
        for h in root.handlers:
            root.removeHandler(h)
        for h in original_handlers:
            root.addHandler(h)
        root.setLevel(original_level)

    def test_development_config(self) -> None:
        """开发环境配置：控制台 handler + ColoredFormatter。"""
        setup_logging(environment="development", log_level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert isinstance(handler.formatter, ColoredFormatter)

    def test_production_config(
        self,
        tmp_path: Path,
    ) -> None:
        """生产环境配置：文件 handler + 控制台 handler + JsonFormatter。"""
        log_dir = str(tmp_path / "logs")
        setup_logging(environment="production", log_dir=log_dir)
        root = logging.getLogger()
        assert len(root.handlers) == 2
        # 文件 handler
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert isinstance(file_handlers[0].formatter, JsonFormatter)
        assert os.path.exists(os.path.join(log_dir, "app.log"))
        # 控制台 handler
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(console_handlers) == 1
        assert isinstance(console_handlers[0].formatter, JsonFormatter)

    def test_idempotent(self) -> None:
        """重复调用不累积 handler。"""
        setup_logging(environment="development")
        setup_logging(environment="development")
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_env_var_default(self) -> None:
        """未指定 environment 时从 APP_ENV 读取。"""
        old_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "production"
        try:
            setup_logging(log_dir="/tmp/test_logs_env")
            root = logging.getLogger()
            assert len(root.handlers) == 2
        finally:
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

    def test_trace_filter_registered(self) -> None:
        """所有 handler 都注册了 TraceIdFilter。"""
        setup_logging(environment="development")
        root = logging.getLogger()
        for handler in root.handlers:
            filters = [type(f).__name__ for f in handler.filters]
            assert "TraceIdFilter" in filters

    def test_log_output_contains_trace_id(self) -> None:
        """日志输出包含 trace_id。"""
        setup_logging(environment="development")
        token = set_trace_id("test1234")
        try:
            test_logger = logging.getLogger("test.output")
            with __import__("io").StringIO() as buf:
                handler = logging.StreamHandler(buf)
                handler.addFilter(
                    next(
                        f for f in logging.getLogger().handlers[0].filters
                        if type(f).__name__ == "TraceIdFilter"
                    )
                )
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
                ))
                test_logger.addHandler(handler)
                test_logger.info("test message")
                output = buf.getvalue()
                test_logger.removeHandler(handler)
            assert "[test1234]" in output
        finally:
            trace_id_var.reset(token)
