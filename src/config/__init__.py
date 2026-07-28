"""配置加载模块。

负责从环境变量（``.env`` 文件）解析配置，拼装 DB 连接串，
并提供数据库引擎与会话管理。

环境变量定义见 AGENTS.md §2.4。

子模块：
    - ``settings``: 全局配置加载与 DB 连接串拼装
    - ``database``: 数据库 Engine / Session 工厂与事务上下文管理
"""

from src.config.database import (
    get_db,
    get_engine,
    get_session_factory,
    session_scope,
)
from src.config.settings import Settings, get_settings

__all__ = [
    "Settings",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_settings",
    "session_scope",
]
