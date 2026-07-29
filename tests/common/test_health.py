"""src.common.health 和 src.app 的单元测试。

测试覆盖：
- check_database: 正常/异常场景
- check_llm_providers: 各种健康状态组合
- check_distributors: 渠道配置/未配置
- aggregate_status: 状态聚合规则
- perform_health_check: 整体检查
- get_app_info: 应用信息
- should_http_503: HTTP 状态码判断
- FastAPI 端点: /health, /health/simple, /health/info
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.common.health import (
    AppInfo,
    ComponentHealth,
    aggregate_status,
    check_database,
    check_distributors,
    check_llm_providers,
    get_app_info,
    perform_health_check,
    should_http_503,
)
from src.config import database
from src.config.settings import Settings
from src.llm.orm import Base, LlmHealth, LlmModel, LlmProvider
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmProviderType,
)


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture()
def app_factory_override(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sessionmaker[Session]]:
    """提供基于 SQLite 内存数据库的 Session 工厂，用于 FastAPI 依赖注入。

    使用 ``StaticPool`` 使所有连接共享同一内存数据库，
    确保测试数据在请求级 Session 中可见。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, expire_on_commit=False
    )
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_provider(
    session: Session,
    *,
    health: LlmHealthStatus = LlmHealthStatus.HEALTHY,
    enabled: bool = True,
    deleted: bool = False,
) -> LlmProvider:
    """创建测试用供应商（含 model + health 行）。

    Args:
        session: SQLAlchemy Session。
        health: 健康状态。
        enabled: 是否启用。
        deleted: 是否软删除。

    Returns:
        LlmProvider ORM 实例。
    """
    provider = LlmProvider(
        provider_code="test",
        display_name="Test",
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        is_enabled=enabled,
        priority=100,
        is_deleted=deleted,
    )
    session.add(provider)
    session.flush()

    model = LlmModel(
        provider_id=provider.id,
        model_code="test-model",
        litellm_model="openai/test-model",
        display_name="Test Model",
        is_enabled=True,
    )
    session.add(model)
    session.flush()

    health_row = LlmHealth(
        provider_id=provider.id,
        model_id=model.id,
        health_status=health,
    )
    session.add(health_row)
    session.flush()
    return provider


def _make_settings(
    *,
    telegram: str | None = None,
    feishu: str | None = None,
) -> Settings:
    """创建测试用 Settings 对象。

    Args:
        telegram: Telegram token。
        feishu: 飞书 webhook URL。

    Returns:
        Settings 实例。
    """
    from src.config.settings import BudgetConfig, DistributorConfig, LLMConfig, MySQLConfig

    return Settings(
        mysql=MySQLConfig(
            host="localhost",
            port=3306,
            user="u",
            password="p",
            database="d",
        ),
        llm=LLMConfig(
            provider_encryption_key="test-key",
            default_provider_code="deepseek",
            api_key=None,
            api_base=None,
            model=None,
        ),
        distributor=DistributorConfig(
            telegram_bot_token=telegram,
            feishu_webhook_url=feishu,
        ),
        budget=BudgetConfig(
            daily_limit_cny=0.0,
            daily_limit_usd=0.0,
            per_call_limit_cny=0.0,
            per_call_limit_usd=0.0,
        ),
        github_token=None,
    )


# ---------------------------------------------------------------------------
# check_database
# ---------------------------------------------------------------------------


class TestCheckDatabase:
    """数据库健康检查测试。"""

    def test_database_up(self, session: Session) -> None:
        """数据库正常时状态为 up。"""
        result = check_database(session)
        assert result.status == "up"
        assert "latency_ms" in result.details

    def test_database_down(self) -> None:
        """数据库连接失败时状态为 down。"""
        mock_session = MagicMock()
        from sqlalchemy.exc import OperationalError

        mock_session.execute.side_effect = OperationalError(
            "SELECT 1", {}, Exception("connection refused")
        )
        result = check_database(mock_session)
        assert result.status == "down"
        assert "error" in result.details


# ---------------------------------------------------------------------------
# check_llm_providers
# ---------------------------------------------------------------------------


class TestCheckLlmProviders:
    """LLM 供应商健康检查测试。"""

    def test_all_healthy(self, session: Session) -> None:
        """所有供应商健康时状态为 up。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY)
        session.commit()

        result = check_llm_providers(session)
        assert result.status == "up"
        assert result.details["healthy"] == 1

    def test_has_unhealthy(self, session: Session) -> None:
        """存在 unhealthy 供应商时状态为 degraded。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY)
        _make_provider(session, health=LlmHealthStatus.UNHEALTHY)
        session.commit()

        result = check_llm_providers(session)
        assert result.status == "degraded"
        assert result.details["unhealthy"] == 1

    def test_all_unhealthy(self, session: Session) -> None:
        """所有供应商不可用时状态为 down。"""
        _make_provider(session, health=LlmHealthStatus.UNHEALTHY)
        session.commit()

        result = check_llm_providers(session)
        assert result.status == "down"

    def test_no_enabled_providers(self, session: Session) -> None:
        """无启用供应商时状态为 down。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY, enabled=False)
        session.commit()

        result = check_llm_providers(session)
        assert result.status == "down"

    def test_excludes_deleted(self, session: Session) -> None:
        """软删除供应商不参与统计。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY, deleted=True)
        session.commit()

        result = check_llm_providers(session)
        assert result.status == "down"


# ---------------------------------------------------------------------------
# check_distributors
# ---------------------------------------------------------------------------


class TestCheckDistributors:
    """分发渠道健康检查测试。"""

    def test_both_configured(self) -> None:
        """两个渠道都配置时状态为 up。"""
        settings = _make_settings(telegram="token", feishu="url")
        with patch("src.common.health.get_settings", return_value=settings):
            result = check_distributors()
        assert result.status == "up"

    def test_telegram_only(self) -> None:
        """仅配置 Telegram 时状态为 up。"""
        settings = _make_settings(telegram="token")
        with patch("src.common.health.get_settings", return_value=settings):
            result = check_distributors()
        assert result.status == "up"
        assert result.details["telegram"] == "configured"
        assert result.details["feishu"] == "not_configured"

    def test_no_channels(self) -> None:
        """无渠道配置时状态为 down。"""
        settings = _make_settings()
        with patch("src.common.health.get_settings", return_value=settings):
            result = check_distributors()
        assert result.status == "down"


# ---------------------------------------------------------------------------
# aggregate_status
# ---------------------------------------------------------------------------


class TestAggregateStatus:
    """状态聚合规则测试。"""

    def test_all_up(self) -> None:
        """所有组件 up 时整体 up。"""
        components = {
            "db": ComponentHealth(status="up"),
            "llm": ComponentHealth(status="up"),
        }
        assert aggregate_status(components) == "up"

    def test_has_degraded(self) -> None:
        """有 degraded 无 down 时整体 degraded。"""
        components = {
            "db": ComponentHealth(status="up"),
            "llm": ComponentHealth(status="degraded"),
        }
        assert aggregate_status(components) == "degraded"

    def test_has_down(self) -> None:
        """有 down 时整体 down。"""
        components = {
            "db": ComponentHealth(status="down"),
            "llm": ComponentHealth(status="up"),
        }
        assert aggregate_status(components) == "down"

    def test_down_overrides_degraded(self) -> None:
        """down 优先级高于 degraded。"""
        components = {
            "db": ComponentHealth(status="degraded"),
            "llm": ComponentHealth(status="down"),
        }
        assert aggregate_status(components) == "down"

    def test_empty_components(self) -> None:
        """空组件列表时整体 up。"""
        assert aggregate_status({}) == "up"


# ---------------------------------------------------------------------------
# perform_health_check
# ---------------------------------------------------------------------------


class TestPerformHealthCheck:
    """完整健康检查测试。"""

    def test_all_healthy(self, session: Session) -> None:
        """所有组件健康时整体 up。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY)
        session.commit()
        settings = _make_settings(telegram="token")

        with patch("src.common.health.get_settings", return_value=settings):
            result = perform_health_check(session)

        assert result.status == "up"
        assert "database" in result.components
        assert "llm_providers" in result.components
        assert "distributors" in result.components

    def test_db_down_makes_overall_down(self, session: Session) -> None:
        """数据库 down 时整体 down。"""
        _make_provider(session, health=LlmHealthStatus.HEALTHY)
        session.commit()
        settings = _make_settings(telegram="token")

        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError(
            "SELECT 1", {}, Exception("refused")
        )

        with patch("src.common.health.get_settings", return_value=settings):
            result = perform_health_check(mock_session)

        assert result.status == "down"


# ---------------------------------------------------------------------------
# get_app_info
# ---------------------------------------------------------------------------


class TestGetAppInfo:
    """应用信息测试。"""

    def test_returns_info(self) -> None:
        """返回包含必要字段的应用信息。"""
        info = get_app_info()
        assert isinstance(info, AppInfo)
        assert info.name == "ai-knowledge-base"
        assert info.version == "0.1.0"
        assert len(info.python_version) > 0
        assert len(info.platform) > 0


# ---------------------------------------------------------------------------
# should_http_503
# ---------------------------------------------------------------------------


class TestShouldHttp503:
    """HTTP 503 判断测试。"""

    def test_down_returns_true(self) -> None:
        """down 状态返回 True。"""
        assert should_http_503("down") is True

    def test_up_returns_false(self) -> None:
        """up 状态返回 False。"""
        assert should_http_503("up") is False

    def test_degraded_returns_false(self) -> None:
        """degraded 状态返回 False。"""
        assert should_http_503("degraded") is False


# ---------------------------------------------------------------------------
# FastAPI 端点测试
# ---------------------------------------------------------------------------


def _create_test_app(
    factory: sessionmaker[Session],
) -> FastAPI:
    """创建注册了健康路由的测试用 FastAPI 应用。

    Args:
        factory: Session 工厂。

    Returns:
        FastAPI 实例。
    """
    from src.app import create_app

    return create_app()


class TestHealthEndpoints:
    """FastAPI 健康检查端点测试。"""

    def test_health_simple(self, app_factory_override: sessionmaker[Session]) -> None:
        """/health/simple 始终返回 200。"""
        app = _create_test_app(app_factory_override)
        client = TestClient(app)
        resp = client.get("/health/simple")
        assert resp.status_code == 200
        assert resp.json()["status"] == "up"

    def test_health_info(self, app_factory_override: sessionmaker[Session]) -> None:
        """/health/info 返回应用信息。"""
        app = _create_test_app(app_factory_override)
        client = TestClient(app)
        resp = client.get("/health/info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "ai-knowledge-base"
        assert "version" in body

    def test_health_up(
        self,
        app_factory_override: sessionmaker[Session],
    ) -> None:
        """所有组件健康时 /health 返回 200。"""
        with app_factory_override() as session:
            _make_provider(session, health=LlmHealthStatus.HEALTHY)
            session.commit()

        settings = _make_settings(telegram="token")
        with patch("src.common.health.get_settings", return_value=settings):
            app = _create_test_app(app_factory_override)
            client = TestClient(app)
            resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "up"
        assert "components" in body

    def test_health_down_returns_503(
        self,
        app_factory_override: sessionmaker[Session],
    ) -> None:
        """无供应商且无渠道时 /health 返回 503。"""
        settings = _make_settings()
        with patch("src.common.health.get_settings", return_value=settings):
            app = _create_test_app(app_factory_override)
            client = TestClient(app)
            resp = client.get("/health")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "down"

    def test_root_redirects_to_health(
        self,
        app_factory_override: sessionmaker[Session],
    ) -> None:
        """根路径重定向到 /health。"""
        app = _create_test_app(app_factory_override)
        client = TestClient(app)
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)
