"""应用级健康检查端点。

提供类似 Spring Boot Actuator ``/actuator/health`` 的应用健康检查功能，
检查数据库连通性、LLM 供应商健康摘要和分发渠道配置状态。

与 :mod:`src.llm.health` 的区别：
    - :mod:`src.llm.health` 是 LLM 供应商级别的健康检查（类熔断器状态机），
      用于路由决策。
    - 本模块是**应用级**健康检查，聚合各子系统状态供运维监控使用，
      不影响业务路由。

端点设计：
    - ``GET /health``: 完整健康检查（DB + LLM + 分发渠道），
      整体状态为 DOWN 时返回 HTTP 503。
    - ``GET /health/simple``: 简易存活探针，仅检查应用进程存活，
      始终返回 HTTP 200，适合 K8s livenessProbe。
    - ``GET /health/info``: 应用信息（版本、Python 版本），不检查依赖，
      适合 readinessProbe 的信息展示。

健康状态聚合规则：
    - ``UP``: 所有组件均为 UP。
    - ``DEGRADED``: 至少一个组件为 DEGRADED，无 DOWN。
    - ``DOWN``: 至少一个组件为 DOWN。
"""

from __future__ import annotations

import logging
import platform
import sys
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.models.enums import LlmHealthStatus

logger = logging.getLogger(__name__)

_DB_PING_TIMEOUT_SECONDS = 5.0

_UNKNOWN = "unknown"


class ComponentHealth(BaseModel):
    """单个组件的健康状态。

    Attributes:
        status: 组件健康状态，``up`` / ``degraded`` / ``down``。
        details: 组件附加信息，如连接耗时、供应商计数等。
    """

    model_config = {"extra": "forbid"}

    status: str = Field(..., description="组件健康状态: up/degraded/down")
    details: dict[str, Any] = Field(
        default_factory=dict, description="组件附加信息"
    )


class HealthResponse(BaseModel):
    """应用健康检查响应。

    Attributes:
        status: 整体健康状态，``up`` / ``degraded`` / ``down``。
        timestamp: 检查时间（ISO 8601 UTC）。
        components: 各组件健康状态。
    """

    model_config = {"extra": "forbid"}

    status: str = Field(..., description="整体健康状态: up/degraded/down")
    timestamp: str = Field(..., description="检查时间 ISO 8601 UTC")
    components: dict[str, ComponentHealth] = Field(
        default_factory=dict, description="各组件健康状态"
    )


class AppInfo(BaseModel):
    """应用信息。

    Attributes:
        name: 应用名称。
        version: 应用版本。
        python_version: Python 版本。
        platform: 运行平台。
    """

    model_config = {"extra": "forbid"}

    name: str = Field(..., description="应用名称")
    version: str = Field(..., description="应用版本")
    python_version: str = Field(..., description="Python 版本")
    platform: str = Field(..., description="运行平台")


def _now_iso() -> str:
    """返回当前时间的 ISO 8601 UTC 字符串。

    Returns:
        如 ``2026-07-28T08:00:00Z`` 格式的 UTC 时间字符串。
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_database(session: Session) -> ComponentHealth:
    """检查数据库连通性。

    执行 ``SELECT 1`` 并测量响应耗时。
    数据库不可达时状态为 ``down``，超时为 ``degraded``。

    Args:
        session: SQLAlchemy Session。

    Returns:
        数据库组件健康状态。
    """
    start = time.monotonic()
    try:
        session.execute(text("SELECT 1"))
        latency_ms = int((time.monotonic() - start) * 1000)
        if latency_ms > _DB_PING_TIMEOUT_SECONDS * 1000:
            return ComponentHealth(
                status="degraded",
                details={
                    "latency_ms": latency_ms,
                    "message": "数据库响应缓慢",
                },
            )
        logger.debug("数据库健康检查通过, latency=%dms", latency_ms)
        return ComponentHealth(
            status="up",
            details={"latency_ms": latency_ms},
        )
    except OperationalError as exc:
        logger.error("数据库连接失败: %s", exc, exc_info=True)
        return ComponentHealth(
            status="down",
            details={"error": "数据库连接失败"},
        )
    except SQLAlchemyError as exc:
        logger.error("数据库查询异常: %s", exc, exc_info=True)
        return ComponentHealth(
            status="down",
            details={"error": "数据库查询异常"},
        )


def check_llm_providers(session: Session) -> ComponentHealth:
    """检查 LLM 供应商健康摘要。

    统计各健康状态的供应商数量。
    存在 unhealthy 供应商时状态为 ``degraded``（仍可路由到健康供应商）；
    全部 unhealthy 或无可用供应商时状态为 ``down``。

    Args:
        session: SQLAlchemy Session。

    Returns:
        LLM 供应商组件健康状态。
    """
    try:
        stmt = text(
            "SELECT h.health_status, COUNT(*) AS cnt "
            "FROM kb_llm_health h "
            "JOIN kb_llm_provider p ON h.provider_id = p.id "
            "JOIN kb_llm_model m ON h.model_id = m.id "
            "WHERE h.is_deleted = 0 "
            "AND p.is_deleted = 0 AND p.is_enabled = 1 "
            "AND m.is_deleted = 0 AND m.is_enabled = 1 "
            "GROUP BY h.health_status"
        )
        rows = session.execute(stmt).fetchall()
        counts: dict[str, int] = {
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "unknown": 0,
        }
        _status_names = {
            LlmHealthStatus.HEALTHY.value: "healthy",
            LlmHealthStatus.DEGRADED.value: "degraded",
            LlmHealthStatus.UNHEALTHY.value: "unhealthy",
            LlmHealthStatus.UNKNOWN.value: "unknown",
        }
        for row in rows:
            name = _status_names.get(row.health_status, "unknown")
            counts[name] = row.cnt

        total_enabled = sum(counts.values())
        available = counts["healthy"] + counts["degraded"]

        if total_enabled == 0:
            return ComponentHealth(
                status="down",
                details={
                    **counts,
                    "total_enabled": 0,
                    "message": "无启用的 LLM 供应商",
                },
            )

        if available == 0:
            return ComponentHealth(
                status="down",
                details={
                    **counts,
                    "total_enabled": total_enabled,
                    "message": "所有供应商不可用",
                },
            )

        if counts["unhealthy"] > 0 or counts["unknown"] > 0:
            return ComponentHealth(
                status="degraded",
                details={
                    **counts,
                    "total_enabled": total_enabled,
                    "available": available,
                },
            )

        return ComponentHealth(
            status="up",
            details={
                **counts,
                "total_enabled": total_enabled,
                "available": available,
            },
        )
    except SQLAlchemyError as exc:
        logger.error("LLM 供应商健康检查失败: %s", exc, exc_info=True)
        return ComponentHealth(
            status="down",
            details={"error": "查询供应商状态失败"},
        )


def check_distributors() -> ComponentHealth:
    """检查分发渠道配置状态。

    从环境变量读取 Telegram 和飞书配置，至少配置一个渠道为 ``up``，
    否则为 ``down``。

    Returns:
        分发渠道组件健康状态。
    """
    settings = get_settings()
    telegram_configured = settings.distributor.telegram_bot_token is not None
    feishu_configured = settings.distributor.feishu_webhook_url is not None

    channels: dict[str, bool] = {
        "telegram": telegram_configured,
        "feishu": feishu_configured,
    }

    if not telegram_configured and not feishu_configured:
        return ComponentHealth(
            status="down",
            details={
                **{k: ("configured" if v else "not_configured") for k, v in channels.items()},
                "message": "无可用分发渠道",
            },
        )

    return ComponentHealth(
        status="up",
        details={k: ("configured" if v else "not_configured") for k, v in channels.items()},
    )


def aggregate_status(components: dict[str, ComponentHealth]) -> str:
    """聚合各组件状态为整体状态。

    规则：任意 ``down`` -> ``down``；任意 ``degraded`` -> ``degraded``；否则 ``up``。

    Args:
        components: 各组件健康状态。

    Returns:
        整体健康状态字符串。
    """
    statuses = [c.status for c in components.values()]
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    return "up"


def perform_health_check(session: Session) -> HealthResponse:
    """执行完整健康检查。

    依次检查数据库、LLM 供应商、分发渠道，聚合为整体状态。

    Args:
        session: SQLAlchemy Session。

    Returns:
        完整健康检查响应。
    """
    components: dict[str, ComponentHealth] = {
        "database": check_database(session),
        "llm_providers": check_llm_providers(session),
        "distributors": check_distributors(),
    }
    return HealthResponse(
        status=aggregate_status(components),
        timestamp=_now_iso(),
        components=components,
    )


def get_app_info() -> AppInfo:
    """返回应用信息。

    Returns:
        应用信息对象。
    """
    return AppInfo(
        name="ai-knowledge-base",
        version="0.1.0",
        python_version=platform.python_version(),
        platform=sys.platform,
    )


def should_http_503(status: str) -> bool:
    """判断健康状态是否应返回 HTTP 503。

    Args:
        status: 整体健康状态。

    Returns:
        ``True`` 表示应返回 503。
    """
    return status == "down"


__all__ = [
    "AppInfo",
    "ComponentHealth",
    "HealthResponse",
    "aggregate_status",
    "check_database",
    "check_distributors",
    "check_llm_providers",
    "get_app_info",
    "perform_health_check",
    "should_http_503",
]
