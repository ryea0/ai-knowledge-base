"""统一 API 响应模型。

提供标准化的接口响应封装，所有 HTTP 接口返回须使用 ``Result`` 或 ``PageResult``。
基于 Pydantic v2 泛型支持，可在类型注解中指定 ``data`` 的具体类型，
如 ``Result[ArticleResponse]``、``PageResult[ArticleResponse]``，
配合 mypy 静态检查确保类型安全。

Python 泛型说明：
    Python 通过 ``typing.TypeVar`` + ``typing.Generic[T]`` 支持泛型；
    PEP 695（Python 3.12+）提供了更简洁的 ``class Result[T]`` 类型参数语法，
    本模块采用该语法（项目要求 Python >=3.12）。
    使用泛型是为了让 ``data`` 字段在不同接口中携带具体类型，
    使 mypy 能在调用侧推断出 ``result.data`` 的真实类型，避免 ``Any`` 泄漏。

业界响应规范（AGENTS.md 未显式定义接口响应格式，此处参照主流实践补充）：
    - ``code``: 业务状态码，0 表示成功，非 0 表示失败。
    - ``message``: 人类可读的提示信息。
    - ``data``: 业务数据，成功时携带，失败时为 ``None``。
    - 分页响应额外包含 ``total``（总条数）、``page``（当前页码）、``size``（每页条数）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

CODE_SUCCESS = 0
CODE_FAIL = 1
DEFAULT_SUCCESS_MESSAGE = "success"
DEFAULT_FAIL_MESSAGE = "fail"


class Result[T](BaseModel):
    """统一响应模型。

    Attributes:
        code: 业务状态码，0=成功，非 0=失败。
        message: 提示信息。
        data: 业务数据，失败时为 ``None``。
    """

    model_config = ConfigDict(extra="forbid")

    code: int = Field(..., description="业务状态码，0=成功，非 0=失败")
    message: str = Field(..., description="提示信息")
    data: T | None = Field(None, description="业务数据，失败时为 None")

    @classmethod
    def ok(
        cls,
        data: T | None = None,
        message: str = DEFAULT_SUCCESS_MESSAGE,
    ) -> Result[T]:
        """构造成功响应。

        Args:
            data: 业务数据。
            message: 提示信息，默认 ``"success"``。

        Returns:
            code=0 的成功响应实例。
        """
        return cls(code=CODE_SUCCESS, message=message, data=data)

    @classmethod
    def fail(
        cls,
        message: str = DEFAULT_FAIL_MESSAGE,
        code: int = CODE_FAIL,
        data: T | None = None,
    ) -> Result[T]:
        """构造失败响应。

        Args:
            message: 失败提示信息。
            code: 业务状态码，默认 1。
            data: 附加数据，一般不填。

        Returns:
            非 0 code 的失败响应实例。
        """
        return cls(code=code, message=message, data=data)


class PageResult[T](Result[T]):
    """分页响应模型，继承 :class:`Result`。

    额外携带分页元信息：``total`` / ``page`` / ``size``。

    Attributes:
        total: 总条数。
        page: 当前页码，从 1 开始。
        size: 每页条数。
    """

    total: int = Field(0, ge=0, description="总条数")
    page: int = Field(1, ge=1, description="当前页码，从 1 开始")
    size: int = Field(10, ge=1, description="每页条数")

    @classmethod
    def ok(
        cls,
        data: T | None = None,
        message: str = DEFAULT_SUCCESS_MESSAGE,
        *,
        total: int = 0,
        page: int = 1,
        size: int = 10,
    ) -> PageResult[T]:
        """构造分页成功响应。

        分页参数 ``total`` / ``page`` / ``size`` 为 keyword-only，
        以保持与父类 :meth:`Result.ok` 签名的 LSP 兼容。

        Args:
            data: 当前页数据列表。
            message: 提示信息，默认 ``"success"``。
            total: 总条数。
            page: 当前页码，从 1 开始。
            size: 每页条数。

        Returns:
            code=0 的分页响应实例。
        """
        return cls(
            code=CODE_SUCCESS,
            message=message,
            data=data,
            total=total,
            page=page,
            size=size,
        )


__all__ = [
    "CODE_FAIL",
    "CODE_SUCCESS",
    "DEFAULT_FAIL_MESSAGE",
    "DEFAULT_SUCCESS_MESSAGE",
    "PageResult",
    "Result",
]
