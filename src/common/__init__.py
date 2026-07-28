"""通用模块。

提供跨模块复用的基础设施，如统一 API 响应模型、错误码与业务异常、
全局异常处理器、全局 JSON 时间序列化配置、链路追踪与请求日志中间件。
"""

from src.common.exception_handler import GlobalExceptionHandler
from src.common.exceptions import BizException, ErrorCode
from src.common.json_config import (
    CustomJSONResponse,
    JsonDate,
    JsonDateTime,
)
from src.common.middleware import RequestLogMiddleware
from src.common.response import CODE_FAIL, CODE_SUCCESS, PageResult, Result
from src.common.trace import (
    TraceIdFilter,
    generate_trace_id,
    get_trace_id,
    set_trace_id,
    trace_id_var,
)

__all__ = [
    "BizException",
    "CODE_FAIL",
    "CODE_SUCCESS",
    "CustomJSONResponse",
    "ErrorCode",
    "GlobalExceptionHandler",
    "JsonDate",
    "JsonDateTime",
    "PageResult",
    "RequestLogMiddleware",
    "Result",
    "TraceIdFilter",
    "generate_trace_id",
    "get_trace_id",
    "set_trace_id",
    "trace_id_var",
]
