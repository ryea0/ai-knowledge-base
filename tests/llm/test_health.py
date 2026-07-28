"""src.llm.health 的单元测试。

测试覆盖：
- record_success 状态转 healthy
- record_failure 状态转 degraded / unhealthy
- record_failure 达阈值转 unhealthy
- check_provider_health 健康检查成功/失败
- check_provider_health 禁用时跳过
- reset_health 重置为 unknown
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.health import (
    check_provider_health,
    record_failure,
    record_success,
    reset_health,
)
from src.llm.orm import Base, LlmProvider
from src.models.enums import LlmAuthType, LlmHealthStatus, LlmProviderType


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_provider(
    *,
    health: LlmHealthStatus = LlmHealthStatus.HEALTHY,
    failures: int = 0,
    threshold: int = 5,
    health_check_enabled: bool = True,
) -> LlmProvider:
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
        health_status=health,
        consecutive_failures=failures,
        failure_threshold=threshold,
        health_check_enabled=health_check_enabled,
    )


class TestRecordSuccess:
    """record_success 测试。"""

    def test_transitions_to_healthy(self, session: Session) -> None:
        """非 healthy 状态转为 healthy。"""
        p = _make_provider(
            health=LlmHealthStatus.DEGRADED,
            failures=3,
        )
        session.add(p)
        session.commit()

        record_success(session, p.id)

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        assert updated.consecutive_failures == 0
        assert updated.last_error is None
        assert updated.last_success_at is not None

    def test_already_healthy_no_change(self, session: Session) -> None:
        """已 healthy 时 CAS 不触发更新。"""
        p = _make_provider(health=LlmHealthStatus.HEALTHY, failures=0)
        session.add(p)
        session.commit()
        old_success_at = p.last_success_at

        record_success(session, p.id)

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        # last_success_at 未更新（CAS 跳过）
        assert updated.last_success_at == old_success_at


class TestRecordFailure:
    """record_failure 测试。"""

    def test_transitions_to_degraded(self, session: Session) -> None:
        """首次失败转为 degraded。"""
        p = _make_provider(
            health=LlmHealthStatus.HEALTHY,
            failures=0,
            threshold=5,
        )
        session.add(p)
        session.commit()

        record_failure(session, p.id, "Connection error")

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.DEGRADED
        assert updated.consecutive_failures == 1
        assert updated.last_error == "Connection error"
        assert updated.last_failure_at is not None

    def test_transitions_to_unhealthy_at_threshold(
        self, session: Session
    ) -> None:
        """达阈值转为 unhealthy。"""
        p = _make_provider(
            health=LlmHealthStatus.DEGRADED,
            failures=4,
            threshold=5,
        )
        session.add(p)
        session.commit()

        record_failure(session, p.id, "Timeout")

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.UNHEALTHY
        assert updated.consecutive_failures == 5

    def test_nonexistent_provider(self, session: Session) -> None:
        """不存在的供应商不报错。"""
        record_failure(session, 99999, "error")

    def test_error_msg_truncated(self, session: Session) -> None:
        """错误消息截断至 500 字符。"""
        p = _make_provider(failures=0, threshold=100)
        session.add(p)
        session.commit()

        long_msg = "x" * 600
        record_failure(session, p.id, long_msg)

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert len(updated.last_error) <= 500 if updated.last_error else True


class TestResetHealth:
    """reset_health 测试。"""

    def test_resets_to_unknown(self, session: Session) -> None:
        """重置为 unknown。"""
        p = _make_provider(
            health=LlmHealthStatus.UNHEALTHY,
            failures=10,
        )
        session.add(p)
        session.commit()

        reset_health(session, p.id)

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.UNKNOWN
        assert updated.consecutive_failures == 0
        assert updated.last_error is None


class TestCheckProviderHealth:
    """check_provider_health 测试。"""

    def test_disabled_returns_true(self, session: Session) -> None:
        """健康检查禁用时返回 True。"""
        p = _make_provider(health_check_enabled=False)
        session.add(p)
        session.commit()

        result = check_provider_health(session, p)
        assert result is True

    @patch("httpx.get")
    def test_success(self, mock_get: MagicMock, session: Session) -> None:
        """健康检查成功。"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        p = _make_provider(health=LlmHealthStatus.UNKNOWN)
        session.add(p)
        session.commit()

        result = check_provider_health(session, p)
        assert result is True

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.HEALTHY
        assert updated.last_check_at is not None

    @patch("httpx.get")
    def test_failure(self, mock_get: MagicMock, session: Session) -> None:
        """健康检查失败。"""
        mock_get.side_effect = Exception("Connection refused")

        p = _make_provider(health=LlmHealthStatus.HEALTHY)
        session.add(p)
        session.commit()

        result = check_provider_health(session, p)
        assert result is False

        updated = session.get(LlmProvider, p.id)
        assert updated is not None
        assert updated.health_status == LlmHealthStatus.DEGRADED
        assert updated.consecutive_failures == 1
        assert updated.last_error is not None
