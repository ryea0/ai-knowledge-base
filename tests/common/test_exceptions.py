"""src.common.exceptions 的单元测试。

测试覆盖：
- ErrorCode 枚举值与 message 属性
- BizException 默认 message（取自 ErrorCode）
- BizException 自定义 message 覆盖
- BizException 作为 Exception 的行为（捕获、str、继承）
- error_code 属性访问
"""

from __future__ import annotations

import pytest

from src.common.exceptions import BizException, ErrorCode


class TestErrorCode:
    """ErrorCode 枚举测试。"""

    def test_enum_values_unique(self) -> None:
        """所有错误码值唯一且 > 0。"""
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))
        assert all(v > 0 for v in values)

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (ErrorCode.SYSTEM_ERROR, "系统错误"),
            (ErrorCode.PARAM_ERROR, "参数错误"),
            (ErrorCode.UNAUTHORIZED, "未授权，请先登录"),
            (ErrorCode.FORBIDDEN, "禁止访问"),
            (ErrorCode.NOT_FOUND, "资源不存在"),
            (ErrorCode.METHOD_NOT_ALLOWED, "请求方法不允许"),
            (ErrorCode.RATE_LIMITED, "请求过于频繁，请稍后再试"),
            (ErrorCode.INTERNAL_ERROR, "系统内部错误"),
        ],
    )
    def test_message(self, code: ErrorCode, expected: str) -> None:
        """每个错误码有对应的默认 message。"""
        assert code.message == expected

    def test_all_codes_have_messages(self) -> None:
        """所有枚举成员均有 message 映射。"""
        for code in ErrorCode:
            assert code.message  # 非空字符串


class TestBizExceptionDefault:
    """BizException 默认 message 测试。"""

    def test_default_message(self) -> None:
        """不传 message 时使用错误码默认消息。"""
        exc = BizException(ErrorCode.PARAM_ERROR)
        assert exc.message == "参数错误"

    def test_error_code_attribute(self) -> None:
        """error_code 属性正确持有枚举成员。"""
        exc = BizException(ErrorCode.NOT_FOUND)
        assert exc.error_code is ErrorCode.NOT_FOUND

    def test_message_none_uses_default(self) -> None:
        """显式传 None 时也使用默认消息。"""
        exc = BizException(ErrorCode.UNAUTHORIZED, message=None)
        assert exc.message == "未授权，请先登录"


class TestBizExceptionCustomMessage:
    """BizException 自定义 message 测试。"""

    def test_custom_message(self) -> None:
        """自定义 message 覆盖默认消息。"""
        exc = BizException(ErrorCode.PARAM_ERROR, message="标题不能为空")
        assert exc.message == "标题不能为空"
        assert exc.error_code is ErrorCode.PARAM_ERROR

    def test_custom_message_empty_string(self) -> None:
        """空字符串作为自定义 message（不回退到默认）。"""
        exc = BizException(ErrorCode.SYSTEM_ERROR, message="")
        assert exc.message == ""

    def test_custom_message_does_not_change_error_code(self) -> None:
        """自定义 message 不影响 error_code。"""
        exc = BizException(ErrorCode.FORBIDDEN, message="无权操作此条目")
        assert exc.error_code is ErrorCode.FORBIDDEN
        assert exc.error_code.message == "禁止访问"


class TestBizExceptionBehavior:
    """BizException 异常行为测试。"""

    def test_is_exception_subclass(self) -> None:
        """BizException 是 Exception 的子类。"""
        assert issubclass(BizException, Exception)

    def test_raisable_and_catchable(self) -> None:
        """可作为异常抛出和捕获。"""
        with pytest.raises(BizException) as exc_info:
            raise BizException(ErrorCode.INTERNAL_ERROR)
        assert exc_info.value.error_code is ErrorCode.INTERNAL_ERROR

    def test_catchable_as_exception(self) -> None:
        """可被通用 Exception 捕获。"""
        with pytest.raises(Exception) as exc_info:  # noqa: PT011
            raise BizException(ErrorCode.RATE_LIMITED)
        assert isinstance(exc_info.value, BizException)

    def test_str_format(self) -> None:
        """__str__ 返回 [code] message 格式。"""
        exc = BizException(ErrorCode.PARAM_ERROR, message="字段缺失")
        assert str(exc) == "[10001] 字段缺失"

    def test_str_default_message(self) -> None:
        """__str__ 使用默认消息时格式正确。"""
        exc = BizException(ErrorCode.NOT_FOUND)
        assert str(exc) == "[10004] 资源不存在"

    def test_args_passed_to_base(self) -> None:
        """super().__init__ 传入 message，args 可访问。"""
        exc = BizException(ErrorCode.SYSTEM_ERROR)
        assert exc.args == ("系统错误",)
