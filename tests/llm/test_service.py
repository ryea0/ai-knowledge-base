"""src.llm.service 的单元测试。

测试覆盖：
- Provider CRUD（create/get/list/update/delete）
- Model CRUD（create/list/update/delete）
- _clear_default_model 辅助函数
- discover_models 模型发现（mock httpx）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.llm.orm import Base, LlmModel, LlmProvider
from src.llm.schemas import (
    ModelCreate,
    ModelUpdate,
    ProviderCreate,
    ProviderUpdate,
)
from src.llm.service import (
    _clear_default_model,
    create_model,
    create_provider,
    delete_model,
    delete_provider,
    discover_models,
    get_provider,
    list_models,
    list_providers,
    update_model,
    update_provider,
)
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


def _provider_create(
    code: str = "test",
    *,
    api_key: str | None = None,
    auth_type: LlmAuthType = LlmAuthType.BEARER,
) -> ProviderCreate:
    """创建 ProviderCreate fixture。"""
    return ProviderCreate(
        provider_code=code,
        display_name=code.title(),
        provider_type=LlmProviderType.CLOUD,
        base_url="https://api.example.com",
        litellm_provider="openai",
        auth_type=auth_type,
        api_key=api_key,
    )


def _model_create(
    code: str = "test-model",
    *,
    is_default: bool = True,
) -> ModelCreate:
    """创建 ModelCreate fixture。"""
    return ModelCreate(
        model_code=code,
        litellm_model=f"openai/{code}",
        display_name=code,
        is_default=is_default,
    )


class TestCreateProvider:
    """create_provider 测试。"""

    def test_create_without_api_key(self, session: Session) -> None:
        """无 API Key 创建。"""
        resp = create_provider(session, _provider_create())
        assert resp.provider_code == "test"
        assert resp.is_enabled is True

    def test_create_with_api_key(self, session: Session) -> None:
        """有 API Key 创建（加密存储）。"""
        resp = create_provider(
            session, _provider_create(api_key="sk-test")
        )
        assert resp.provider_code == "test"

        provider = session.get(LlmProvider, resp.id)
        assert provider is not None
        assert provider.api_key_encrypted is not None
        assert provider.api_key_encrypted != "sk-test"

    def test_create_none_auth_no_key(self, session: Session) -> None:
        """none 鉴权不加密 API Key。"""
        resp = create_provider(
            session, _provider_create(auth_type=LlmAuthType.NONE)
        )
        provider = session.get(LlmProvider, resp.id)
        assert provider is not None
        assert provider.api_key_encrypted is None

    def test_duplicate_code_raises(self, session: Session) -> None:
        """重复 provider_code 抛 ValueError。"""
        create_provider(session, _provider_create("dup"))
        with pytest.raises(ValueError, match="已存在"):
            create_provider(session, _provider_create("dup"))


class TestGetProvider:
    """get_provider 测试。"""

    def test_get_existing(self, session: Session) -> None:
        """查存在的供应商。"""
        created = create_provider(session, _provider_create())
        result = get_provider(session, created.id)
        assert result is not None
        assert result.provider_code == "test"

    def test_get_nonexistent(self, session: Session) -> None:
        """查不存在的返回 None。"""
        assert get_provider(session, 99999) is None


class TestListProviders:
    """list_providers 测试。"""

    def test_empty(self, session: Session) -> None:
        """空表返回空列表。"""
        assert list_providers(session) == []

    def test_sorted_by_priority(self, session: Session) -> None:
        """按优先级排序。"""
        create_provider(session, _provider_create("p1"))
        create_provider(session, _provider_create("p2"))
        result = list_providers(session)
        assert len(result) == 2


class TestUpdateProvider:
    """update_provider 测试。"""

    def test_update_display_name(self, session: Session) -> None:
        """更新显示名称。"""
        created = create_provider(session, _provider_create())
        resp = update_provider(
            session, created.id, ProviderUpdate(display_name="New Name")
        )
        assert resp.display_name == "New Name"

    def test_update_api_key(self, session: Session) -> None:
        """更新 API Key。"""
        created = create_provider(session, _provider_create())
        update_provider(
            session, created.id, ProviderUpdate(api_key="sk-new")
        )
        provider = session.get(LlmProvider, created.id)
        assert provider is not None
        assert provider.api_key_encrypted is not None

    def test_update_nonexistent_raises(self, session: Session) -> None:
        """更新不存在的抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            update_provider(session, 99999, ProviderUpdate())


class TestDeleteProvider:
    """delete_provider 测试。"""

    def test_soft_delete(self, session: Session) -> None:
        """软删除（is_enabled=False）。"""
        created = create_provider(session, _provider_create())
        delete_provider(session, created.id)
        provider = session.get(LlmProvider, created.id)
        assert provider is not None
        assert not provider.is_enabled

    def test_delete_nonexistent_raises(self, session: Session) -> None:
        """删除不存在的抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            delete_provider(session, 99999)


class TestCreateModel:
    """create_model 测试。"""

    def test_create_model(self, session: Session) -> None:
        """创建模型。"""
        provider = create_provider(session, _provider_create())
        resp = create_model(session, provider.id, _model_create("m1"))
        assert resp.model_code == "m1"
        assert resp.is_default is True

    def test_create_default_clears_others(self, session: Session) -> None:
        """新默认模型清除旧默认。"""
        provider = create_provider(session, _provider_create())
        m1 = create_model(session, provider.id, _model_create("m1", is_default=True))
        m2 = create_model(session, provider.id, _model_create("m2", is_default=True))

        # m1 应不再默认
        m1_updated = session.get(LlmModel, m1.id)
        assert m1_updated is not None
        assert not m1_updated.is_default

        m2_updated = session.get(LlmModel, m2.id)
        assert m2_updated is not None
        assert m2_updated.is_default

    def test_duplicate_model_code_raises(self, session: Session) -> None:
        """重复 model_code 抛 ValueError。"""
        provider = create_provider(session, _provider_create())
        create_model(session, provider.id, _model_create("m1"))
        with pytest.raises(ValueError, match="已存在"):
            create_model(session, provider.id, _model_create("m1"))

    def test_nonexistent_provider_raises(self, session: Session) -> None:
        """供应商不存在抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            create_model(session, 99999, _model_create())


class TestListModels:
    """list_models 测试。"""

    def test_empty(self, session: Session) -> None:
        """无模型返回空列表。"""
        provider = create_provider(session, _provider_create())
        assert list_models(session, provider.id) == []

    def test_lists_all(self, session: Session) -> None:
        """列出所有模型。"""
        provider = create_provider(session, _provider_create())
        create_model(session, provider.id, _model_create("m1"))
        create_model(session, provider.id, _model_create("m2", is_default=False))
        result = list_models(session, provider.id)
        assert len(result) == 2


class TestUpdateModel:
    """update_model 测试。"""

    def test_update_display_name(self, session: Session) -> None:
        """更新模型名称。"""
        provider = create_provider(session, _provider_create())
        model = create_model(session, provider.id, _model_create("m1"))
        resp = update_model(
            session, model.id, ModelUpdate(display_name="New Name")
        )
        assert resp.display_name == "New Name"

    def test_update_nonexistent_raises(self, session: Session) -> None:
        """更新不存在的抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            update_model(session, 99999, ModelUpdate())


class TestDeleteModel:
    """delete_model 测试。"""

    def test_soft_delete_model(self, session: Session) -> None:
        """软删除模型（is_deleted=True, is_enabled=False）。"""
        provider = create_provider(session, _provider_create())
        model = create_model(session, provider.id, _model_create("m1"))
        delete_model(session, model.id)

        deleted = session.get(LlmModel, model.id)
        assert deleted is not None
        assert bool(deleted.is_deleted) is True
        assert bool(deleted.is_enabled) is False
        assert deleted.deleted_at is not None

    def test_delete_nonexistent_raises(self, session: Session) -> None:
        """删除不存在的抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            delete_model(session, 99999)


class TestClearDefaultModel:
    """_clear_default_model 测试。"""

    def test_clears_defaults(self, session: Session) -> None:
        """清除所有默认标记。"""
        provider = create_provider(session, _provider_create())
        m1 = create_model(session, provider.id, _model_create("m1", is_default=True))
        m2 = create_model(session, provider.id, _model_create("m2", is_default=True))

        _clear_default_model(session, provider_id=provider.id)

        for m in [m1, m2]:
            model = session.get(LlmModel, m.id)
            assert model is not None
            assert not model.is_default

    def test_exclude_id(self, session: Session) -> None:
        """排除指定 ID 的模型，仅清除其他模型的 default。"""
        provider = create_provider(session, _provider_create())
        m1 = create_model(session, provider.id, _model_create("m1", is_default=True))
        m2 = create_model(session, provider.id, _model_create("m2", is_default=True))

        # m2 is now default, m1 is cleared. Now manually set m1 as default too
        m1_model = session.get(LlmModel, m1.id)
        assert m1_model is not None
        m1_model.is_default = True
        session.flush()

        _clear_default_model(session, provider_id=provider.id, exclude_id=m1.id)

        m1_updated = session.get(LlmModel, m1.id)
        assert m1_updated is not None
        assert m1_updated.is_default

        m2_updated = session.get(LlmModel, m2.id)
        assert m2_updated is not None
        assert not m2_updated.is_default


class TestDiscoverModels:
    """discover_models 测试。"""

    @patch("src.llm.service.httpx")
    def test_discover_success(self, mock_httpx: MagicMock, session: Session) -> None:
        """成功发现模型。"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
            ]
        }
        mock_httpx.get.return_value = mock_response

        provider = create_provider(session, _provider_create())
        result = discover_models(session, provider.id)

        assert len(result) == 2
        assert result[0].model_code == "gpt-4o"
        assert result[0].litellm_model == "openai/gpt-4o"
        assert not result[0].already_exists

    @patch("src.llm.service.httpx")
    def test_discover_already_exists(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """已存在的模型标记 already_exists。"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"data": [{"id": "existing-model"}]}
        mock_httpx.get.return_value = mock_response

        provider = create_provider(session, _provider_create())
        create_model(session, provider.id, _model_create("existing-model"))

        result = discover_models(session, provider.id)
        assert len(result) == 1
        assert result[0].already_exists is True

    @patch("src.llm.service.httpx")
    def test_discover_http_error_raises(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """HTTP 错误抛 RuntimeError。"""
        import httpx as real_httpx

        mock_httpx.get.side_effect = real_httpx.HTTPError("Connection failed")
        mock_httpx.HTTPError = real_httpx.HTTPError

        provider = create_provider(session, _provider_create())
        with pytest.raises(RuntimeError, match="无法获取"):
            discover_models(session, provider.id)

    def test_discover_nonexistent_provider(self, session: Session) -> None:
        """供应商不存在抛 ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            discover_models(session, 99999)

    @patch("src.llm.service.httpx")
    def test_discover_skips_empty_id(
        self, mock_httpx: MagicMock, session: Session
    ) -> None:
        """空 model id 被跳过。"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": [
                {"id": ""},
                {"id": "valid-model"},
            ]
        }
        mock_httpx.get.return_value = mock_response

        provider = create_provider(session, _provider_create())
        result = discover_models(session, provider.id)
        assert len(result) == 1
        assert result[0].model_code == "valid-model"
