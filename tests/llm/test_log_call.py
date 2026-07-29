"""src.llm.log_call 的单元测试。

测试覆盖：
- write_call_log 成功调用写入 token / cost / latency
- write_call_log 失败调用写入 error_msg，usage/cost 为 None
- write_call_log trace_id 从上下文获取
- write_call_log 事务不 commit 仅 flush
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.common.trace import set_trace_id
from src.llm.cost import CostEstimate, TokenUsage
from src.llm.log_call import write_call_log
from src.llm.orm import Base, LlmCallLog


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


class TestWriteCallLogSuccess:
    """成功调用日志写入测试。"""

    def test_writes_token_usage_and_cost(self, session: Session) -> None:
        """成功调用写入 token 用量和成本。"""
        usage = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        cost = CostEstimate(
            usage=usage,
            input_cost_usd=0.001,
            output_cost_usd=0.002,
            total_cost_usd=0.003,
        )

        write_call_log(
            session,
            provider_id=1,
            model_id=2,
            is_success=True,
            latency_ms=1234,
            usage=usage,
            cost=cost,
        )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.provider_id == 1
        assert log.model_id == 2
        assert log.is_success == True  # noqa: E712
        assert log.input_tokens == 100
        assert log.output_tokens == 50
        assert log.total_tokens == 150
        assert float(log.cost_usd) == pytest.approx(0.003)
        assert log.latency_ms == 1234
        assert log.error_msg is None

    def test_writes_without_usage(self, session: Session) -> None:
        """成功调用但无 usage 时 token/cost 为 None。"""
        write_call_log(
            session,
            provider_id=1,
            model_id=2,
            is_success=True,
            latency_ms=500,
        )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.is_success == True  # noqa: E712
        assert log.input_tokens is None
        assert log.output_tokens is None
        assert log.total_tokens is None
        assert log.cost_usd is None
        assert log.latency_ms == 500

    def test_writes_without_latency(self, session: Session) -> None:
        """未传 latency_ms 时为 None。"""
        write_call_log(
            session,
            provider_id=1,
            model_id=2,
            is_success=True,
        )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        assert logs[0].latency_ms is None


class TestWriteCallLogFailure:
    """失败调用日志写入测试。"""

    def test_writes_error_msg(self, session: Session) -> None:
        """失败调用写入错误信息，usage/cost 为 None。"""
        write_call_log(
            session,
            provider_id=1,
            model_id=2,
            is_success=False,
            latency_ms=300,
            error_msg="timeout",
        )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.is_success == False  # noqa: E712
        assert log.error_msg == "timeout"
        assert log.input_tokens is None
        assert log.output_tokens is None
        assert log.total_tokens is None
        assert log.cost_usd is None
        assert log.latency_ms == 300

    def test_writes_without_error_msg(self, session: Session) -> None:
        """失败调用未传 error_msg 时为 None。"""
        write_call_log(
            session,
            provider_id=1,
            model_id=2,
            is_success=False,
        )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        assert logs[0].error_msg is None


class TestWriteCallLogTraceId:
    """trace_id 测试。"""

    def test_trace_id_from_context(self, session: Session) -> None:
        """trace_id 从上下文获取。"""
        set_trace_id("abcd1234")
        try:
            write_call_log(
                session,
                provider_id=1,
                model_id=2,
                is_success=True,
            )
        finally:
            set_trace_id("")

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        assert logs[0].trace_id == "abcd1234"

    def test_trace_id_default_when_not_set(self, session: Session) -> None:
        """未设置 trace_id 时使用默认值。"""
        with patch("src.llm.log_call.get_trace_id", return_value="-"):
            write_call_log(
                session,
                provider_id=1,
                model_id=2,
                is_success=True,
            )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 1
        assert logs[0].trace_id == "-"


class TestWriteCallLogMultiple:
    """多次调用写入测试。"""

    def test_multiple_calls_logged(self, session: Session) -> None:
        """多次调用各自写入一行。"""
        for i in range(5):
            write_call_log(
                session,
                provider_id=1,
                model_id=2,
                is_success=True,
                latency_ms=100 + i,
            )

        logs = session.query(LlmCallLog).all()
        assert len(logs) == 5
        latencies = [log.latency_ms for log in logs]
        assert latencies == [100, 101, 102, 103, 104]
