"""LiteLLM 封装，统一 LLM 调用入口。

通过 LiteLLM 的 ``completion()`` 函数统一调用多供应商 LLM，
支持 OpenAI / DeepSeek / Ark / Qwen / Ollama / llama.cpp 等。

    调用成功/失败后须通知 :mod:`src.llm.health` 更新供应商健康状态，
    并在 ``kb_llm_call_log`` 表写入一行调用计量日志（token 用量 / 成本 / 延迟）。

    鉴权统一通过 :mod:`src.llm.auth_adapter` 的 :func:`build_auth_context` 构造，
    不再直接调用 :mod:`src.llm.crypto` 解密。

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
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

import litellm

from src.llm.auth_adapter import build_auth_context
from src.llm.orm import LlmModel, LlmProvider
from src.llm.response import LLMResponse
from src.llm.utils import sanitize_secrets

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.llm.budget import BudgetConfig, BudgetGuard
    from src.llm.cost import CostEstimate, TokenUsage

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
    """重试策略（数据驱动配置，替代策略模式子类层级）。

    通过 ``max_attempts`` / ``backoff_base`` / ``backoff_factor`` 三个参数
    覆盖原 ``TimeoutRetryStrategy`` / ``RateLimitRetryStrategy`` 等子类的行为，
    退避公式: ``delay = backoff_base * (backoff_factor ** (attempt - 1))``。
    """

    __slots__ = ("max_attempts", "backoff_base", "backoff_factor")

    def __init__(
        self,
        max_attempts: int = 0,
        backoff_base: float = 0.0,
        backoff_factor: float = 2.0,
    ) -> None:
        """初始化重试策略。

        Args:
            max_attempts: 最大重试次数（不含首次调用），0 表示不重试。
            backoff_base: 首次退避秒数。
            backoff_factor: 退避倍率。
        """
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_factor = backoff_factor

    def should_retry(self, attempt: int) -> bool:
        """判断当前重试次数下是否应继续重试。

        Args:
            attempt: 已重试次数（从 1 开始）。

        Returns:
            True 表示应重试。
        """
        return attempt < self.max_attempts

    def backoff_seconds(self, attempt: int) -> float:
        """计算第 attempt 次重试前的等待时间（秒）。

        Args:
            attempt: 当前重试序号（从 1 开始）。

        Returns:
            等待秒数。
        """
        return self.backoff_base * (self.backoff_factor ** (attempt - 1))


# 不可重试策略（鉴权失败 / 客户端错误 / 未知异常）
NoRetryStrategy = RetryStrategy(max_attempts=0)

# 超时重试策略 -- 指数退避，最多 3 次。退避: 1s -> 2s -> 4s
TimeoutRetryStrategy = RetryStrategy(max_attempts=3, backoff_base=1.0, backoff_factor=2.0)

# 限流重试策略 -- 指数退避 + 基础延迟，最多 3 次。退避: 5s -> 10s -> 20s
RateLimitRetryStrategy = RetryStrategy(max_attempts=3, backoff_base=5.0, backoff_factor=2.0)

# 网络异常重试策略 -- 线性退避，最多 2 次。退避: 1s -> 2s
NetworkRetryStrategy = RetryStrategy(max_attempts=2, backoff_base=1.0, backoff_factor=2.0)

# 服务端 5xx 重试策略 -- 指数退避，最多 2 次。退避: 2s -> 4s
ServerErrorRetryStrategy = RetryStrategy(max_attempts=2, backoff_base=2.0, backoff_factor=2.0)


class RetryPolicyFactory:
    """重试策略工厂 -- 根据错误类型返回对应策略。

    策略实例为模块级单例，无需缓存。
    """

    _strategies: dict[LlmErrorType, RetryStrategy] = {
        LlmErrorType.TIMEOUT: TimeoutRetryStrategy,
        LlmErrorType.AUTH_FAILED: NoRetryStrategy,
        LlmErrorType.RATE_LIMITED: RateLimitRetryStrategy,
        LlmErrorType.NETWORK: NetworkRetryStrategy,
        LlmErrorType.SERVER_ERROR: ServerErrorRetryStrategy,
        LlmErrorType.CLIENT_ERROR: NoRetryStrategy,
        LlmErrorType.UNKNOWN: NoRetryStrategy,
    }

    @classmethod
    def get_strategy(cls, error_type: LlmErrorType) -> RetryStrategy:
        """根据错误类型获取重试策略。

        Args:
            error_type: LLM 错误类型分类。

        Returns:
            对应的重试策略实例。
        """
        return cls._strategies.get(error_type, NoRetryStrategy)


def chat_completion(
    provider: LlmProvider,
    model: LlmModel,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = False,
    session: Session | None = None,
    **kwargs: Any,
) -> LLMResponse | object:
    """调用 LLM 生成回复（非流式）。

    使用 LiteLLM 统一接口，通过 ``model.litellm_model`` 自动路由到对应供应商。
    鉴权由 :func:`build_auth_context` 统一构造，支持 bearer / header / none 类型。

    LiteLLM 内部重试被禁用（``num_retries=0``），重试由外层
    :func:`chat_completion_with_retry` 按策略模式统一控制，避免双重重试。

    若传入 ``session``，调用成功/失败后会通知 :mod:`src.llm.health`
    更新模型健康状态。

    Args:
        provider: 供应商 ORM 对象（含 base_url / api_key / 超时等配置）。
        model: 模型 ORM 对象（含 litellm_model 标识）。
        messages: OpenAI 格式的消息列表。
        temperature: 采样温度，默认 0.7。
        max_tokens: 最大输出 tokens，None 则使用模型默认值。
        stream: 是否流式输出。
        session: 可选的 SQLAlchemy Session，传入则联动健康状态更新和调用日志写入。
        **kwargs: 透传给 LiteLLM ``completion()`` 的额外参数。

    Returns:
        非流式调用返回 :class:`LLMResponse`（含 content / usage / cost，cost 含币种信息）；
        流式调用返回 LiteLLM 原始响应对象。

    Raises:
        LlmCallError: 调用失败（网络 / 鉴权 / 模型不存在等），携带 error_type。
    """
    ctx = build_auth_context(provider)

    call_kwargs: dict[str, Any] = {
        "model": model.litellm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
        "timeout": provider.timeout_seconds,
        "num_retries": 0,
        **kwargs,
    }

    if ctx.api_key:
        call_kwargs["api_key"] = ctx.api_key
    if ctx.api_base:
        call_kwargs["api_base"] = ctx.api_base
    if ctx.extra_headers:
        call_kwargs["extra_headers"] = ctx.extra_headers
    if ctx.extra_kwargs:
        call_kwargs.update(ctx.extra_kwargs)

    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens

    logger.info(
        "LLM 调用: provider=%s model=%s messages=%d",
        provider.provider_code,
        model.model_code,
        len(messages),
    )

    # 预算控制：调用前检查每日上限
    budget_guard: BudgetGuard | None = None
    if session is not None:
        from src.config.settings import get_settings

        settings = get_settings()
        if any(
            (
                settings.budget.daily_limit_cny,
                settings.budget.daily_limit_usd,
            )
        ):
            from src.llm.budget import BudgetGuard

            budget_guard = BudgetGuard(session, _budget_config_from_settings(settings))
            budget_guard.check_pre_call(model)

    start = time.monotonic()
    try:
        response = litellm.completion(**call_kwargs)
    except Exception as exc:
        error_type = _classify_exception(exc)
        sanitized = sanitize_secrets(str(exc))
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.error(
            "LLM 调用失败: provider=%s model=%s error_type=%s latency=%dms error=%s",
            provider.provider_code,
            model.model_code,
            error_type.value,
            latency_ms,
            sanitized,
        )
        if session is not None:
            _on_call_complete(
                session,
                provider,
                model,
                is_success=False,
                latency_ms=latency_ms,
                error_msg=sanitized,
            )
        raise LlmCallError(
            sanitized,
            provider_code=provider.provider_code,
            model_code=model.model_code,
            error_type=error_type,
        ) from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "LLM 调用成功: provider=%s model=%s latency=%dms",
        provider.provider_code,
        model.model_code,
        latency_ms,
    )

    if stream:
        if session is not None:
            _on_call_complete(
                session,
                provider,
                model,
                is_success=True,
                latency_ms=latency_ms,
            )
        return response  # type: ignore[no-any-return]

    llm_response = LLMResponse.from_litellm_response(
        response,
        model,
        provider_code=provider.provider_code,
        latency_ms=latency_ms,
    )

    if session is not None:
        _on_call_complete(
            session,
            provider,
            model,
            is_success=True,
            latency_ms=latency_ms,
            usage=llm_response.usage,
            cost=llm_response.cost,
        )

        # 预算控制：调用后检查单次上限 + 每日累计
        if budget_guard is not None:
            budget_guard.check_post_call(llm_response.cost)

    return llm_response


def chat_completion_with_retry(
    provider: LlmProvider,
    model: LlmModel,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = False,
    session: Session | None = None,
    **kwargs: Any,
) -> LLMResponse | object:
    """带策略重试的 LLM 调用。

    在 :func:`chat_completion` 基础上增加基于 :class:`RetryStrategy` 的重试逻辑。
    重试策略由 :class:`RetryPolicyFactory` 根据异常的 ``error_type`` 自动选择。

    重试上限取 ``min(strategy.max_attempts, provider.max_retries)``，
    避免某策略的重试次数超过供应商配置的上限。

    Args:
        provider: 供应商 ORM 对象。
        model: 模型 ORM 对象。
        messages: OpenAI 格式的消息列表。
        temperature: 采样温度。
        max_tokens: 最大输出 tokens。
        stream: 是否流式输出。
        session: 可选的 SQLAlchemy Session，传入则联动健康状态更新和调用日志写入。
            每次 ``chat_completion`` 尝试（含重试）都会写一行 call_log。

        **kwargs: 透传给 LiteLLM 的额外参数。

    Returns:
        非流式调用返回 :class:`LLMResponse`；
        流式调用返回 LiteLLM 原始响应对象。

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
                session=session,
                **kwargs,
            )
        except LlmCallError as exc:
            attempt += 1
            strategy = RetryPolicyFactory.get_strategy(exc.error_type)
            effective_max = min(strategy.max_attempts, provider.max_retries)

            if not strategy.should_retry(attempt) or attempt > effective_max:
                logger.warning(
                    "LLM 重试终止: provider=%s model=%s error_type=%s "
                    "attempts=%d max=%d",
                    provider.provider_code,
                    model.model_code,
                    exc.error_type.value,
                    attempt,
                    effective_max,
                )
                raise

            backoff = strategy.backoff_seconds(attempt)
            logger.info(
                "LLM 重试: provider=%s model=%s error_type=%s "
                "attempt=%d/%d backoff=%.1fs",
                provider.provider_code,
                model.model_code,
                exc.error_type.value,
                attempt,
                effective_max,
                backoff,
            )
            time.sleep(backoff)


def _on_call_complete(
    session: Session,
    provider: LlmProvider,
    model: LlmModel,
    *,
    is_success: bool,
    latency_ms: int,
    usage: TokenUsage | None = None,
    cost: CostEstimate | None = None,
    error_msg: str | None = None,
) -> None:
    """LLM 调用完成后的统一后处理：更新健康状态 + 写入调用日志。

    消除 ``chat_completion`` 中 stream / 非 stream / 失败路径的重复代码。

    Args:
        session: SQLAlchemy Session。
        provider: 供应商 ORM 对象。
        model: 模型 ORM 对象。
        is_success: 调用是否成功。
        latency_ms: 响应延迟毫秒。
        usage: Token 用量（成功且非 stream 时传入）。
        cost: 成本估算（成功且非 stream 时传入）。
        error_msg: 失败原因（脱敏后，失败时传入）。
    """
    from src.llm.health import record_failure, record_success
    from src.llm.log_call import write_call_log

    if is_success:
        record_success(
            session,
            provider_id=provider.id,
            model_id=model.id,
            latency_ms=latency_ms,
        )
    else:
        record_failure(
            session,
            provider_id=provider.id,
            model_id=model.id,
            error_msg=error_msg or "",
        )

    write_call_log(
        session,
        provider_id=provider.id,
        model_id=model.id,
        is_success=is_success,
        latency_ms=latency_ms,
        usage=usage,
        cost=cost,
        error_msg=error_msg,
    )


def _budget_config_from_settings(settings: Any) -> BudgetConfig:
    """从 :class:`Settings` 构造 :class:`BudgetConfig`。

    Args:
        settings: 全局配置 :class:`Settings` 实例。

    Returns:
        :class:`BudgetConfig` 实例。
    """
    from src.llm.budget import BudgetConfig

    return BudgetConfig(
        daily_limit_cny=settings.budget.daily_limit_cny,
        daily_limit_usd=settings.budget.daily_limit_usd,
        per_call_limit_cny=settings.budget.per_call_limit_cny,
        per_call_limit_usd=settings.budget.per_call_limit_usd,
    )


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
    # _is_instance 遍历 MRO 检查类名，无需再额外比对 exc_name

    # 超时 -- Timeout 是 litellm.exceptions.Timeout
    if _is_instance(exc, "Timeout"):
        return LlmErrorType.TIMEOUT

    # 鉴权失败
    if _is_instance(exc, "AuthenticationError"):
        return LlmErrorType.AUTH_FAILED

    # 限流
    if _is_instance(exc, "RateLimitError"):
        return LlmErrorType.RATE_LIMITED

    # 服务端 5xx
    if (
        _is_instance(exc, "InternalServerError")
        or _is_instance(exc, "ServiceUnavailableError")
        or _is_instance(exc, "BadGatewayError")
    ):
        return LlmErrorType.SERVER_ERROR

    # 网络连接异常（排除已匹配的 Timeout）
    if _is_instance(exc, "APIConnectionError"):
        return LlmErrorType.NETWORK

    # 客户端 4xx（非鉴权/限流）
    if (
        _is_instance(exc, "BadRequestError")
        or _is_instance(exc, "NotFoundError")
        or _is_instance(exc, "PermissionDeniedError")
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


def quick_chat(
    prompt: str,
    session: Session,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """一句话调用 LLM 的便捷函数。

    自动从 DB 中选取最优供应商和默认模型（按优先级 + 健康状态路由），
    发送单轮对话并返回纯文本响应。适合不需要精细控制供应商/模型的
    简单调用场景（如摘要生成、标签提取）。

    内部调用 :func:`chat_completion_with_retry`，已含重试和健康联动。

    Args:
        prompt: 用户提问文本。
        session: SQLAlchemy Session（用于查询供应商/模型 + 健康联动）。
        system_prompt: 可选的 system 消息，用于设定角色或上下文。
        temperature: 采样温度，默认 0.7。
        max_tokens: 最大输出 tokens，None 则使用模型默认值。

    Returns:
        LLM 生成的回复文本。

    Raises:
        LlmCallError: 所有路由候选均不可用或调用失败。
        RuntimeError: 无可用供应商-模型组合。
    """
    from src.llm.router import select_first_available

    pair = select_first_available(session)
    if pair is None:
        raise RuntimeError("无可用 LLM 供应商-模型组合")

    provider, model = pair

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = chat_completion_with_retry(
        provider,
        model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        session=session,
    )

    return response.content if isinstance(response, LLMResponse) else str(response)


__all__ = [
    "LLMResponse",
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
    "quick_chat",
]
