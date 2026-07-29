"""src.llm.retry_decorator 的单元测试。

测试覆盖:
- 异常分类: retry_on / no_retry_on / 默认不重试 / 优先级 / 子类匹配
- 退避参数: max_attempts / base_delay / backoff_factor / max_delay / jitter
- 参数校验: 越界抛 ValueError / 非 Exception 子类
- 重试日志: WARNING / ERROR / 脱敏
- NonRetryableLlmError: 继承关系 / original 属性
"""

from __future__ import annotations

import json
import logging
import random
from unittest.mock import patch

import httpx
import pytest

from src.llm.budget import BudgetExceededError
from src.llm.client import LlmCallError, LlmErrorType
from src.llm.retry_decorator import (
    NON_RETRYABLE_CONTENT_EXCEPTIONS,
    RETRYABLE_HTTP_EXCEPTIONS,
    RETRYABLE_LLM_ERROR_TYPES,
    NonRetryableLlmError,
    with_retry,
)


class TestRetryOnExceptions:
    """异常分类: 触发重试 / 不重试 / 优先级 / 子类匹配。"""

    @patch("src.llm.retry_decorator.time.sleep")
    def test_timeout_triggers_retry(self, mock_sleep: patch) -> None:
        """httpx.TimeoutException 触发重试。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=3,
            jitter=False,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            func()
        assert call_count == 3

    @patch("src.llm.retry_decorator.time.sleep")
    def test_json_decode_error_no_retry(self, mock_sleep: patch) -> None:
        """json.JSONDecodeError 不重试，立即抛出。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            no_retry_on=(json.JSONDecodeError,),
            max_attempts=3,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise json.JSONDecodeError("msg", "doc", 0)

        with pytest.raises(json.JSONDecodeError):
            func()
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.llm.retry_decorator.time.sleep")
    def test_budget_exceeded_no_retry(self, mock_sleep: patch) -> None:
        """BudgetExceededError 不重试，立即抛出。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            no_retry_on=(BudgetExceededError,),
            max_attempts=3,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise BudgetExceededError(
                "budget exceeded",
                daily_limit=100.0,
                daily_spent=90.0,
                estimated_cost=20.0,
                currency="CNY",
            )

        with pytest.raises(BudgetExceededError):
            func()
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.llm.retry_decorator.time.sleep")
    def test_undeclared_exception_no_retry(self, mock_sleep: patch) -> None:
        """未声明异常默认不重试。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=3,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("unexpected")

        with pytest.raises(RuntimeError):
            func()
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.llm.retry_decorator.time.sleep")
    def test_no_retry_on_takes_precedence(self, mock_sleep: patch) -> None:
        """no_retry_on 优先于 retry_on。"""
        call_count = 0

        @with_retry(
            retry_on=(ValueError,),
            no_retry_on=(ValueError,),
            max_attempts=3,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("overlap")

        with pytest.raises(ValueError):
            func()
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.llm.retry_decorator.time.sleep")
    def test_subclass_matches_parent(self, mock_sleep: patch) -> None:
        """异常子类匹配父类声明 (isinstance 语义)。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.HTTPError,),
            max_attempts=2,
            jitter=False,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            func()
        assert call_count == 2


class TestBackoffParams:
    """退避参数: max_attempts / max_delay / jitter。"""

    @patch("src.llm.retry_decorator.time.sleep")
    def test_max_attempts_1_no_retry(self, mock_sleep: patch) -> None:
        """max_attempts=1 等于不重试。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=1,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            func()
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.llm.retry_decorator.time.sleep")
    def test_backoff_capped_by_max_delay(self, mock_sleep: patch) -> None:
        """退避不超过 max_delay (第5次延迟截断为 10s)。"""
        call_count = 0

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=6,
            base_delay=1.0,
            backoff_factor=2.0,
            max_delay=10.0,
            jitter=False,
        )
        def func() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            func()
        assert call_count == 6

        sleep_calls = mock_sleep.call_args_list
        assert len(sleep_calls) == 5
        delays = [call.args[0] for call in sleep_calls]
        assert delays == [1.0, 2.0, 4.0, 8.0, 10.0]

    @patch("src.llm.retry_decorator.time.sleep")
    def test_jitter_in_50_to_100_percent_range(self, mock_sleep: patch) -> None:
        """jitter=True 时延迟在理论值的 50%-100% 区间。"""
        random.seed(42)

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=3,
            base_delay=10.0,
            backoff_factor=1.0,
            max_delay=10.0,
            jitter=True,
        )
        def func() -> None:
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            func()

        sleep_calls = mock_sleep.call_args_list
        assert len(sleep_calls) == 2
        for call in sleep_calls:
            delay = call.args[0]
            assert 5.0 <= delay <= 10.0


class TestParamValidation:
    """参数校验: 越界抛 ValueError。"""

    @pytest.mark.parametrize(
        "params",
        [
            {"max_attempts": 0},
            {"max_attempts": 11},
            {"base_delay": -1.0},
            {"base_delay": 61.0},
            {"backoff_factor": 0.5},
            {"backoff_factor": 11.0},
            {"max_delay": 0.0},
            {"max_delay": 301.0},
        ],
    )
    def test_param_out_of_range_raises_value_error(
        self, params: dict[str, int | float]
    ) -> None:
        """参数越界抛 ValueError。"""
        with pytest.raises(ValueError):
            with_retry(retry_on=(httpx.TimeoutException,), **params)

    def test_non_exception_type_in_retry_on_raises(self) -> None:
        """retry_on 传入非 Exception 子类抛 ValueError。"""
        with pytest.raises(ValueError, match="Exception 子类"):
            with_retry(retry_on=(str,))

    def test_non_exception_type_in_no_retry_on_raises(self) -> None:
        """no_retry_on 传入非 Exception 子类抛 ValueError。"""
        with pytest.raises(ValueError, match="Exception 子类"):
            with_retry(no_retry_on=(int,))


class TestRetryLogging:
    """重试日志: WARNING / ERROR / 脱敏。"""

    @patch("src.llm.retry_decorator.time.sleep")
    def test_warning_log_contains_func_name_and_count(
        self, mock_sleep: patch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """重试日志包含函数名和次数 (jitter=False)。"""

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=3,
            base_delay=2.0,
            backoff_factor=1.0,
            max_delay=2.0,
            jitter=False,
        )
        def my_func() -> None:
            raise httpx.TimeoutException("timeout")

        with caplog.at_level(logging.WARNING), pytest.raises(httpx.TimeoutException):
            my_func()

        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 2

        first = first_record_msg(warning_records[0])
        assert "my_func" in first
        assert "1/3" in first
        assert "2.0s" in first
        assert "TimeoutException" in first

    @patch("src.llm.retry_decorator.time.sleep")
    def test_error_log_on_exhaustion(
        self, mock_sleep: patch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """重试耗尽记录 ERROR 级别日志。"""

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=3,
            jitter=False,
        )
        def my_func() -> None:
            raise httpx.TimeoutException("timeout")

        with caplog.at_level(logging.ERROR), pytest.raises(httpx.TimeoutException):
            my_func()

        error_records = [
            r for r in caplog.records if r.levelno == logging.ERROR
        ]
        assert len(error_records) == 1

        msg = first_record_msg(error_records[0])
        assert "my_func" in msg
        assert "3/3" in msg

    @patch("src.llm.retry_decorator.time.sleep")
    def test_log_secrets_sanitized(
        self, mock_sleep: patch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """异常消息中的 API Key 被脱敏 (日志消息行, 不含 traceback)。"""

        @with_retry(
            retry_on=(httpx.TimeoutException,),
            max_attempts=2,
            jitter=False,
        )
        def my_func() -> None:
            raise httpx.TimeoutException("error api_key=sk-abc123secret")

        with caplog.at_level(logging.WARNING), pytest.raises(httpx.TimeoutException):
            my_func()

        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        for record in warning_records:
            assert "sk-abc123secret" not in record.getMessage()
            assert "***REDACTED***" in record.getMessage()

        error_records = [
            r for r in caplog.records if r.levelno == logging.ERROR
        ]
        for record in error_records:
            assert "sk-abc123secret" not in record.getMessage()
            assert "***REDACTED***" in record.getMessage()


class TestNonRetryableLlmError:
    """NonRetryableLlmError 类属性测试。"""

    def test_inherits_exception_not_llm_call_error(self) -> None:
        """NonRetryableLlmError 继承 Exception 而非 LlmCallError。"""
        assert issubclass(NonRetryableLlmError, Exception)
        assert not issubclass(NonRetryableLlmError, LlmCallError)

    def test_original_attribute_points_to_source(self) -> None:
        """original 属性指向原始 LlmCallError 实例。"""
        original = LlmCallError(
            "auth failed",
            error_type=LlmErrorType.AUTH_FAILED,
        )
        wrapped = NonRetryableLlmError(original)
        assert wrapped.original is original


class TestConstants:
    """常量元组完整性测试。"""

    def test_retryable_http_exceptions_contents(self) -> None:
        """RETRYABLE_HTTP_EXCEPTIONS 包含 4 种 httpx 异常。"""
        assert httpx.TimeoutException in RETRYABLE_HTTP_EXCEPTIONS
        assert httpx.ConnectError in RETRYABLE_HTTP_EXCEPTIONS
        assert httpx.ReadError in RETRYABLE_HTTP_EXCEPTIONS
        assert httpx.RemoteProtocolError in RETRYABLE_HTTP_EXCEPTIONS

    def test_non_retryable_content_exceptions_contents(self) -> None:
        """NON_RETRYABLE_CONTENT_EXCEPTIONS 包含 JSONDecodeError / KeyError / ValueError。"""
        assert json.JSONDecodeError in NON_RETRYABLE_CONTENT_EXCEPTIONS
        assert KeyError in NON_RETRYABLE_CONTENT_EXCEPTIONS
        assert ValueError in NON_RETRYABLE_CONTENT_EXCEPTIONS

    def test_retryable_llm_error_types_contents(self) -> None:
        """RETRYABLE_LLM_ERROR_TYPES 包含 4 种可重试错误类型。"""
        assert LlmErrorType.TIMEOUT in RETRYABLE_LLM_ERROR_TYPES
        assert LlmErrorType.RATE_LIMITED in RETRYABLE_LLM_ERROR_TYPES
        assert LlmErrorType.NETWORK in RETRYABLE_LLM_ERROR_TYPES
        assert LlmErrorType.SERVER_ERROR in RETRYABLE_LLM_ERROR_TYPES
        assert LlmErrorType.AUTH_FAILED not in RETRYABLE_LLM_ERROR_TYPES


def first_record_msg(record: logging.LogRecord) -> str:
    """获取 LogRecord 的格式化消息。"""
    return record.getMessage()
