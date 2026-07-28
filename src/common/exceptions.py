"""统一错误码与业务异常。

定义全局业务错误码枚举 :class:`ErrorCode` 和业务异常 :class:`BizException`。
错误码设计参照业界 HTTP 风格分段：

    - ``1xxxx``: 通用错误（参数校验、鉴权、系统内部错误等）
    - ``2xxxx``: 知识条目业务错误（保留扩展）
    - ``3xxxx``: LLM 供应商业务错误（保留扩展）

``BizException`` 持有一个 :class:`ErrorCode`，支持用自定义 ``message`` 覆盖
枚举默认消息；异常捕获方可通过 ``error_code`` 属性获取结构化错误码，
用于 API 响应映射或日志聚合。

与 ``Result`` 的关系：
    异常处理层捕获 :class:`BizException` 后，可将其转换为
    ``Result.fail(message=exc.message, code=exc.error_code.code)`` 响应。
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码枚举。

    每个成员携带一个默认 ``message``（通过 ``message`` 属性访问）。
    新增错误码须遵循分段约定，并在本枚举中集中定义，禁止散落在业务代码中。

    成员的整数值即对外暴露的业务状态码（对应 :class:`Result.code`），
    0 保留给成功（见 ``response.CODE_SUCCESS``），错误码均 > 0。
    """

    # --- 通用错误 1xxxx ---
    SYSTEM_ERROR = 10000
    PARAM_ERROR = 10001
    UNAUTHORIZED = 10002
    FORBIDDEN = 10003
    NOT_FOUND = 10004
    METHOD_NOT_ALLOWED = 10005
    RATE_LIMITED = 10006
    INTERNAL_ERROR = 10007

    @property
    def message(self) -> str:
        """错误码对应的默认提示信息。"""
        return _ERROR_MESSAGES[self]


_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.SYSTEM_ERROR: "系统错误",
    ErrorCode.PARAM_ERROR: "参数错误",
    ErrorCode.UNAUTHORIZED: "未授权，请先登录",
    ErrorCode.FORBIDDEN: "禁止访问",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "请求方法不允许",
    ErrorCode.RATE_LIMITED: "请求过于频繁，请稍后再试",
    ErrorCode.INTERNAL_ERROR: "系统内部错误",
}


class BizException(Exception):
    """业务异常。

    用于在业务逻辑中抛出可预期的错误，由上层异常处理层统一捕获并转换为
    :class:`Result.fail` 响应。非业务异常（如网络错误、DB 异常）不应包装为
    本异常，应直接抛出或包装为 ``RuntimeError``。

    Attributes:
        error_code: 错误码枚举成员。
        message: 实际提示信息，未自定义时取 ``error_code.message``。
    """

    def __init__(
        self,
        error_code: ErrorCode,
        message: str | None = None,
    ) -> None:
        """初始化业务异常。

        Args:
            error_code: 错误码枚举成员。
            message: 自定义提示信息，为 ``None`` 时使用错误码默认消息。
        """
        self.error_code: ErrorCode = error_code
        self.message: str = message if message is not None else error_code.message
        super().__init__(self.message)

    def __str__(self) -> str:
        """返回 ``[code] message`` 格式的简短描述。"""
        return f"[{self.error_code.value}] {self.message}"


__all__ = ["BizException", "ErrorCode"]
