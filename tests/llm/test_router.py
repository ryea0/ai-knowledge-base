"""src.llm.router 的单元测试。

测试覆盖：
- get_routable_chain 路由链构建与健康状态过滤
- select_first_available 首选可用
- get_all_enabled_providers 含 unhealthy
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.orm import Base, LlmHealth, LlmModel, LlmProvider
from src.llm.router import (
    get_all_enabled_providers,
    get_routable_chain,
    select_first_available,
)
from src.models.enums import LlmAuthType, LlmHealthStatus, LlmProviderType


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_provider(
    code: str,
    *,
    priority: int = 100,
    enabled: bool = True,
) -> LlmProvider:
    """创建测试用供应商。"""
    return LlmProvider(
        provider_code=code,
        display_name=code,
        provider_type=LlmProviderType.CLOUD,
        base_url="https://example.com",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        is_enabled=enabled,
        priority=priority,
    )


def _make_model(
    provider_id: int,
    code: str = "test-model",
    *,
    is_default: bool = True,
    enabled: bool = True,
) -> LlmModel:
    """创建测试用模型。"""
    return LlmModel(
        provider_id=provider_id,
        model_code=code,
        litellm_model=f"openai/{code}",
        display_name=code,
        is_enabled=enabled,
        is_default=is_default,
    )


def _make_health(
    provider_id: int,
    model_id: int,
    *,
    status: LlmHealthStatus = LlmHealthStatus.HEALTHY,
) -> LlmHealth:
    """创建测试用模型健康状态行。"""
    return LlmHealth(
        provider_id=provider_id,
        model_id=model_id,
        health_status=status,
    )


def _setup_chain(
    session: Session,
    code: str,
    *,
    priority: int = 100,
    health: LlmHealthStatus = LlmHealthStatus.HEALTHY,
    model_code: str = "test-model",
    provider_enabled: bool = True,
    model_enabled: bool = True,
    is_default: bool = True,
) -> tuple[LlmProvider, LlmModel]:
    """创建 provider + model + health 三行并 commit。"""
    p = _make_provider(code, priority=priority, enabled=provider_enabled)
    session.add(p)
    session.flush()
    m = _make_model(
        p.id, model_code, is_default=is_default, enabled=model_enabled
    )
    session.add(m)
    session.flush()
    h = _make_health(p.id, m.id, status=health)
    session.add(h)
    session.commit()
    return p, m


class TestGetRoutableChain:
    """get_routable_chain 测试。"""

    def test_empty(self, session: Session) -> None:
        """空表返回空列表。"""
        assert get_routable_chain(session) == []

    def test_chain_with_models(self, session: Session) -> None:
        """有模型的供应商组成路由链。"""
        _setup_chain(session, "p1", priority=50)
        _setup_chain(session, "p2", priority=100)

        chain = get_routable_chain(session)
        assert len(chain) == 2
        assert chain[0][0].provider_code == "p1"
        assert chain[0][1].model_code == "test-model"

    def test_skips_provider_without_model(self, session: Session) -> None:
        """无模型的供应商被跳过。"""
        p1 = _make_provider("p1")
        session.add(p1)
        session.commit()
        _setup_chain(session, "p2")

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "p2"

    def test_filters_unhealthy(self, session: Session) -> None:
        """unhealthy 模型被排除。"""
        _setup_chain(session, "healthy", health=LlmHealthStatus.HEALTHY)
        _setup_chain(
            session,
            "unhealthy",
            health=LlmHealthStatus.UNHEALTHY,
            model_code="unhealthy-model",
        )

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "healthy"

    def test_degraded_included(self, session: Session) -> None:
        """degraded 模型仍可尝试。"""
        _setup_chain(session, "degraded", health=LlmHealthStatus.DEGRADED)

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "degraded"

    def test_exclude_degraded(self, session: Session) -> None:
        """exclude_degraded=True 时排除 degraded。"""
        _setup_chain(session, "healthy", health=LlmHealthStatus.HEALTHY)
        _setup_chain(
            session,
            "degraded",
            health=LlmHealthStatus.DEGRADED,
            model_code="degraded-model",
        )

        chain = get_routable_chain(session, exclude_degraded=True)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "healthy"

    def test_filters_disabled_provider(self, session: Session) -> None:
        """disabled 供应商被排除。"""
        _setup_chain(session, "enabled", provider_enabled=True)
        _setup_chain(
            session,
            "disabled",
            provider_enabled=False,
            model_code="disabled-model",
        )

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "enabled"

    def test_filters_disabled_model(self, session: Session) -> None:
        """disabled 模型被排除。"""
        _setup_chain(session, "ok", model_enabled=True)
        _setup_chain(
            session,
            "disabled-model",
            model_enabled=False,
            model_code="dm",
        )

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "ok"

    def test_sorted_by_priority(self, session: Session) -> None:
        """按 priority 升序排列。"""
        _setup_chain(session, "p1", priority=200)
        _setup_chain(session, "p2", priority=50)
        _setup_chain(session, "p3", priority=100, model_code="m3")

        chain = get_routable_chain(session)
        assert [p.provider_code for p, _ in chain] == ["p2", "p3", "p1"]


class TestSelectFirstAvailable:
    """select_first_available 测试。"""

    def test_empty_returns_none(self, session: Session) -> None:
        """空表返回 None。"""
        assert select_first_available(session) is None

    def test_returns_first(self, session: Session) -> None:
        """返回优先级最高的可用组合。"""
        _setup_chain(session, "p1", priority=10)
        _setup_chain(session, "p2", priority=20, model_code="m2")

        result = select_first_available(session)
        assert result is not None
        provider, model = result
        assert provider.provider_code == "p1"
        assert model.model_code == "test-model"


class TestGetAllEnabledProviders:
    """get_all_enabled_providers 测试。"""

    def test_includes_unhealthy(self, session: Session) -> None:
        """含 unhealthy 供应商（此函数不检查健康状态）。"""
        _setup_chain(session, "healthy", health=LlmHealthStatus.HEALTHY)
        _setup_chain(
            session,
            "unhealthy",
            health=LlmHealthStatus.UNHEALTHY,
            model_code="uh-model",
        )

        result = get_all_enabled_providers(session)
        codes = [p.provider_code for p in result]
        assert "healthy" in codes
        assert "unhealthy" in codes

    def test_excludes_disabled(self, session: Session) -> None:
        """排除 disabled。"""
        _setup_chain(session, "enabled", provider_enabled=True)
        _setup_chain(
            session,
            "disabled",
            provider_enabled=False,
            model_code="dis-model",
        )

        result = get_all_enabled_providers(session)
        codes = [p.provider_code for p in result]
        assert "enabled" in codes
        assert "disabled" not in codes
