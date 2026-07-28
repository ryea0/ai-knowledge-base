"""src.llm.router 的单元测试。

测试覆盖：
- get_routable_providers 排序与健康状态过滤
- get_default_model 默认模型查询
- get_routable_chain 路由链构建
- select_first_available 首选可用
- get_all_enabled_providers 含 unhealthy
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.orm import Base, LlmModel, LlmProvider
from src.llm.router import (
    get_all_enabled_providers,
    get_default_model,
    get_routable_chain,
    get_routable_providers,
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
    health: LlmHealthStatus = LlmHealthStatus.HEALTHY,
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
        health_status=health,
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


class TestGetRoutableProviders:
    """get_routable_providers 测试。"""

    def test_empty(self, session: Session) -> None:
        """空表返回空列表。"""
        assert get_routable_providers(session) == []

    def test_filters_unhealthy(self, session: Session) -> None:
        """unhealthy 供应商被排除。"""
        p1 = _make_provider("healthy", health=LlmHealthStatus.HEALTHY)
        p2 = _make_provider("unhealthy", health=LlmHealthStatus.UNHEALTHY)
        p3 = _make_provider("degraded", health=LlmHealthStatus.DEGRADED)
        session.add_all([p1, p2, p3])
        session.commit()

        result = get_routable_providers(session)
        codes = [p.provider_code for p in result]
        assert "healthy" in codes
        assert "degraded" in codes
        assert "unhealthy" not in codes

    def test_exclude_degraded(self, session: Session) -> None:
        """exclude_degraded=True 时排除 degraded。"""
        p1 = _make_provider("healthy", health=LlmHealthStatus.HEALTHY)
        p2 = _make_provider("degraded", health=LlmHealthStatus.DEGRADED)
        session.add_all([p1, p2])
        session.commit()

        result = get_routable_providers(session, exclude_degraded=True)
        codes = [p.provider_code for p in result]
        assert "healthy" in codes
        assert "degraded" not in codes

    def test_filters_disabled(self, session: Session) -> None:
        """disabled 供应商被排除。"""
        p1 = _make_provider("enabled", enabled=True)
        p2 = _make_provider("disabled", enabled=False)
        session.add_all([p1, p2])
        session.commit()

        result = get_routable_providers(session)
        codes = [p.provider_code for p in result]
        assert "enabled" in codes
        assert "disabled" not in codes

    def test_sorted_by_priority(self, session: Session) -> None:
        """按 priority 升序排列。"""
        p1 = _make_provider("p1", priority=200)
        p2 = _make_provider("p2", priority=50)
        p3 = _make_provider("p3", priority=100)
        session.add_all([p1, p2, p3])
        session.commit()

        result = get_routable_providers(session)
        assert [p.provider_code for p in result] == ["p2", "p3", "p1"]


class TestGetDefaultModel:
    """get_default_model 测试。"""

    def test_returns_default(self, session: Session) -> None:
        """返回 is_default=True 的模型。"""
        p = _make_provider("test")
        session.add(p)
        session.commit()

        m1 = _make_model(p.id, "default", is_default=True)
        m2 = _make_model(p.id, "non-default", is_default=False)
        session.add_all([m1, m2])
        session.commit()

        result = get_default_model(session, p.id)
        assert result is not None
        assert result.model_code == "default"

    def test_no_default_returns_none(self, session: Session) -> None:
        """无默认模型返回 None。"""
        p = _make_provider("test")
        session.add(p)
        session.commit()

        m = _make_model(p.id, "test", is_default=False)
        session.add(m)
        session.commit()

        assert get_default_model(session, p.id) is None

    def test_disabled_default_skipped(self, session: Session) -> None:
        """disabled 默认模型被跳过。"""
        p = _make_provider("test")
        session.add(p)
        session.commit()

        m = _make_model(p.id, "test", is_default=True, enabled=False)
        session.add(m)
        session.commit()

        assert get_default_model(session, p.id) is None


class TestGetRoutableChain:
    """get_routable_chain 测试。"""

    def test_empty(self, session: Session) -> None:
        """空表返回空列表。"""
        assert get_routable_chain(session) == []

    def test_chain_with_models(self, session: Session) -> None:
        """有模型的供应商组成路由链。"""
        p1 = _make_provider("p1", priority=50)
        p2 = _make_provider("p2", priority=100)
        session.add_all([p1, p2])
        session.commit()

        m1 = _make_model(p1.id, "m1")
        m2 = _make_model(p2.id, "m2")
        session.add_all([m1, m2])
        session.commit()

        chain = get_routable_chain(session)
        assert len(chain) == 2
        assert chain[0][0].provider_code == "p1"
        assert chain[0][1].model_code == "m1"

    def test_skips_provider_without_model(self, session: Session) -> None:
        """无模型的供应商被跳过。"""
        p1 = _make_provider("p1")
        p2 = _make_provider("p2")
        session.add_all([p1, p2])
        session.commit()

        m2 = _make_model(p2.id, "m2")
        session.add(m2)
        session.commit()

        chain = get_routable_chain(session)
        assert len(chain) == 1
        assert chain[0][0].provider_code == "p2"


class TestSelectFirstAvailable:
    """select_first_available 测试。"""

    def test_empty_returns_none(self, session: Session) -> None:
        """空表返回 None。"""
        assert select_first_available(session) is None

    def test_returns_first(self, session: Session) -> None:
        """返回优先级最高的可用组合。"""
        p1 = _make_provider("p1", priority=10)
        p2 = _make_provider("p2", priority=20)
        session.add_all([p1, p2])
        session.commit()

        m1 = _make_model(p1.id, "m1")
        m2 = _make_model(p2.id, "m2")
        session.add_all([m1, m2])
        session.commit()

        result = select_first_available(session)
        assert result is not None
        provider, model = result
        assert provider.provider_code == "p1"
        assert model.model_code == "m1"


class TestGetAllEnabledProviders:
    """get_all_enabled_providers 测试。"""

    def test_includes_unhealthy(self, session: Session) -> None:
        """含 unhealthy 供应商。"""
        p1 = _make_provider("healthy", health=LlmHealthStatus.HEALTHY)
        p2 = _make_provider("unhealthy", health=LlmHealthStatus.UNHEALTHY)
        session.add_all([p1, p2])
        session.commit()

        result = get_all_enabled_providers(session)
        codes = [p.provider_code for p in result]
        assert "healthy" in codes
        assert "unhealthy" in codes

    def test_excludes_disabled(self, session: Session) -> None:
        """排除 disabled。"""
        p1 = _make_provider("enabled", enabled=True)
        p2 = _make_provider("disabled", enabled=False)
        session.add_all([p1, p2])
        session.commit()

        result = get_all_enabled_providers(session)
        codes = [p.provider_code for p in result]
        assert "enabled" in codes
        assert "disabled" not in codes
