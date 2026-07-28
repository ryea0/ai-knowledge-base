"""src.config.database 的单元测试。

测试覆盖：
- get_engine / get_session_factory 单例缓存
- session_scope 正常提交
- session_scope 异常回滚
- session_scope 异常后 Session 已关闭
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.config import database
from src.config.database import get_engine, get_session_factory, session_scope
from src.llm.orm import Base, LlmProvider


@pytest.fixture
def sqlite_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    """提供基于 SQLite 内存数据库的 Session 工厂。

    替换 database 模块中的 ``get_session_factory``，使 ``session_scope``
    在隔离的内存数据库上运行。每次 fixture 创建全新数据库。

    Yields:
        SQLite 内存 Session 工厂。
    """
    engine: Engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, expire_on_commit=False
    )

    monkeypatch.setattr(database, "get_session_factory", lambda: factory)

    yield factory

    Base.metadata.drop_all(engine)
    engine.dispose()


class TestGetEngine:
    """get_engine 单例测试。"""

    def test_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """多次调用返回同一 Engine 实例。"""
        get_engine.cache_clear()
        monkeypatch.setenv("MYSQL_HOST", "localhost")
        monkeypatch.setenv("MYSQL_USER", "u")
        monkeypatch.setenv("MYSQL_PASSWORD", "p")
        monkeypatch.setenv("MYSQL_DATABASE", "d")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "key")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            e1 = get_engine()
            e2 = get_engine()
            assert e1 is e2
            assert isinstance(e1, Engine)
        finally:
            get_engine.cache_clear()
            get_settings.cache_clear()

    def test_cache_clear_creates_new(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cache_clear 后创建新实例。"""
        get_engine.cache_clear()
        monkeypatch.setenv("MYSQL_HOST", "localhost")
        monkeypatch.setenv("MYSQL_USER", "u")
        monkeypatch.setenv("MYSQL_PASSWORD", "p")
        monkeypatch.setenv("MYSQL_DATABASE", "d")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "key")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            e1 = get_engine()
            get_engine.cache_clear()
            e2 = get_engine()
            assert e1 is not e2
        finally:
            get_engine.cache_clear()
            get_settings.cache_clear()


class TestGetSessionFactory:
    """get_session_factory 单例测试。"""

    def test_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """多次调用返回同一工厂实例。"""
        get_engine.cache_clear()
        get_session_factory.cache_clear()
        monkeypatch.setenv("MYSQL_HOST", "localhost")
        monkeypatch.setenv("MYSQL_USER", "u")
        monkeypatch.setenv("MYSQL_PASSWORD", "p")
        monkeypatch.setenv("MYSQL_DATABASE", "d")
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "key")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            f1 = get_session_factory()
            f2 = get_session_factory()
            assert f1 is f2
            assert isinstance(f1, sessionmaker)
        finally:
            get_engine.cache_clear()
            get_session_factory.cache_clear()
            get_settings.cache_clear()


class TestSessionScope:
    """session_scope 上下文管理器测试。"""

    def test_commit_on_success(
        self,
        sqlite_factory: sessionmaker[Session],
    ) -> None:
        """正常退出时自动 commit。"""
        with session_scope() as session:
            provider = LlmProvider(
                provider_code="test",
                display_name="Test",
                base_url="http://localhost",
                litellm_provider="openai",
            )
            session.add(provider)
            session.flush()
            assert provider.id is not None

        with session_scope() as session:
            count = session.execute(
                text("SELECT COUNT(*) FROM kb_llm_provider")
            ).scalar()
            assert count == 1

    def test_rollback_on_exception(
        self,
        sqlite_factory: sessionmaker[Session],
    ) -> None:
        """抛出异常时自动 rollback，数据不持久化。"""
        with pytest.raises(ValueError, match="故意失败"), session_scope() as session:
            provider = LlmProvider(
                provider_code="test",
                display_name="Test",
                base_url="http://localhost",
                litellm_provider="openai",
            )
            session.add(provider)
            session.flush()
            raise ValueError("故意失败")

        with session_scope() as session:
            count = session.execute(
                text("SELECT COUNT(*) FROM kb_llm_provider")
            ).scalar()
            assert count == 0

    def test_session_closed_after_success(
        self,
        sqlite_factory: sessionmaker[Session],
    ) -> None:
        """正常退出后 Session 事务已结束。"""
        session_ref: Session | None = None
        with session_scope() as session:
            session_ref = session
            session.execute(text("SELECT 1"))

        assert session_ref is not None
        assert session_ref.in_transaction() is False

    def test_session_closed_after_exception(
        self,
        sqlite_factory: sessionmaker[Session],
    ) -> None:
        """异常退出后 Session 事务已结束。"""
        session_ref: Session | None = None
        with pytest.raises(RuntimeError), session_scope() as session:
            session_ref = session
            raise RuntimeError("boom")

        assert session_ref is not None
        assert session_ref.in_transaction() is False
