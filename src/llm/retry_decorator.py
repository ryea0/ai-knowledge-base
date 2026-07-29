"""通用重试装饰器，通过显式异常白名单控制重试行为。

与现有 ``chat_completion_with_retry`` 的 ``RetryPolicyFactory`` 体系共存：
    - ``chat_completion_with_retry`` 按 ``LlmErrorType`` 自动分派策略，强耦合 LLM 调用链
    - ``with_retry`` 通过 ``retry_on`` / ``no_retry_on`` 显式声明，可装饰任意同步函数

异常分类表参见 ``openspec/changes/add-with-retry-decorator/specs/llm-retry/spec.md``。
"""

from __future__ import annotations

import functools
import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from src.llm.client import LlmCallError, LlmErrorType
from src.llm.utils import sanitize_secrets

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class NonRetryableLlmError(Exception):
    """不可重试的 LLM 错误，由适配层从 ``LlmCallError`` 转换而来。

    当 ``LlmCallError.error_type`` 为 AUTH_FAILED / CLIENT_ERROR / UNKNOWN 时，
    适配层将其转换为此异常，使其不匹配 ``with_retry`` 的 ``retry_on``，
    从而不被重试。

    Attributes:
        original: 原始 ``LlmCallError`` 实例，保留错误上下文供日志和调试。
    """

    def __init__(self, original: LlmCallError) -> None:
        """初始化不可重试的 LLM 错误。

        Args:
            original: 原始 ``LlmCallError`` 实例。
        """
        super().__init__(str(original))
        self.original: LlmCallError = original


RETRYABLE_HTTP_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
"""HTTP 采集器可重试的瞬时异常类型。"""

NON_RETRYABLE_CONTENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    json.JSONDecodeError,
    KeyError,
    ValueError,
)
"""内容解析不可重试的异常类型（重试只会浪费资源）。"""

RETRYABLE_LLM_ERROR_TYPES: frozenset[LlmErrorType] = frozenset(
    {
        LlmErrorType.TIMEOUT,
        LlmErrorType.RATE_LIMITED,
        LlmErrorType.NETWORK,
        LlmErrorType.SERVER_ERROR,
    }
)
"""可重试的 LLM 错误类型集合，供适配层 ``chat_for_analysis`` 引用。"""


def with_retry(
    *,
    retry_on: tuple[type[Exception], ...] = (),
    no_retry_on: tuple[type[Exception], ...] = (),
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> Callable[[F], F]:
    """同步函数重试装饰器，通过显式异常白名单控制重试行为。

    匹配语义为 ``isinstance``：被装饰函数抛出的异常如果 ``isinstance`` 匹配
    ``retry_on`` 中的任一类型则触发重试；如果匹配 ``no_retry_on`` 中的任一类型
    则立即抛出不重试。``no_retry_on`` 优先于 ``retry_on``。
    未匹配任一列表的异常，默认不重试（安全默认）。

    Args:
        retry_on: 触发重试的异常类型元组，每个元素须为 ``Exception`` 子类。
        no_retry_on: 禁止重试的异常类型元组，每个元素须为 ``Exception`` 子类。
        max_attempts: 最大尝试次数（含首次调用），取值 1-10。
        base_delay: 首次重试前等待秒数，取值 >0 且 <=60。
        backoff_factor: 退避倍率，取值 >=1 且 <=10。
        max_delay: 单次等待上限秒数，取值 >0 且 <=300。
        jitter: 是否添加随机抖动（避免惊群），抖动到理论延迟的 50%-100%。

    Returns:
        装饰后的函数，具有重试能力。

    Raises:
        ValueError: 参数越界或 ``retry_on`` / ``no_retry_on`` 元素不是 Exception 子类。
    """
    _validate_params(
        retry_on=retry_on,
        no_retry_on=no_retry_on,
        max_attempts=max_attempts,
        base_delay=base_delay,
        backoff_factor=backoff_factor,
        max_delay=max_delay,
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if not _should_retry(exc, retry_on, no_retry_on):
                        raise

                    if attempt >= max_attempts:
                        sanitized_msg = sanitize_secrets(str(exc))
                        logger.error(
                            "%s 重试耗尽 %d/%d, 异常: %s: %s",
                            func.__name__,
                            attempt,
                            max_attempts,
                            type(exc).__name__,
                            sanitized_msg,
                            exc_info=True,
                        )
                        raise

                    delay = _calculate_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        backoff_factor=backoff_factor,
                        max_delay=max_delay,
                        jitter=jitter,
                    )
                    sanitized_msg = sanitize_secrets(str(exc))
                    logger.warning(
                        "%s 重试 %d/%d, 等待 %.1fs, 异常: %s: %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        delay,
                        type(exc).__name__,
                        sanitized_msg,
                    )
                    time.sleep(delay)

        return wrapper  # type: ignore[return-value]

    return decorator


def _validate_params(
    *,
    retry_on: tuple[type[Exception], ...],
    no_retry_on: tuple[type[Exception], ...],
    max_attempts: int,
    base_delay: float,
    backoff_factor: float,
    max_delay: float,
) -> None:
    """校验装饰器参数取值范围。

    Args:
        retry_on: 触发重试的异常类型元组。
        no_retry_on: 禁止重试的异常类型元组。
        max_attempts: 最大尝试次数。
        base_delay: 首次重试前等待秒数。
        backoff_factor: 退避倍率。
        max_delay: 单次等待上限秒数。

    Raises:
        ValueError: 参数越界或异常类型不合法。
    """
    if not 1 <= max_attempts <= 10:
        raise ValueError(
            f"max_attempts 须在 1-10 范围内, 实际值: {max_attempts}"
        )
    if not 0.0 < base_delay <= 60.0:
        raise ValueError(
            f"base_delay 须在 (0, 60] 范围内, 实际值: {base_delay}"
        )
    if not 1.0 <= backoff_factor <= 10.0:
        raise ValueError(
            f"backoff_factor 须在 [1, 10] 范围内, 实际值: {backoff_factor}"
        )
    if not 0.0 < max_delay <= 300.0:
        raise ValueError(
            f"max_delay 须在 (0, 300] 范围内, 实际值: {max_delay}"
        )
    for exc_type in retry_on:
        if not (isinstance(exc_type, type) and issubclass(exc_type, Exception)):
            raise ValueError(
                f"retry_on 中的元素须为 Exception 子类, 实际值: {exc_type}"
            )
    for exc_type in no_retry_on:
        if not (isinstance(exc_type, type) and issubclass(exc_type, Exception)):
            raise ValueError(
                f"no_retry_on 中的元素须为 Exception 子类, 实际值: {exc_type}"
            )


def _should_retry(
    exc: Exception,
    retry_on: tuple[type[Exception], ...],
    no_retry_on: tuple[type[Exception], ...],
) -> bool:
    """判断异常是否应触发重试。

    ``no_retry_on`` 优先于 ``retry_on``：同时匹配时 不重试。
    未匹配任一列表的异常，默认不重试。

    Args:
        exc: 被装饰函数抛出的异常。
        retry_on: 触发重试的异常类型元组。
        no_retry_on: 禁止重试的异常类型元组。

    Returns:
        True 表示应重试。
    """
    if isinstance(exc, no_retry_on):
        return False
    return bool(isinstance(exc, retry_on))


def _calculate_delay(
    *,
    attempt: int,
    base_delay: float,
    backoff_factor: float,
    max_delay: float,
    jitter: bool,
) -> float:
    """计算第 ``attempt`` 次重试前的等待秒数。

    退避公式: ``delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)``
    当 ``jitter=True`` 时: ``delay = delay * (0.5 + random() * 0.5)``

    Args:
        attempt: 当前重试序号（从 1 开始）。
        base_delay: 首次重试前等待秒数。
        backoff_factor: 退避倍率。
        max_delay: 单次等待上限秒数。
        jitter: 是否添加随机抖动。

    Returns:
        实际等待秒数。
    """
    delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
    if jitter:
        delay = delay * (0.5 + random.random() * 0.5)
    return delay


__all__ = [
    "NON_RETRYABLE_CONTENT_EXCEPTIONS",
    "NonRetryableLlmError",
    "RETRYABLE_HTTP_EXCEPTIONS",
    "RETRYABLE_LLM_ERROR_TYPES",
    "with_retry",
]
