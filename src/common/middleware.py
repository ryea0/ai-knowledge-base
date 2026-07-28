"""请求日志中间件。

等效于 Spring MVC 的 ``HandlerInterceptor + OncePerRequestFilter``，
在 FastAPI 中通过 ASGI middleware 实现。

功能：
    1. 请求进入时生成 traceId（或从 ``X-Request-Id`` 请求头提取），
       放入 :data:`~src.common.trace.trace_id_var`（Python 的 MDC 等价物）。
    2. 响应头回传 ``X-Request-Id``。
    3. 记录每个请求的 method / path / status / 耗时。
    4. 慢请求（>1s）标记 WARNING 级别。
    5. 请求结束时清理 traceId ContextVar。

对应 AGENTS.md §10.3 / §10.6 规范。

Usage::

    from src.common.middleware import RequestLogMiddleware

    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.trace import generate_trace_id, set_trace_id, trace_id_var
from src.config.logging_config import SLOW_REQUEST_THRESHOLD

logger = logging.getLogger(__name__)

# 请求头中的 traceId 字段名
_TRACE_ID_HEADER = "X-Request-Id"

# 需要跳过日志记录的路径（健康检查探针等高频低价值请求）
_SKIP_PATHS: frozenset[str] = frozenset({
    "/health/simple",
})


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求日志中间件。

    拦截所有 HTTP 请求，生成/传递 traceId 并记录请求日志。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """处理请求，注入 traceId 并记录日志。

        Args:
            request: HTTP 请求对象。
            call_next: 下一个中间件/路由处理函数。

        Returns:
            HTTP 响应对象。
        """
        # 跳过高频探针路径
        path = request.url.path
        is_skipped = path in _SKIP_PATHS

        # 生成或提取 traceId
        trace_id = request.headers.get(_TRACE_ID_HEADER) or generate_trace_id()
        token = set_trace_id(trace_id)

        start = time.monotonic()

        try:
            response = await call_next(request)
        finally:
            # 确保 traceId 在请求结束后恢复
            trace_id_var.reset(token)

        if not is_skipped:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            _log_request(request, response, elapsed_ms)

        # 响应头回传 traceId
        response.headers[_TRACE_ID_HEADER] = trace_id
        return response


def _log_request(
    request: Request,
    response: Response,
    elapsed_ms: int,
) -> None:
    """记录请求日志。

    正常请求记录 INFO 级别，慢请求（>1s）记录 WARNING 级别。

    Args:
        request: HTTP 请求对象。
        response: HTTP 响应对象。
        elapsed_ms: 请求耗时（毫秒）。
    """
    method = request.method
    path = request.url.path
    status = response.status_code

    if elapsed_ms > SLOW_REQUEST_THRESHOLD * 1000:
        logger.warning(
            "%s %s -> %d %dms (SLOW)",
            method,
            path,
            status,
            elapsed_ms,
        )
    else:
        logger.info(
            "%s %s -> %d %dms",
            method,
            path,
            status,
            elapsed_ms,
        )


__all__ = ["RequestLogMiddleware"]
