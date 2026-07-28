"""src.common.response 的单元测试。

测试覆盖：
- Result.ok / Result.fail 工厂方法
- Result 泛型类型约束
- PageResult 继承与额外字段
- PageResult.ok 工厂方法
- 序列化正确性
- extra='forbid' 约束
- 分页字段边界值校验
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.response import (
    CODE_FAIL,
    CODE_SUCCESS,
    PageResult,
    Result,
)


class TestResultOk:
    """Result.ok 测试。"""

    def test_ok_with_data(self) -> None:
        """成功响应携带数据。"""
        result = Result[str].ok("hello")
        assert result.code == CODE_SUCCESS
        assert result.message == "success"
        assert result.data == "hello"

    def test_ok_without_data(self) -> None:
        """成功响应不携带数据时 data 为 None。"""
        result = Result[None].ok()
        assert result.code == 0
        assert result.data is None

    def test_ok_custom_message(self) -> None:
        """自定义 message。"""
        result = Result[str].ok("data", message="created")
        assert result.message == "created"

    def test_ok_with_dict_data(self) -> None:
        """dict 类型数据。"""
        payload = {"id": 1, "title": "test"}
        result = Result[dict].ok(payload)  # type: ignore[type-arg]
        assert result.data == payload


class TestResultFail:
    """Result.fail 测试。"""

    def test_fail_default(self) -> None:
        """默认失败响应。"""
        result = Result[None].fail()
        assert result.code == CODE_FAIL
        assert result.message == "fail"
        assert result.data is None

    def test_fail_custom_message(self) -> None:
        """自定义失败消息。"""
        result = Result[None].fail(message="参数错误")
        assert result.message == "参数错误"

    def test_fail_custom_code(self) -> None:
        """自定义失败码。"""
        result = Result[None].fail(message="未授权", code=401)
        assert result.code == 401

    def test_fail_with_data(self) -> None:
        """失败响应携带附加数据。"""
        result = Result[dict].fail(message="校验失败", data={"field": "name"})  # type: ignore[type-arg]
        assert result.data == {"field": "name"}


class TestResultSerialization:
    """Result 序列化测试。"""

    def test_model_dump(self) -> None:
        """model_dump 输出包含三个字段。"""
        result = Result[str].ok("hello")
        dumped = result.model_dump()
        assert dumped == {"code": 0, "message": "success", "data": "hello"}

    def test_model_dump_none_data(self) -> None:
        """data 为 None 时正确序列化。"""
        result = Result[None].fail("error")
        dumped = result.model_dump()
        assert dumped == {"code": 1, "message": "error", "data": None}

    def test_extra_field_forbidden(self) -> None:
        """禁止额外字段。"""
        with pytest.raises(ValidationError):
            Result[str](  # type: ignore[call-arg]
                code=0,
                message="ok",
                data="x",
                extra="bad",
            )


class TestPageResult:
    """PageResult 测试。"""

    def test_inherits_from_result(self) -> None:
        """PageResult 是 Result 的子类。"""
        assert issubclass(PageResult, Result)

    def test_ok_with_pagination(self) -> None:
        """分页成功响应携带分页字段。"""
        items = ["a", "b", "c"]
        result = PageResult[list[str]].ok(data=items, total=100, page=2, size=3)
        assert result.code == 0
        assert result.message == "success"
        assert result.data == items
        assert result.total == 100
        assert result.page == 2
        assert result.size == 3

    def test_ok_defaults(self) -> None:
        """默认分页值。"""
        result = PageResult[list[str]].ok(data=[])
        assert result.total == 0
        assert result.page == 1
        assert result.size == 10

    def test_page_result_serialization(self) -> None:
        """分页响应序列化包含所有字段。"""
        result = PageResult[list[str]].ok(data=["x"], total=5, page=1, size=10)
        dumped = result.model_dump()
        assert dumped == {
            "code": 0,
            "message": "success",
            "data": ["x"],
            "total": 5,
            "page": 1,
            "size": 10,
        }

    def test_negative_total_rejected(self) -> None:
        """total 不能为负。"""
        with pytest.raises(ValidationError):
            PageResult[list[str]].ok(data=[], total=-1)

    def test_zero_page_rejected(self) -> None:
        """page 不能小于 1。"""
        with pytest.raises(ValidationError):
            PageResult[list[str]].ok(data=[], page=0)

    def test_zero_size_rejected(self) -> None:
        """size 不能小于 1。"""
        with pytest.raises(ValidationError):
            PageResult[list[str]].ok(data=[], size=0)

    def test_page_result_fail_inherited(self) -> None:
        """PageResult 继承 Result.fail。"""
        result = PageResult[list[str]].fail(message="查询失败")
        assert result.code == CODE_FAIL
        assert result.message == "查询失败"
        assert result.data is None
