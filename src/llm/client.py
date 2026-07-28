"""LiteLLM 封装，统一 LLM 调用入口。

通过 LiteLLM 的 ``completion()`` 函数统一调用多供应商 LLM，
支持 OpenAI / DeepSeek / Ark / Qwen / Ollama / llama.cpp 等。

调用成功/失败后须通知 :mod:`src.llm.health` 更新供应商健康状态。

异常分类与重试策略（策略模式）：
    - ``TIMEOUT``        -- 请求超时，可重试，指数退避
    - ``AUTH_FAILED``    -- 鉴权失败，不可重试
    - ``RATE_LIMITED``   -- 限流，可重试，更长退避
    - ``NETWORK``        -- 网络连接异常，可重试，短退避
    - ``SERVER_ERROR``   -- 服务端 5xx，可重试
    - ``CLIENT_ERROR``   -- 客户端 4xx（非鉴权/限流），不可重试
    - ``UNKNOWN``        -- 未知异常，不可重试
"""

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Any

import litellm

from src.llm.orm import LlmModel, LlmProvider

logger = logging.getLogger(__name__)

# 关闭 LiteLLM 自身的日志输出，避免污染标准输出
litellm.suppress_debug_info = True


class LlmErrorType(Enum):
    """LLM 调用失败的错误类型分类。

    用于 :class:`LlmCallError` 携带错误语义，供上层按类型决定重试策略。
    """

    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    UNKNOWN = "unknown"


class LlmCallError(Exception):
    """LLM 调用失败异常，含供应商/模型上下文与错误类型分类。

    Attributes:
        provider_code: 供应商代码，用于日志定位。
        model_code: 模型代码，用于日志定位。
        error_type: 错误类型分类，供上层按类型决定重试策略。
    """

    def __init__(
        self,
        message: str,
        *,
        provider_code: str = "",
        model_code: str = "",
        error_type: LlmErrorType = LlmErrorType.UNKNOWN,
    ) -> None:
        """初始化 LLM 调用异常。

        Args:
            message: 异常消息（已脱敏）。
            provider_code: 供应商代码。
            model_code: 模型代码。
            error_type: 错误类型分类。
        """
        super().__init__(message)
        self.provider_code = provider_code
        self.model_code = model_code
        self.error_type = error_type

    def __str__(self) -> str:
        """返回包含错误类型的异常描述。"""
        return (
            f"[{self.error_type.value}] provider={self.provider_code} "
            f"model={self.model_code}: {self.args[0] if self.args else ''}"
        )


class RetryStrategy:
    """重试策略基类（策略模式接口）。

    子类通过覆写 :meth:`should_retry` / :meth:`max_attempts` /
    :meth:`backoff_seconds` 定义不同错误类型的重试行为。
    """

    def should_retry(self, attempt: int) -> bool:
        """判断当前重试次数下是否应继续重试。

        Args:
            attempt: 已重试次数（从 1 开始）。

        Returns:
            True 表示应重试。
        """
        return attempt < self.max_attempts()

    def max_attempts(self) -> int:
        """最大重试次数（不含首次调用）。"""
        return 0

    def backoff_seconds(self, attempt: int) -> float:
        """计算第 attempt 次重试前的等待时间（秒）。

        Args:
            attempt: 当前重试序号（从 1 开始）。

        Returns:
            等待秒数。
        """
        return 0.0


class NoRetryStrategy(RetryStrategy):
    """不可重试策略（鉴权失败 / 客户端错误 / 未知异常）。"""

    def max_attempts(self) -> int:
        return 0

    def should_retry(self, attempt: int) -> bool:
        return False


class TimeoutRetryStrategy(RetryStrategy):
    """超时重试策略 -- 指数退避，最多 3 次。

    退避: 1s -> 2s -> 4s
    """

    def max_attempts(self) -> int:
        return 3

    def backoff_seconds(self, attempt: int) -> float:
        return float(2 ** (attempt - 1))


class RateLimitRetryStrategy(RetryStrategy):
    """限流重试策略 -- 指数退避 + 基础延迟，最多 3 次。

    退避: 5s -> 10s -> 20s（限流需更长等待）
    """

    def max_attempts(self) -> int:
        return 3

    def backoff_seconds(self, attempt: int) -> float:
        return 5.0 * float(2 ** (attempt - 1))


class NetworkRetryStrategy(RetryStrategy):
    """网络异常重试策略 -- 短退避，最多 2 次。

    退避: 1s -> 2s
    """

    def max_attempts(self) -> int:
        return 2

    def backoff_seconds(self, attempt: int) -> float:
        return float(attempt)


class ServerErrorRetryStrategy(RetryStrategy):
    """服务端 5xx 重试策略 -- 指数退避，最多 2 次。

    退避: 2s -> 4s
    """

    def max_attempts(self) -> int:
        return 2

    def backoff_seconds(self, attempt: int) -> float:
        return 2.0 * float(2 ** (attempt - 1))


class RetryPolicyFactory:
    """重试策略工厂 -- 根据错误类型返回对应策略。

    使用缓存避免重复创建策略实例。
    """

    _strategies: dict[LlmErrorType, RetryStrategy] = {}

    @classmethod
    def get_strategy(cls, error_type: LlmErrorType) -> RetryStrategy:
        """根据错误类型获取重试策略。

        Args:
            error_type: LLM 错误类型分类。

        Returns:
            对应的重试策略实例。
        """
        if not cls._strategies:
            cls._strategies = {
                LlmErrorType.TIMEOUT: TimeoutRetryStrategy(),
                LlmErrorType.AUTH_FAILED: NoRetryStrategy(),
                LlmErrorType.RATE_LIMITED: RateLimitRetryStrategy(),
                LlmErrorType.NETWORK: NetworkRetryStrategy(),
                LlmErrorType.SERVER_ERROR: ServerErrorRetryStrategy(),
                LlmErrorType.CLIENT_ERROR: NoRetryStrategy(),
                LlmErrorType.UNKNOWN: NoRetryStrategy(),
            }
        return cls._strategies.get(error_type, NoRetryStrategy())


def chat_completion(
    provider: LlmProvider,
    model: LlmModel,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """调用 LLM 生成回复（非流式）。

    使用 LiteLLM 统一接口，通过 ``model.litellm_model`` 自动路由到对应供应商。
    鉴权由 LiteLLM 根据 ``litellm_provider`` 前缀自动处理（bearer 类型传入 api_key）。

    Args:
        provider: 供应商 ORM 对象（含 base_url / api_key / 超时等配置）。
        model: 模型 ORM 对象（含 litellm_model 标识）。
        messages: OpenAI 格式的消息列表。
        temperature: 采样温度，默认 0.7。
        max_tokens: 最大输出 tokens，None 则使用模型默认值。
        stream: 是否流式输出。
        **kwargs: 透传给 LiteLLM ``completion()`` 的额外参数。

    Returns:
        LiteLLM 响应字典，含 ``choices`` / ``usage`` 等字段。

    Raises:
        LlmCallError: 调用失败（网络 / 鉴权 / 模型不存在等），携带 error_type。
    """
    # 构造 LiteLLM 调用参数
    call_kwargs: dict[str, Any] = {
        "model": model.litellm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
        "timeout": provider.timeout_seconds,
        "num_retries": provider.max_retries,
        **kwargs,
    }

    # 设置 API Key 和 base_url（非 none 鉴权类型）
    if provider.api_key_encrypted:
        from src.llm.crypto import decrypt

        call_kwargs["api_key"] = decrypt(provider.api_key_encrypted)

    if provider.base_url:
        call_kwargs["api_base"] = provider.base_url

    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens

    logger.info(
        "LLM 调用: provider=%s model=%s messages=%d",
        provider.provider_code,
        model.model_code,
        len(messages),
    )

    try:
        response = litellm.completion(**call_kwargs)
    except Exception as exc:
        error_type = _classify_exception(exc)
        sanitized = _sanitize_error(str(exc))
        logger.error(
            "LLM 调用失败: provider=%s model=%s error_type=%s error=%s",
            provider.provider_code,
            model.model_code,
            error_type.value,
            sanitized,
        )
        raise LlmCallError(
            sanitized,
            provider_code=provider.provider_code,
            model_code=model.model_code,
            error_type=error_type,
        ) from exc

    logger.info(
        "LLM 调用成功: provider=%s model=%s",
        provider.provider_code,
        model.model_code,
    )
    return dict(response) if not stream else response


def chat_completion_with_retry(
    provider: LlmProvider,
    model: LlmModel,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """带策略重试的 LLM 调用。

    在 :func:`chat_completion` 基础上增加基于 :class:`RetryStrategy` 的重试逻辑。
    重试策略由 :class:`RetryPolicyFactory` 根据异常的 ``error_type`` 自动选择。

    Args:
        provider: 供应商 ORM 对象。
        model: 模型 ORM 对象。
        messages: OpenAI 格式的消息列表。
        temperature: 采样温度。
        max_tokens: 最大输出 tokens。
        stream: 是否流式输出。
        **kwargs: 透传给 LiteLLM 的额外参数。

    Returns:
        LiteLLM 响应字典。

    Raises:
        LlmCallError: 所有重试耗尽后仍失败，抛出最后一次异常。
    """
    attempt = 0

    while True:
        try:
            return chat_completion(
                provider,
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                **kwargs,
            )
        except LlmCallError as exc:
            attempt += 1
            strategy = RetryPolicyFactory.get_strategy(exc.error_type)

            if not strategy.should_retry(attempt):
                logger.warning(
                    "LLM 重试终止: provider=%s model=%s error_type=%s attempts=%d",
                    provider.provider_code,
                    model.model_code,
                    exc.error_type.value,
                    attempt,
                )
                raise

            backoff = strategy.backoff_seconds(attempt)
            logger.info(
                "LLM 重试: provider=%s model=%s error_type=%s attempt=%d/%d backoff=%.1fs",
                provider.provider_code,
                model.model_code,
                exc.error_type.value,
                attempt,
                strategy.max_attempts(),
                backoff,
            )
            time.sleep(backoff)


def _classify_exception(exc: Exception) -> LlmErrorType:
    """将 LiteLLM / OpenAI SDK 异常映射为 :class:`LlmErrorType`。

    LiteLLM 异常继承链:
        - ``Timeout`` -> ``APITimeoutError`` -> ``APIConnectionError``
        - ``AuthenticationError`` -> ``APIStatusError`` (401/403)
        - ``RateLimitError`` -> ``APIStatusError`` (429)
        - ``APIConnectionError`` -> 网络层错误
        - ``InternalServerError`` -> 5xx
        - ``ServiceUnavailableError`` -> 503
        - ``BadRequestError`` / ``NotFoundError`` -> 4xx

    Args:
        exc: LiteLLM 抛出的原始异常。

    Returns:
        对应的 :class:`LlmErrorType` 枚举值。
    """
    # 按精确度从高到低匹配（子类在前）
    exc_name = type(exc).__name__

    # 超时 -- Timeout 是 litellm.exceptions.Timeout
    if _is_instance(exc, "Timeout") or exc_name == "Timeout":
        return LlmErrorType.TIMEOUT

    # 鉴权失败
    if _is_instance(exc, "AuthenticationError") or exc_name == "AuthenticationError":
        return LlmErrorType.AUTH_FAILED

    # 限流
    if _is_instance(exc, "RateLimitError") or exc_name == "RateLimitError":
        return LlmErrorType.RATE_LIMITED

    # 服务端 5xx
    if (
        _is_instance(exc, "InternalServerError")
        or _is_instance(exc, "ServiceUnavailableError")
        or _is_instance(exc, "BadGatewayError")
        or exc_name in ("InternalServerError", "ServiceUnavailableError", "BadGatewayError")
    ):
        return LlmErrorType.SERVER_ERROR

    # 网络连接异常（排除已匹配的 Timeout）
    if _is_instance(exc, "APIConnectionError") or exc_name == "APIConnectionError":
        return LlmErrorType.NETWORK

    # 客户端 4xx（非鉴权/限流）
    if (
        _is_instance(exc, "BadRequestError")
        or _is_instance(exc, "NotFoundError")
        or _is_instance(exc, "PermissionDeniedError")
        or exc_name in ("BadRequestError", "NotFoundError", "PermissionDeniedError")
    ):
        return LlmErrorType.CLIENT_ERROR

    return LlmErrorType.UNKNOWN


def _is_instance(exc: Exception, class_name: str) -> bool:
    """检查异常是否为指定类名的实例（按类名匹配，避免硬依赖 LiteLLM 内部模块路径）。

    Args:
        exc: 待检查的异常。
        class_name: LiteLLM 异常类名（如 ``"Timeout"``）。

    Returns:
        True 表示异常或其父类中存在匹配的类名。
    """
    return any(cls.__name__ == class_name for cls in type(exc).__mro__)


def _sanitize_error(msg: str) -> str:
    """脱敏错误消息，移除可能包含的 API Key。

    Args:
        msg: 原始错误消息。

    Returns:
        脱敏后的错误消息，截断至 500 字符。
    """
    sanitized = msg
    for keyword in ("api_key", "apikey", "authorization", "bearer", "token"):
        if keyword.lower() in sanitized.lower():
            sanitized = re.sub(
                rf"(?i)({keyword})\s*[=:]\s*\S+",
                r"\1=***REDACTED***",
                sanitized,
            )
    return sanitized[:500]


def estimate_cost(
    model: LlmModel, input_tokens: int, output_tokens: int
) -> float:
    """估算单次调用的成本（USD）。

    Args:
        model: 模型 ORM 对象（含定价信息）。
        input_tokens: 输入 token 数。
        output_tokens: 输出 token 数。

    Returns:
        预估成本（USD），local 模型返回 0.0。
    """
    cost = (
        input_tokens / 1_000_000 * float(model.input_price_per_1m)
        + output_tokens / 1_000_000 * float(model.output_price_per_1m)
    )
    return round(cost, 6)


__all__ = [
    "LlmCallError",
    "LlmErrorType",
    "NetworkRetryStrategy",
    "NoRetryStrategy",
    "RateLimitRetryStrategy",
    "RetryPolicyFactory",
    "RetryStrategy",
    "ServerErrorRetryStrategy",
    "TimeoutRetryStrategy",
    "chat_completion",
    "chat_completion_with_retry",
    "estimate_cost",
]
