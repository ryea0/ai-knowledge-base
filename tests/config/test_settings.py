"""src.config.settings 的单元测试。

测试覆盖：
- MySQLConfig 连接串拼装
- DistributorConfig 渠道可用性判断
- get_settings 环境变量加载（通过 monkeypatch）
"""

from __future__ import annotations

import pytest

from src.config.settings import (
    DistributorConfig,
    MySQLConfig,
    Settings,
    get_settings,
)


class TestMySQLConfig:
    """MySQLConfig 连接串拼装测试。"""

    def test_connection_url_format(self) -> None:
        """连接串格式正确。"""
        cfg = MySQLConfig(
            host="127.0.0.1",
            port=3306,
            user="kb_app",
            password="secret",
            database="ai_knowledge_base",
        )
        assert (
            cfg.connection_url
            == "mysql+pymysql://kb_app:secret@127.0.0.1:3306/ai_knowledge_base"
        )

    def test_connection_url_custom_port(self) -> None:
        """自定义端口拼装正确。"""
        cfg = MySQLConfig(
            host="db.example.com",
            port=13306,
            user="root",
            password="pass",
            database="testdb",
        )
        assert "db.example.com:13306/testdb" in cfg.connection_url

    def test_frozen_dataclass(self) -> None:
        """MySQLConfig 不可变。"""
        cfg = MySQLConfig(
            host="h", port=3306, user="u", password="p", database="d"
        )
        with pytest.raises(AttributeError):
            cfg.host = "changed"  # type: ignore[misc]


class TestDistributorConfig:
    """DistributorConfig 渠道可用性测试。"""

    def test_has_no_channel(self) -> None:
        """无渠道时 has_available_channel 为 False。"""
        cfg = DistributorConfig(
            telegram_bot_token=None,
            feishu_webhook_url=None,
        )
        assert not cfg.has_available_channel

    def test_has_telegram_only(self) -> None:
        """仅 Telegram 时 has_available_channel 为 True。"""
        cfg = DistributorConfig(
            telegram_bot_token="token123",
            feishu_webhook_url=None,
        )
        assert cfg.has_available_channel

    def test_has_feishu_only(self) -> None:
        """仅飞书时 has_available_channel 为 True。"""
        cfg = DistributorConfig(
            telegram_bot_token=None,
            feishu_webhook_url="https://example.com/hook",
        )
        assert cfg.has_available_channel

    def test_has_both_channels(self) -> None:
        """两个渠道都有时 has_available_channel 为 True。"""
        cfg = DistributorConfig(
            telegram_bot_token="token",
            feishu_webhook_url="https://example.com/hook",
        )
        assert cfg.has_available_channel


class TestGetSettings:
    """get_settings 环境变量加载测试。"""

    def test_get_settings_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """正常环境变量加载成功。"""
        get_settings.cache_clear()

        monkeypatch.setenv("MYSQL_HOST", "testhost")
        monkeypatch.setenv("MYSQL_PORT", "3307")
        monkeypatch.setenv("MYSQL_USER", "testuser")
        monkeypatch.setenv("MYSQL_PASSWORD", "testpass")
        monkeypatch.setenv("MYSQL_DATABASE", "testdb")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-key")
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER_CODE", "deepseek")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token")
        monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")

        settings = get_settings()

        assert isinstance(settings, Settings)
        assert settings.mysql.host == "testhost"
        assert settings.mysql.port == 3307
        assert settings.mysql.user == "testuser"
        assert settings.mysql.database == "testdb"
        assert settings.mysql.connection_url == (
            "mysql+pymysql://testuser:testpass@testhost:3307/testdb"
        )
        assert settings.llm.default_provider_code == "deepseek"
        assert settings.distributor.telegram_bot_token == "tg-token"
        assert settings.distributor.feishu_webhook_url is None
        assert settings.distributor.has_available_channel
        assert settings.github_token == "gh-token"

        get_settings.cache_clear()

    def test_get_settings_missing_required(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """必填环境变量缺失时抛 ValueError。"""
        get_settings.cache_clear()

        for key in [
            "MYSQL_HOST",
            "MYSQL_USER",
            "MYSQL_PASSWORD",
            "MYSQL_DATABASE",
            "LLM_PROVIDER_ENCRYPTION_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        monkeypatch.setattr("src.config.settings.load_dotenv", lambda: None)

        with pytest.raises(ValueError, match="必填环境变量未设置"):
            get_settings()

        get_settings.cache_clear()

    def test_get_settings_default_port(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MYSQL_PORT 未设置时使用默认值 3306。"""
        get_settings.cache_clear()

        monkeypatch.setenv("MYSQL_HOST", "h")
        monkeypatch.setenv("MYSQL_PORT", "")
        monkeypatch.delenv("MYSQL_PORT", raising=False)
        monkeypatch.setenv("MYSQL_USER", "u")
        monkeypatch.setenv("MYSQL_PASSWORD", "p")
        monkeypatch.setenv("MYSQL_DATABASE", "d")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "key")

        settings = get_settings()
        assert settings.mysql.port == 3306

        get_settings.cache_clear()

    def test_get_settings_cached(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """get_settings 使用 lru_cache，多次调用返回同一实例。"""
        get_settings.cache_clear()

        for key, val in {
            "MYSQL_HOST": "h",
            "MYSQL_USER": "u",
            "MYSQL_PASSWORD": "p",
            "MYSQL_DATABASE": "d",
            "LLM_PROVIDER_ENCRYPTION_KEY": "key",
        }.items():
            monkeypatch.setenv(key, val)

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

        get_settings.cache_clear()

    def test_llm_config_deprecated_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """废弃的 LLM_API_KEY 等字段仍可读取。"""
        get_settings.cache_clear()

        monkeypatch.setenv("MYSQL_HOST", "h")
        monkeypatch.setenv("MYSQL_USER", "u")
        monkeypatch.setenv("MYSQL_PASSWORD", "p")
        monkeypatch.setenv("MYSQL_DATABASE", "d")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "key")
        monkeypatch.setenv("LLM_API_KEY", "old-key")
        monkeypatch.setenv("LLM_API_BASE", "https://old.api/v1")
        monkeypatch.setenv("LLM_MODEL", "old-model")

        settings = get_settings()
        assert settings.llm.api_key == "old-key"
        assert settings.llm.api_base == "https://old.api/v1"
        assert settings.llm.model == "old-model"

        get_settings.cache_clear()
