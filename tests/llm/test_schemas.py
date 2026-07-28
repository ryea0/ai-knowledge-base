"""src.llm.schemas 的单元测试。

测试覆盖：
- ProviderCreate / ProviderResponse 验证
- ModelCreate / ModelResponse 验证
- DiscoveredModel 验证
- HealthLogResponse 验证
- extra='forbid' 约束
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.llm.schemas import (
    DiscoveredModel,
    HealthLogResponse,
    ModelCreate,
    ModelUpdate,
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)
from src.models.enums import (
    LlmAuthType,
    LlmHealthStatus,
    LlmProviderType,
)


class TestProviderCreate:
    """ProviderCreate 测试。"""

    def test_valid_create(self) -> None:
        """合法创建。"""
        p = ProviderCreate(
            provider_code="deepseek",
            display_name="DeepSeek",
            provider_type=LlmProviderType.CLOUD,
            base_url="https://api.deepseek.com/v1",
            litellm_provider="deepseek",
            auth_type=LlmAuthType.BEARER,
            api_key="sk-test",
        )
        assert p.provider_code == "deepseek"
        assert p.is_enabled is True
        assert p.priority == 100

    def test_extra_forbidden(self) -> None:
        """禁止额外字段。"""
        with pytest.raises(ValidationError):
            ProviderCreate(
                provider_code="test",
                display_name="Test",
                base_url="https://example.com",
                litellm_provider="openai",
                extra="bad",  # type: ignore[call-arg]
            )

    def test_empty_provider_code(self) -> None:
        """provider_code 不能为空。"""
        with pytest.raises(ValidationError):
            ProviderCreate(
                provider_code="",
                display_name="Test",
                base_url="https://example.com",
                litellm_provider="openai",
            )

    def test_negative_priority(self) -> None:
        """priority 不能为负。"""
        with pytest.raises(ValidationError):
            ProviderCreate(
                provider_code="test",
                display_name="Test",
                base_url="https://example.com",
                litellm_provider="openai",
                priority=-1,
            )


class TestProviderUpdate:
    """ProviderUpdate 测试。"""

    def test_partial_update(self) -> None:
        """部分更新。"""
        u = ProviderUpdate(display_name="New Name")
        assert u.display_name == "New Name"
        assert u.base_url is None

    def test_empty_update(self) -> None:
        """空更新。"""
        u = ProviderUpdate()
        assert u.display_name is None

    def test_extra_forbidden(self) -> None:
        """禁止额外字段。"""
        with pytest.raises(ValidationError):
            ProviderUpdate(extra="bad")  # type: ignore[call-arg]


class TestProviderResponse:
    """ProviderResponse 测试。"""

    def test_from_attributes(self) -> None:
        """from_attributes=True 可从对象属性构建。"""

        class FakeProvider:
            def __init__(self) -> None:
                self.id = 1
                self.provider_code = "test"
                self.display_name = "Test"
                self.provider_type = LlmProviderType.CLOUD
                self.base_url = "https://example.com"
                self.litellm_provider = "openai"
                self.auth_type = LlmAuthType.BEARER
                self.api_key_encrypted = None
                self.auth_config = None
                self.is_enabled = True
                self.priority = 100
                self.timeout_seconds = 30
                self.max_retries = 3
                self.rpm_limit = 0
                self.health_status = LlmHealthStatus.UNKNOWN
                self.health_check_enabled = True
                self.last_check_at = None
                self.last_success_at = None
                self.last_failure_at = None
                self.consecutive_failures = 0
                self.failure_threshold = 5
                self.last_error = None
                self.is_deleted = False
                self.deleted_at = None
                self.created_at = datetime(2026, 7, 27)
                self.updated_at = datetime(2026, 7, 27)

        resp = ProviderResponse.model_validate(FakeProvider())
        assert resp.provider_code == "test"
        assert resp.health_status == LlmHealthStatus.UNKNOWN


class TestModelCreate:
    """ModelCreate 测试。"""

    def test_valid_create(self) -> None:
        """合法创建。"""
        m = ModelCreate(
            model_code="deepseek-chat",
            litellm_model="deepseek/deepseek-chat",
            display_name="DeepSeek Chat",
        )
        assert m.model_code == "deepseek-chat"
        assert m.context_window == 4096
        assert m.is_default is False

    def test_extra_forbidden(self) -> None:
        """禁止额外字段。"""
        with pytest.raises(ValidationError):
            ModelCreate(
                model_code="test",
                litellm_model="openai/test",
                display_name="Test",
                extra="bad",  # type: ignore[call-arg]
            )


class TestModelUpdate:
    """ModelUpdate 测试。"""

    def test_partial_update(self) -> None:
        """部分更新。"""
        u = ModelUpdate(display_name="New Name")
        assert u.display_name == "New Name"
        assert u.context_window is None


class TestDiscoveredModel:
    """DiscoveredModel 测试。"""

    def test_valid(self) -> None:
        """合法模型。"""
        m = DiscoveredModel(
            model_code="gpt-4o",
            litellm_model="openai/gpt-4o",
            display_name="GPT-4o",
        )
        assert m.already_exists is False
        assert m.context_window == 4096


class TestHealthLogResponse:
    """HealthLogResponse 测试。"""

    def test_from_attributes(self) -> None:
        """从对象属性构建。"""

        class FakeLog:
            def __init__(self) -> None:
                self.id = 1
                self.provider_id = 1
                self.model_id = None
                self.check_at = datetime(2026, 7, 27)
                self.latency_ms = 150
                self.is_success = True
                self.error_msg = None

        resp = HealthLogResponse.model_validate(FakeLog())
        assert resp.is_success is True
        assert resp.latency_ms == 150
