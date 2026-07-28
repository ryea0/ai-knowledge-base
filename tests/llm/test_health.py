"""src.llm.health 的单元测试。

测试覆盖：
- record_success 状态转 healthy
- record_failure 状态转 degraded / unhealthy
- record_failure 达阈值转 unhealthy
- check_model_health 健康检查成功/失败
- check_model_health 禁用时跳过
- reset_health 重置为 unknown
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.health import (
    check_model_health,
    record_failure,
    record_success,
    reset_health,
)
from src.llm.orm import Base, LlmHealth, LlmModel, LlmProvider
from src.models.enums import LlmAuthType, LlmHealthStatus, LlmProviderType


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_provider() -> LlmProvider:
    """创建测试用供应商。"""
    return LlmProvider(
        provider_code="test",
        display_name="Test",
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        is_enabled=True,
        priority=100,
    )


def _make_model(provider_id: int, code: str = "test-model") -> LlmModel:
    """创建测试用模型。"""
    return LlmModel(
        provider_id=provider_id,
        model_code=code,
        litellm_model=f"openai/{code}",
        display_name=code,
    )


def _make_health(
    provider_id: int,
    model_id: int,
    *,
    status: LlmHealthStatus = LlmHealthStatus.HEALTHY,
    failures: int = 0,
    threshold: int = 5,
    health_check_enabled: bool = True,
) -> LlmHealth:
    """创建测试用健康状态行。"""
    return LlmHealth(
        provider_id=provider_id,
        model_id=model_id,
        health_status=status,
        consecutive_failures=failures,
        failure_threshold=threshold,
        health_check_enabled=health_check_enabled,
    )


def _setup_provider_model_health(
    session: Session,
    *,
    status: LlmHealthStatus = LlmHealthStatus.HEALTHY,
    failures: int = 0,
    threshold: int = 5,
    health_check_enabled: bool = True,
) -> tuple[LlmProvider, LlmModel, LlmHealth]:
    """创建 provider + model + health 三行并 commit。"""
    p = _make_provider()
    session.add(p)
    session.flush()
    m = _make_model(p.id)
    session.add(m)
    session.flush()
    h = _make_health(
        p.id,
        m.id,
        status=status,
        failures=failures,
        threshold=threshold,
        health_check_enabled=health_check_enabled,
    )
    session.add(h)
    session.commit()
    return p, m, h


class TestRecordSuccess:
    """record_success 测试。"""

    def test_transitions_to_healthy(self, session: Session) -> None:
        """非 healthy 状态转为 healthy。"""
        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.DEGRADED, failures=3
        )

        record_success(session, p.id, m.id)

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        assert updated.consecutive_failures == 0
        assert updated.last_error is None
        assert updated.last_success_at is not None

    def test_already_healthy_updates_success_at(self, session: Session) -> None:
        """已 healthy 时仍然更新 last_success_at 和 last_latency_ms。"""
        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.HEALTHY, failures=0
        )
        old_success_at = session.get(
            LlmHealth, _get_health_id(session, m.id)
        ).last_success_at

        record_success(session, p.id, m.id, latency_ms=42)

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        assert updated.last_success_at is not None
        assert updated.last_success_at != old_success_at
        assert updated.last_latency_ms == 42
        assert updated.consecutive_failures == 0


class TestRecordFailure:
    """record_failure 测试。"""

    def test_transitions_to_degraded(self, session: Session) -> None:
        """首次失败转为 degraded。"""
        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.HEALTHY, failures=0, threshold=5
        )

        record_failure(session, p.id, m.id, "Connection error")

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.DEGRADED
        assert updated.consecutive_failures == 1
        assert updated.last_error == "Connection error"
        assert updated.last_failure_at is not None

    def test_transitions_to_unhealthy_at_threshold(
        self, session: Session
    ) -> None:
        """达阈值转为 unhealthy。"""
        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.DEGRADED, failures=4, threshold=5
        )

        record_failure(session, p.id, m.id, "Timeout")

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.UNHEALTHY
        assert updated.consecutive_failures == 5

    def test_nonexistent_model(self, session: Session) -> None:
        """不存在的模型不报错。"""
        record_failure(session, 99999, 99999, "error")

    def test_error_msg_truncated(self, session: Session) -> None:
        """错误消息截断至 500 字符。"""
        p, m, _ = _setup_provider_model_health(
            session, failures=0, threshold=100
        )

        long_msg = "x" * 600
        record_failure(session, p.id, m.id, long_msg)

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert len(updated.last_error) <= 500 if updated.last_error else True


class TestResetHealth:
    """reset_health 测试。"""

    def test_resets_to_unknown(self, session: Session) -> None:
        """重置为 unknown。"""
        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.UNHEALTHY, failures=10
        )

        reset_health(session, m.id)

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.UNKNOWN
        assert updated.consecutive_failures == 0
        assert updated.last_error is None


class TestCheckModelHealth:
    """check_model_health 测试。"""

    def test_disabled_returns_true(self, session: Session) -> None:
        """健康检查禁用时返回 True。"""
        p, m, _ = _setup_provider_model_health(
            session, health_check_enabled=False
        )

        result = check_model_health(session, p, m)
        assert result is True

    @patch("src.llm.connectivity.httpx")
    def test_success(self, mock_httpx: MagicMock, session: Session) -> None:
        """健康检查成功。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_httpx.get.return_value = mock_response
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError

        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.UNKNOWN
        )

        result = check_model_health(session, p, m)
        assert result is True

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        assert updated.last_check_at is not None

    @patch("src.llm.connectivity.httpx")
    def test_failure(self, mock_httpx: MagicMock, session: Session) -> None:
        """健康检查失败。"""
        mock_httpx.TimeoutException = httpx.TimeoutException
        mock_httpx.HTTPError = httpx.HTTPError
        mock_httpx.get.side_effect = httpx.ConnectError("Connection refused")

        p, m, _ = _setup_provider_model_health(
            session, status=LlmHealthStatus.HEALTHY
        )

        result = check_model_health(session, p, m)
        assert result is False

        updated = session.get(LlmHealth, _get_health_id(session, m.id))
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.DEGRADED
        assert updated.consecutive_failures == 1
        assert updated.last_error is not None


def _get_health_id(session: Session, model_id: int) -> int:
    """辅助：通过 model_id 查询 health 行的 id。"""
    from sqlalchemy import select

    return session.execute(
        select(LlmHealth.id).where(LlmHealth.model_id == model_id)
    ).scalar_one()
