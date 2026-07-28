"""数据库引擎与会话管理。

提供全局 Engine 单例、Session 工厂、事务上下文管理器和 FastAPI 依赖注入，
统一管理 MySQL 连接池与事务生命周期。

连接配置从 :func:`src.config.settings.get_settings` 读取，
连接串格式见 AGENTS.md §2.4（``mysql+pymysql://...``）。

连接池策略：
    - ``pool_size=5``: 常驻连接数
    - ``max_overflow=10``: 突发可额外借出的连接数
    - ``pool_pre_ping=True``: 借出前检测存活（防 MySQL ``wait_timeout`` 断连）
    - ``pool_recycle=3600``: 连接最大存活 1 小时（须 < MySQL ``wait_timeout``）

事务约定：
    服务层（``src.llm.service`` / ``src.llm.health`` 等）**不调用**
    ``session.commit()``，仅 ``flush()``。事务提交/回滚由调用方控制：

    - CLI / 工作流：使用 :func:`session_scope` 上下文管理器
    - FastAPI 端点：使用 :func:`get_db` 依赖注入

使用方式::

    # CLI / 工作流
    from src.config.database import session_scope

    with session_scope() as session:
        article = session.get(Article, 1)
        article.status = ArticleStatus.PUBLISHED
        # 退出 with 块自动 commit；异常自动 rollback

    # FastAPI
    from src.config.database import get_db

    @app.get("/articles/{aid}")
    def get_article(aid: int, db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

_POOL_SIZE = 5
_MAX_OVERFLOW = 10
_POOL_RECYCLE_SECONDS = 3600


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """创建全局 Engine 单例（带连接池）。

    从 :func:`get_settings` 读取 MySQL 配置，构造带连接池的 Engine。
    首次调用后缓存，后续调用返回同一实例。

    Returns:
        全局唯一的 :class:`Engine` 实例。
    """
    settings = get_settings()
    url = settings.mysql.connection_url
    engine = create_engine(
        url,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=_POOL_RECYCLE_SECONDS,
        echo=False,
    )
    logger.info(
        "数据库引擎已创建: %s:%s/%s, pool_size=%s",
        settings.mysql.host,
        settings.mysql.port,
        settings.mysql.database,
        _POOL_SIZE,
    )
    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """创建全局 Session 工厂单例。

    基于 :func:`get_engine` 的 Engine 构造 ``sessionmaker``，
    调用返回的工厂对象即可创建独立 Session。

    Returns:
        全局唯一的 :class:`sessionmaker` 工厂实例。

    Usage::

        SessionLocal = get_session_factory()
        session = SessionLocal()
        ...
        session.close()
    """
    engine = get_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    logger.info("Session 工厂已创建")
    return factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文管理器。

    自动管理 Session 生命周期与事务：正常退出时 ``commit``，
    抛出异常时 ``rollback``，无论成功失败最终 ``close`` 归还连接。

    Yields:
        :class:`Session` 实例。

    Raises:
        重新抛出块内产生的任何异常（rollback 后原样 raise）。

    Usage::

        with session_scope() as session:
            session.add(article)
            session.flush()
            article_id = article.id
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入：提供请求级 Session 并管理事务。

    每个请求获取独立 Session，请求成功时 ``commit``，抛出异常时 ``rollback``，
    无论成功失败最终 ``close`` 归还连接到连接池。

    与 :func:`session_scope` 的区别：本函数为生成器，配合 FastAPI 的
    ``Depends`` 使用；``session_scope`` 为上下文管理器，配合 ``with`` 使用。

    Yields:
        :class:`Session` 实例。

    Usage::

        from fastapi import Depends
        from src.config.database import get_db

        @app.post("/providers")
        def create_provider(
            data: ProviderCreate,
            db: Session = Depends(get_db),
        ):
            return service.create_provider(db, data)
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "get_db",
    "get_engine",
    "get_session_factory",
    "session_scope",
]
