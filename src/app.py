"""FastAPI 应用工厂。

创建并配置 FastAPI 应用实例，注册全局异常处理器和路由。
类似 Spring Boot 的 ``SpringApplication.run()``，是 Web 应用的入口。

注册的路由：
    - ``GET /health``: 完整健康检查（DB + LLM + 分发渠道）
    - ``GET /health/simple``: 简易存活探针（livenessProbe）
    - ``GET /health/info``: 应用信息（readinessProbe info）
    - ``GET /``: 根路径重定向到 ``/health``

Usage::

    from src.app import create_app

    app = create_app()

    # 开发模式运行
    # uvicorn src.app:create_app --factory --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.api.llm_routes import router as llm_router
from src.api.metrics_routes import router as metrics_router
from src.common.exception_handler import GlobalExceptionHandler
from src.common.health import (
    AppInfo,
    HealthResponse,
    get_app_info,
    perform_health_check,
    should_http_503,
)
from src.common.json_config import CustomJSONResponse
from src.common.middleware import RequestLogMiddleware
from src.config.database import get_db
from src.config.logging_config import setup_logging
from src.llm.scheduler import start_connectivity_scheduler, stop_connectivity_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动/停止定时任务。"""
    start_connectivity_scheduler()
    yield
    stop_connectivity_scheduler()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    Returns:
        配置好的 FastAPI 应用实例。
    """
    setup_logging()

    app = FastAPI(
        title="AI 知识库助手",
        description="自动采集 AI/LLM/Agent 领域技术动态的知识库系统",
        version="0.1.0",
        default_response_class=CustomJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(RequestLogMiddleware)

    GlobalExceptionHandler.register(app)

    _register_health_routes(app)

    app.include_router(llm_router)
    app.include_router(metrics_router)

    logger.info("FastAPI 应用创建完成")
    return app


def _register_health_routes(app: FastAPI) -> None:
    """注册健康检查相关路由。

    Args:
        app: FastAPI 应用实例。
    """

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """根路径重定向到健康检查端点。"""
        return RedirectResponse(url="/health")

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["健康检查"],
        summary="完整健康检查",
        description="检查数据库连通性、LLM 供应商健康摘要和分发渠道配置状态。"
        "整体状态为 down 时返回 HTTP 503。",
    )
    def health_check(
        db: Annotated[Session, Depends(get_db)],
    ) -> CustomJSONResponse:
        """执行完整健康检查。

        检查 DB 连通性、LLM 供应商状态、分发渠道配置。
        整体状态为 ``down`` 时返回 HTTP 503，否则 200。
        """
        result = perform_health_check(db)
        status_code = 503 if should_http_503(result.status) else 200
        return CustomJSONResponse(
            status_code=status_code,
            content=result.model_dump(),
        )

    @app.get(
        "/health/simple",
        tags=["健康检查"],
        summary="存活探针",
        description="简易存活探针，仅检查应用进程存活，始终返回 HTTP 200。"
        "适合 K8s livenessProbe。",
    )
    def liveness() -> dict[str, str]:
        """存活探针。

        Returns:
            ``{"status": "up"}`` 字典。
        """
        return {"status": "up"}

    @app.get(
        "/health/info",
        response_model=AppInfo,
        tags=["健康检查"],
        summary="应用信息",
        description="返回应用名称、版本、Python 版本和运行平台。"
        "适合 K8s readinessProbe 的信息展示。",
    )
    def readiness_info() -> AppInfo:
        """应用信息。

        Returns:
            应用信息对象。
        """
        return get_app_info()


__all__ = ["create_app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        reload=True,
    )
