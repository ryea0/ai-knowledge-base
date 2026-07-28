"""src.common.middleware 的单元测试。

测试覆盖：
- RequestLogMiddleware: traceId 生成/传递/清理、请求日志记录、慢请求 WARN
- X-Request-Id 请求头提取与响应头回传
- 跳过路径（/health/simple）
"""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from src.common.middleware import RequestLogMiddleware
from src.common.trace import get_trace_id, trace_id_var


def _create_test_app() -> FastAPI:
    """创建测试用 FastAPI 应用，注册 RequestLogMiddleware。

    Returns:
        配置好中间件的 FastAPI 应用实例。
    """
    app = FastAPI()

    app.add_middleware(RequestLogMiddleware)

    @app.get("/")
    async def index() -> JSONResponse:
        return JSONResponse({"trace_id": get_trace_id()})

    @app.get("/slow")
    async def slow() -> JSONResponse:
        import asyncio

        await asyncio.sleep(0.1)
        return JSONResponse({"status": "ok"})

    @app.get("/health/simple")
    async def health_simple() -> JSONResponse:
        return JSONResponse({"status": "up"})

    return app


@pytest.fixture
def _cleanup_trace() -> Generator[None, None, None]:
    """每个测试前后确保 trace_id 恢复默认。"""
    trace_id_var.set("-")
    yield
    trace_id_var.set("-")


class TestRequestLogMiddleware:
    """RequestLogMiddleware 测试。"""

    def test_trace_id_generated(self, _cleanup_trace: None) -> None:
        """未传 X-Request-Id 时自动生成 traceId。"""
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/")
        assert resp.status_code == 200
        # 响应头回传 traceId
        assert "X-Request-Id" in resp.headers
        tid = resp.headers["X-Request-Id"]
        assert len(tid) == 8
        # 响应体中的 traceId 与响应头一致
        assert resp.json()["trace_id"] == tid

    def test_trace_id_from_header(self, _cleanup_trace: None) -> None:
        """传入 X-Request-Id 时使用该值。"""
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/", headers={"X-Request-Id": "custom123"})
        assert resp.status_code == 200
        assert resp.headers["X-Request-Id"] == "custom123"
        assert resp.json()["trace_id"] == "custom123"

    def test_trace_id_cleaned_after_request(
        self, _cleanup_trace: None
    ) -> None:
        """请求结束后 traceId 恢复默认值。"""
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.json()["trace_id"] != "-"
        # 请求结束后 ContextVar 恢复
        assert get_trace_id() == "-"

    def test_request_logged(self, _cleanup_trace: None, caplog) -> None:  # type: ignore[no-untyped-def]
        """正常请求记录 INFO 级别日志。"""
        app = _create_test_app()
        with TestClient(app) as client, caplog.at_level(
            logging.INFO, logger="src.common.middleware"
        ):
            client.get("/")
        log_msgs = [r.message for r in caplog.records]
        assert any("GET /" in m and "200" in m for m in log_msgs)

    def test_slow_request_warned(
        self, _cleanup_trace: None, caplog
    ) -> None:  # type: ignore[no-untyped-def]
        """慢请求记录 WARNING 级别日志。

        注意：TestClient 同步执行，asyncio.sleep 在 TestClient 内实际阻塞，
        耗时确实会被记录。但由于 0.1s < 1s 阈值，这里测试的是非慢请求场景。
        慢请求标记通过 _log_request 的逻辑分支覆盖（见下方的单元测试）。
        """
        app = _create_test_app()
        with TestClient(app) as client, caplog.at_level(
            logging.INFO, logger="src.common.middleware"
        ):
            client.get("/slow")
        log_msgs = [r.message for r in caplog.records]
        assert any("GET /slow" in m for m in log_msgs)

    def test_skip_path(self, _cleanup_trace: None, caplog) -> None:  # type: ignore[no-untyped-def]
        """/health/simple 跳过日志记录。"""
        app = _create_test_app()
        with TestClient(app) as client, caplog.at_level(
            logging.INFO, logger="src.common.middleware"
        ):
            client.get("/health/simple")
        log_msgs = [r.message for r in caplog.records]
        # 不应有 /health/simple 的请求日志
        assert not any("/health/simple" in m for m in log_msgs)

    def test_trace_id_per_request(self, _cleanup_trace: None) -> None:
        """每个请求生成独立 traceId。"""
        app = _create_test_app()
        with TestClient(app) as client:
            resp1 = client.get("/")
            resp2 = client.get("/")
        tid1 = resp1.headers["X-Request-Id"]
        tid2 = resp2.headers["X-Request-Id"]
        assert tid1 != tid2

    def test_different_methods(self, _cleanup_trace: None) -> None:
        """不同 HTTP 方法正确记录。"""
        app = FastAPI()
        app.add_middleware(RequestLogMiddleware)

        @app.api_route("/test", methods=["GET", "POST"])
        async def test_endpoint() -> JSONResponse:
            return JSONResponse({"method": "ok"})

        with TestClient(app) as client:
            get_resp = client.get("/test")
            post_resp = client.post("/test")
        assert get_resp.status_code == 200
        assert post_resp.status_code == 200
        assert "X-Request-Id" in get_resp.headers
        assert "X-Request-Id" in post_resp.headers


class TestLogRequestFunction:
    """_log_request 函数的单元测试。"""

    def test_slow_request_warning(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """慢请求（>1s）标记 WARNING。"""
        from starlette.requests import Request
        from starlette.responses import Response

        from src.common.middleware import _log_request

        # 构造 mock request / response
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/slow-endpoint",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        response = Response(status_code=200)

        with caplog.at_level(logging.DEBUG, logger="src.common.middleware"):
            _log_request(request, response, elapsed_ms=1500)

        assert any(
            r.levelno == logging.WARNING and "SLOW" in r.message
            for r in caplog.records
        )

    def test_normal_request_info(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """正常请求记录 INFO。"""
        from starlette.requests import Request
        from starlette.responses import Response

        from src.common.middleware import _log_request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/data",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        response = Response(status_code=201)

        with caplog.at_level(logging.DEBUG, logger="src.common.middleware"):
            _log_request(request, response, elapsed_ms=50)

        assert any(
            r.levelno == logging.INFO and "POST" in r.message and "201" in r.message
            for r in caplog.records
        )

    def test_exact_threshold_is_info(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """恰好 1000ms 是 INFO（>1000 才是 WARN）。"""
        from starlette.requests import Request
        from starlette.responses import Response

        from src.common.middleware import _log_request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/edge",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        response = Response(status_code=200)

        with caplog.at_level(logging.DEBUG, logger="src.common.middleware"):
            _log_request(request, response, elapsed_ms=1000)

        assert any(
            r.levelno == logging.INFO for r in caplog.records
        )
        assert not any(
            r.levelno == logging.WARNING for r in caplog.records
        )
