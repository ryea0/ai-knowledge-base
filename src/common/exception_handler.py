"""全局异常处理器。

注册 FastAPI 异常处理器，将各类异常统一转换为 :class:`Result.fail` 响应，
确保所有错误响应携带结构化 ``code``（来自 :class:`ErrorCode` 枚举）和 ``message``。

处理顺序（FastAPI 按异常类型精确匹配，非顺序优先）：

    - :class:`BizException`           -> 使用 ``exc.error_code``，HTTP 200
    - :class:`RequestValidationError` -> :attr:`ErrorCode.PARAM_ERROR`，HTTP 422
    - :class:`ValidationError`        -> :attr:`ErrorCode.PARAM_ERROR`，HTTP 422
    - :class:`Exception`（兜底）       -> :attr:`ErrorCode.INTERNAL_ERROR`，HTTP 500

设计说明：
    - 所有异常响应均通过 :meth:`Result.fail` 构造，``code`` 取自 :class:`ErrorCode`
      枚举的整数值，禁止硬编码数字。
    - 业务异常的 HTTP 状态码返回 200（错误信息在 body 的 ``code`` 字段中表达），
      遵循「业务错误不等于 HTTP 错误」的 API 设计实践；
      参数校验错误返回 422，未知异常返回 500，便于网关/监控层区分。
    - 兜底处理 ``Exception`` 时，日志级别为 ``ERROR`` 并附带 traceback，
      但 ``message`` 不暴露内部堆栈细节，仅返回通用提示。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from src.common.exceptions import BizException, ErrorCode
from src.common.json_config import CustomJSONResponse
from src.common.response import Result

logger = logging.getLogger(__name__)


def _build_response(
    error_code: ErrorCode,
    message: str,
    *,
    status_code: int = 200,
) -> CustomJSONResponse:
    """从 ErrorCode 构建 CustomJSONResponse。

    Args:
        error_code: 错误码枚举成员。
        message: 实际提示信息。
        status_code: HTTP 状态码。

    Returns:
        包含 ``Result.fail`` body 的 CustomJSONResponse。
    """
    result: Result[Any] = Result.fail(
        message=message,
        code=error_code.value,
    )
    return CustomJSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


async def biz_exception_handler(request: Request, exc: Exception) -> CustomJSONResponse:
    """处理 :class:`BizException`。

    使用异常携带的 ``error_code`` 和 ``message`` 构造响应。
    参数类型为 ``Exception`` 以满足 Starlette 处理器签名约定，
    仅注册到 :class:`BizException`，调用时必为该类型。

    Args:
        request: 触发异常的请求（用于日志上下文）。
        exc: 捕获的业务异常。

    Returns:
        HTTP 200 的 ``Result.fail`` 响应。
    """
    biz_exc = cast(BizException, exc)
    logger.warning(
        "业务异常: %s %s -> %s",
        request.method,
        request.url.path,
        biz_exc,
    )
    return _build_response(
        biz_exc.error_code,
        biz_exc.message,
    )


async def validation_exception_handler(
    request: Request,
    exc: Exception,
) -> CustomJSONResponse:
    """处理参数校验异常。

    将 FastAPI / Pydantic 的校验错误统一映射为 :attr:`ErrorCode.PARAM_ERROR`，
    ``message`` 汇总各字段错误信息，``data`` 携带原始错误详情。
    参数类型为 ``Exception`` 以满足 Starlette 处理器签名约定，
    仅注册到 :class:`RequestValidationError` 和 :class:`ValidationError`。

    Args:
        request: 触发异常的请求。
        exc: 校验异常。

    Returns:
        HTTP 422 的 ``Result.fail`` 响应。
    """
    val_exc = cast(RequestValidationError | ValidationError, exc)
    errors: list[Any] = list(val_exc.errors()) if hasattr(val_exc, "errors") else []
    field_msgs: list[str] = []
    for err in errors:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "")
        field_msgs.append(f"{loc}: {msg}" if loc else msg)
    message = "; ".join(field_msgs) if field_msgs else ErrorCode.PARAM_ERROR.message

    logger.info(
        "参数校验失败: %s %s -> %s",
        request.method,
        request.url.path,
        message,
    )
    result: Result[list[Any]] = Result.fail(
        message=message,
        code=ErrorCode.PARAM_ERROR.value,
        data=errors if errors else None,
    )
    return CustomJSONResponse(
        status_code=422,
        content=result.model_dump(mode="json"),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> CustomJSONResponse:
    """兜底处理所有未捕获异常。

    记录 ERROR 级别日志（含 traceback），对外仅返回通用提示，
    不泄露内部堆栈信息。

    Args:
        request: 触发异常的请求。
        exc: 捕获的未知异常。

    Returns:
        HTTP 500 的 ``Result.fail`` 响应。
    """
    logger.error(
        "未捕获异常: %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _build_response(
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.INTERNAL_ERROR.message,
        status_code=500,
    )


class GlobalExceptionHandler:
    """全局异常处理器注册器。

    通过 :meth:`register` 将所有异常处理器注册到 FastAPI 应用实例。
    所有响应均使用 :meth:`Result.fail` 构造，``code`` 取自 :class:`ErrorCode`。

    Usage::

        app = FastAPI()
        handler = GlobalExceptionHandler()
        handler.register(app)
    """

    @staticmethod
    def register(app: FastAPI) -> None:
        """注册全部异常处理器到 FastAPI 应用。

        Args:
            app: FastAPI 应用实例。
        """
        app.add_exception_handler(BizException, biz_exception_handler)
        app.add_exception_handler(RequestValidationError, validation_exception_handler)
        app.add_exception_handler(ValidationError, validation_exception_handler)
        app.add_exception_handler(Exception, generic_exception_handler)


__all__ = ["GlobalExceptionHandler"]
