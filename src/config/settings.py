"""全局配置加载。

从环境变量（``.env`` 文件）读取配置项，提供 DB 连接串拼装。
环境变量定义见 docs/specs/coding-standards.md §2.4。

DB 连接串格式：``mysql+pymysql://{user}:{password}@{host}:{port}/{database}``
禁止使用单一 ``DATABASE_URL`` 混合拼接。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MySQLConfig:
    """MySQL 连接配置。

    Attributes:
        host: MySQL 主机地址。
        port: MySQL 端口。
        user: MySQL 用户名。
        password: MySQL 密码。
        database: MySQL 库名。
    """

    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def connection_url(self) -> str:
        """拼装 SQLAlchemy 连接串。

        Returns:
            ``mysql+pymysql://{user}:{password}@{host}:{port}/{database}`` 格式连接串。
        """
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass(frozen=True)
class LLMConfig:
    """LLM 配置（兼容旧单供应商模式）。

    Attributes:
        provider_encryption_key: LLM 供应商 API Key 加密主密钥。
        default_provider_code: 启动时默认供应商代码。
        api_key: 废弃，保留向后兼容。
        api_base: 废弃，保留向后兼容。
        model: 废弃，保留向后兼容。
    """

    provider_encryption_key: str
    default_provider_code: str
    api_key: str | None
    api_base: str | None
    model: str | None


@dataclass(frozen=True)
class DistributorConfig:
    """分发渠道配置。

    Attributes:
        telegram_bot_token: Telegram Bot Token，未配置为 None。
        feishu_webhook_url: 飞书 Webhook 地址，未配置为 None。
    """

    telegram_bot_token: str | None
    feishu_webhook_url: str | None

    @property
    def has_available_channel(self) -> bool:
        """是否至少有一个可用分发渠道。"""
        return self.telegram_bot_token is not None or self.feishu_webhook_url is not None


@dataclass(frozen=True)
class Settings:
    """全局配置聚合。

    Attributes:
        mysql: MySQL 连接配置。
        llm: LLM 配置。
        distributor: 分发渠道配置。
        github_token: GitHub API Token（可选）。
    """

    mysql: MySQLConfig
    llm: LLMConfig
    distributor: DistributorConfig
    github_token: str | None


def _get_env(key: str, default: str | None = None, *, required: bool = False) -> str:
    """读取环境变量。

    Args:
        key: 环境变量名。
        default: 默认值（``required=False`` 时使用）。
        required: 是否必填，为 ``True`` 且变量未设置时抛 ``ValueError``。

    Returns:
        环境变量值。

    Raises:
        ValueError: ``required=True`` 且变量未设置或为空。
    """
    value = os.environ.get(key, default)
    if required and (value is None or value == ""):
        raise ValueError(f"必填环境变量未设置: {key}")
    return value if value is not None else ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载全局配置（单例，首次调用后缓存）。

    从 ``.env`` 文件和系统环境变量读取配置，拼装为 :class:`Settings`。

    Returns:
        全局配置 :class:`Settings` 实例。

    Raises:
        ValueError: 必填环境变量未设置。
    """
    load_dotenv()

    mysql = MySQLConfig(
        host=_get_env("MYSQL_HOST", required=True),
        port=int(_get_env("MYSQL_PORT", "3306")),
        user=_get_env("MYSQL_USER", required=True),
        password=_get_env("MYSQL_PASSWORD", required=True),
        database=_get_env("MYSQL_DATABASE", required=True),
    )

    llm = LLMConfig(
        provider_encryption_key=_get_env("LLM_PROVIDER_ENCRYPTION_KEY", required=True),
        default_provider_code=_get_env("LLM_DEFAULT_PROVIDER_CODE", "deepseek"),
        api_key=_get_env("LLM_API_KEY") or None,
        api_base=_get_env("LLM_API_BASE") or None,
        model=_get_env("LLM_MODEL") or None,
    )

    distributor = DistributorConfig(
        telegram_bot_token=_get_env("TELEGRAM_BOT_TOKEN") or None,
        feishu_webhook_url=_get_env("FEISHU_WEBHOOK_URL") or None,
    )

    github_token = _get_env("GITHUB_TOKEN") or None

    settings = Settings(
        mysql=mysql,
        llm=llm,
        distributor=distributor,
        github_token=github_token,
    )

    logger.info(
        "配置加载完成: mysql=%s:%s/%s, default_provider=%s, channels=%s",
        mysql.host,
        mysql.port,
        mysql.database,
        llm.default_provider_code,
        "telegram" if distributor.telegram_bot_token else ""
        + "/"
        + "feishu" if distributor.feishu_webhook_url else "",
    )

    return settings
