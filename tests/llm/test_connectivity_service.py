"""src.llm.connectivity_service 的单元测试。

测试覆盖：
- save_connectivity_result: upsert 联通性结果
- scan_all_providers: 批量扫描并持久化
- get_connectivity_map: 批量查询联通性状态
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.connectivity import ConnectivityResult
from src.llm.connectivity_service import (
    get_connectivity_map,
    save_connectivity_result,
    scan_all_providers,
)
from src.llm.orm import Base, LlmProviderConnectivity
from src.llm.schemas import ProviderCreate
from src.llm.service import create_provider
from src.models.enums import LlmAuthType, LlmProviderType


@pytest.fixture()
def session() -> Session:
    """创建内存 SQLite 数据库并建表。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """设置加密所需的环境变量。"""
    monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")


def _provider_create(code: str = "test") -> ProviderCreate:
    """构造测试用 ProviderCreate。"""
    return ProviderCreate(
        provider_code=code,
        display_name=f"Test {code}",
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com/v1",
        litellm_provider="openai",
        auth_type=LlmAuthType.BEARER,
        api_key="sk-test",
    )


class TestSaveConnectivityResult:
    """save_connectivity_result 测试。"""

    def test_insert_new(self, session: Session) -> None:
        """首次保存创建新行。"""
        provider = create_provider(session, _provider_create("p1"))
        result = ConnectivityResult(
            success=True,
            latency_ms=42,
            status_code=200,
            error=None,
            endpoint="https://api.example.com/v1/models",
        )
        save_connectivity_result(session, provider.id, result)

        row = session.get(LlmProviderConnectivity, 1)
        assert row is not None
        assert bool(row.is_connected) is True
        assert row.latency_ms == 42
        assert row.last_error is None
        assert row.last_check_at is not None
        assert row.last_success_at is not None

    def test_update_existing(self, session: Session) -> None:
        """二次保存更新已有行。"""
        provider = create_provider(session, _provider_create("p1"))
        ok = ConnectivityResult(
            success=True, latency_ms=42, status_code=200, error=None, endpoint="url"
        )
        save_connectivity_result(session, provider.id, ok)

        fail = ConnectivityResult(
            success=False, latency_ms=None, status_code=None,
            error="timeout", endpoint="url",
        )
        save_connectivity_result(session, provider.id, fail)

        row = session.get(LlmProviderConnectivity, 1)
        assert row is not None
        assert bool(row.is_connected) is False
        assert row.latency_ms is None
        assert row.last_error == "timeout"
        assert row.last_failure_at is not None

    def test_error_truncated(self, session: Session) -> None:
        """错误信息超过 500 字符时截断。"""
        provider = create_provider(session, _provider_create("p1"))
        long_error = "x" * 600
        result = ConnectivityResult(
            success=False, latency_ms=None, status_code=500,
            error=long_error, endpoint="url",
        )
        save_connectivity_result(session, provider.id, result)

        row = session.get(LlmProviderConnectivity, 1)
        assert row is not None
        assert len(row.last_error) == 500


class TestScanAllProviders:
    """scan_all_providers 测试。"""

    @patch("src.llm.connectivity_service.test_connectivity")
    def test_scan_multiple(self, mock_test: MagicMock, session: Session) -> None:
        """扫描多个供应商并持久化。"""
        create_provider(session, _provider_create("p1"))
        create_provider(session, _provider_create("p2"))

        mock_test.side_effect = [
            ConnectivityResult(True, 10, 200, None, "url1"),
            ConnectivityResult(False, None, None, "error", "url2"),
        ]

        results = scan_all_providers(session)
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False

        conn_map = get_connectivity_map(session, [1, 2])
        assert bool(conn_map[1].is_connected) is True
        assert bool(conn_map[2].is_connected) is False

    @patch("src.llm.connectivity_service.test_connectivity")
    def test_scan_empty(self, mock_test: MagicMock, session: Session) -> None:
        """无供应商时返回空列表。"""
        results = scan_all_providers(session)
        assert results == []
        mock_test.assert_not_called()


class TestGetConnectivityMap:
    """get_connectivity_map 测试。"""

    def test_empty_ids(self, session: Session) -> None:
        """空 ID 列表返回空 dict。"""
        assert get_connectivity_map(session, []) == {}

    def test_missing_rows(self, session: Session) -> None:
        """无联通性行的供应商不在结果中。"""
        provider = create_provider(session, _provider_create("p1"))
        result = get_connectivity_map(session, [provider.id])
        assert provider.id not in result
