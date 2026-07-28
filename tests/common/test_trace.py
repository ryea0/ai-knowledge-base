"""src.common.trace 的单元测试。

测试覆盖：
- generate_trace_id: 格式、长度、唯一性
- get_trace_id / set_trace_id: 读写与默认值
- trace_id_var: ContextVar 默认值与隔离性
- TraceIdFilter: 注入 trace_id 到 LogRecord
"""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest

from src.common.trace import (
    TraceIdFilter,
    generate_trace_id,
    get_trace_id,
    set_trace_id,
    trace_id_var,
)


class TestGenerateTraceId:
    """generate_trace_id 测试。"""

    def test_format_8_hex(self) -> None:
        """生成 8 位十六进制字符串。"""
        tid = generate_trace_id()
        assert len(tid) == 8
        assert all(c in "0123456789abcdef" for c in tid)

    def test_lowercase(self) -> None:
        """全小写。"""
        tid = generate_trace_id()
        assert tid == tid.lower()

    def test_uniqueness(self) -> None:
        """连续生成 1000 个不重复。"""
        ids = {generate_trace_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestGetSetTraceId:
    """get_trace_id / set_trace_id 测试。"""

    def test_default_value(self) -> None:
        """未设置时默认为 '-'。"""
        assert get_trace_id() == "-"

    def test_set_and_get(self) -> None:
        """设置后可读取。"""
        token = set_trace_id("abc12345")
        assert get_trace_id() == "abc12345"
        trace_id_var.reset(token)

    def test_reset_restores_previous(self) -> None:
        """reset 恢复原值。"""
        token = set_trace_id("first")
        assert get_trace_id() == "first"

        token2 = set_trace_id("second")
        assert get_trace_id() == "second"
        trace_id_var.reset(token2)
        assert get_trace_id() == "first"

        trace_id_var.reset(token)
        assert get_trace_id() == "-"


class TestTraceIdFilter:
    """TraceIdFilter 测试。"""

    def test_filter_injects_trace_id(self) -> None:
        """Filter 将 trace_id 注入 LogRecord。"""
        token = set_trace_id("aabbccdd")
        try:
            f = TraceIdFilter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=1,
                msg="hello",
                args=(),
                exc_info=None,
            )
            assert f.filter(record) is True
            assert record.trace_id == "aabbccdd"
        finally:
            trace_id_var.reset(token)

    def test_filter_default_trace_id(self) -> None:
        """未设置 traceId 时注入默认值 '-'。"""
        f = TraceIdFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=1,
            msg="world",
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True
        assert record.trace_id == "-"

    def test_filter_always_returns_true(self) -> None:
        """Filter 不过滤任何记录。"""
        f = TraceIdFilter()
        for level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="",
                lineno=1,
                msg="msg",
                args=(),
                exc_info=None,
            )
            assert f.filter(record) is True


class TestContextIsolation:
    """ContextVar 隔离性测试。"""

    def test_independent_contexts(self) -> None:
        """不同 set 之间互不干扰。"""
        token1 = set_trace_id("ctx1")
        assert get_trace_id() == "ctx1"

        token2 = set_trace_id("ctx2")
        assert get_trace_id() == "ctx2"

        trace_id_var.reset(token2)
        assert get_trace_id() == "ctx1"

        trace_id_var.reset(token1)
        assert get_trace_id() == "-"


@pytest.fixture(autouse=True)
def _cleanup_trace_id() -> Generator[None, None, None]:
    """每个测试后确保 trace_id 恢复默认值。"""
    yield
    # 确保测试中设置的 trace_id 被清理
    if trace_id_var.get() != "-":
        trace_id_var.set("-")
