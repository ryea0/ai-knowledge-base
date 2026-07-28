"""src.common.exception_handler 的单元测试。

测试覆盖：
- GlobalExceptionHandler.register 注册后各异常处理器生效
- BizException -> Result.fail(code=exc.error_code), HTTP 200
- RequestValidationError -> Result.fail(code=PARAM_ERROR), HTTP 422
- ValidationError (Pydantic) -> Result.fail(code=PARAM_ERROR), HTTP 422
- Exception 兜底 -> Result.fail(code=INTERNAL_ERROR), HTTP 500
- 所有响应 body 均含 code/message/data 三字段
- 自定义 message 的 BizException 透传
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from src.common.exception_handler import GlobalExceptionHandler
from src.common.exceptions import BizException, ErrorCode


class _Item(BaseModel):
    """测试用请求体模型。"""

    name: str = Field(..., min_length=1, max_length=10)
    age: int = Field(..., ge=0)


def _create_app() -> FastAPI:
    """创建注册了全局异常处理器的测试用 FastAPI 应用。

    Returns:
        注册了异常处理器的 FastAPI 实例。
    """
    app = FastAPI()

    GlobalExceptionHandler.register(app)

    @app.get("/biz")
    def _biz() -> dict[str, str]:
        raise BizException(ErrorCode.NOT_FOUND, message="文章不存在")

    @app.get("/biz/default")
    def _biz_default() -> dict[str, str]:
        raise BizException(ErrorCode.UNAUTHORIZED)

    @app.post("/validation")
    def _validation(item: _Item) -> dict[str, str]:
        return {"name": item.name}

    @app.get("/pydantic")
    def _pydantic() -> dict[str, str]:
        raise ValidationError.from_exception_data(
            "Item",
            [
                {
                    "type": "missing",
                    "loc": ("name",),
                    "input": {},
                    "ctx": {"field": "name"},
                }
            ],
        )

    @app.get("/generic")
    def _generic() -> dict[str, str]:
        raise RuntimeError("unexpected boom")

    @app.get("/ok")
    def _ok() -> dict[str, str]:
        return {"msg": "hello"}

    return app


class TestBizExceptionHandler:
    """BizException 处理测试。"""

    def test_biz_exception_with_custom_message(self) -> None:
        """BizException 自定义 message 透传，HTTP 200。"""
        client = TestClient(_create_app())
        resp = client.get("/biz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ErrorCode.NOT_FOUND.value
        assert body["message"] == "文章不存在"
        assert body["data"] is None

    def test_biz_exception_default_message(self) -> None:
        """BizException 默认 message（取自 ErrorCode），HTTP 200。"""
        client = TestClient(_create_app())
        resp = client.get("/biz/default")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ErrorCode.UNAUTHORIZED.value
        assert body["message"] == ErrorCode.UNAUTHORIZED.message


class TestValidationExceptionHandler:
    """参数校验异常处理测试。"""

    def test_request_validation_error(self) -> None:
        """RequestValidationError -> PARAM_ERROR, HTTP 422。"""
        client = TestClient(_create_app())
        resp = client.post("/validation", json={"name": "", "age": -1})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == ErrorCode.PARAM_ERROR.value
        assert body["data"] is not None
        assert isinstance(body["data"], list)

    def test_request_validation_missing_field(self) -> None:
        """缺少必填字段触发 RequestValidationError。"""
        client = TestClient(_create_app())
        resp = client.post("/validation", json={"age": 5})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == ErrorCode.PARAM_ERROR.value
        assert "name" in body["message"]

    def test_validation_error_pydantic(self) -> None:
        """Pydantic ValidationError -> PARAM_ERROR, HTTP 422。"""
        client = TestClient(_create_app())
        resp = client.get("/pydantic")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == ErrorCode.PARAM_ERROR.value
        assert body["message"]  # 非空

    def test_validation_message_contains_field_info(self) -> None:
        """参数校验 message 包含字段定位信息。"""
        client = TestClient(_create_app())
        resp = client.post("/validation", json={"name": "", "age": -1})
        body = resp.json()
        assert "name" in body["message"] or "age" in body["message"]


class TestGenericExceptionHandler:
    """兜底 Exception 处理测试。"""

    def test_generic_exception(self) -> None:
        """未捕获异常 -> INTERNAL_ERROR, HTTP 500。"""
        client = TestClient(_create_app(), raise_server_exceptions=False)
        resp = client.get("/generic")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == ErrorCode.INTERNAL_ERROR.value
        assert body["message"] == ErrorCode.INTERNAL_ERROR.message
        assert body["data"] is None

    def test_generic_exception_no_stack_leak(self) -> None:
        """兜底响应不泄露内部堆栈信息。"""
        client = TestClient(_create_app(), raise_server_exceptions=False)
        resp = client.get("/generic")
        body = resp.json()
        assert "boom" not in body["message"]


class TestNormalRequest:
    """正常请求不受异常处理器影响。"""

    def test_ok_response(self) -> None:
        """正常请求返回 200。"""
        client = TestClient(_create_app())
        resp = client.get("/ok")
        assert resp.status_code == 200
        assert resp.json() == {"msg": "hello"}
