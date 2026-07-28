"""SQLAlchemy 声明式基类与通用业务实体基类。

定义项目所有 ORM 模型共享的 :class:`Base`（声明式基类）和
:class:`BaseEntity`（通用业务实体基类）。

``BaseEntity`` 封装 docs/specs/db-conventions.md §7.1 要求的必选字段：
    - ``id``: ``BIGINT UNSIGNED AUTO_INCREMENT`` 主键
    - ``created_at``: 创建时间，插入时自动填充
    - ``updated_at``: 更新时间，插入和更新时自动填充
    - ``is_deleted``: 软删除标记，``0`` = 未删除，``1`` = 已删除
    - ``deleted_at``: 软删除时间，删除时填充

纯追加日志表（如 ``kb_llm_call_log``）不继承 ``BaseEntity``，
直接继承 :class:`Base` 并自行定义 ``id`` + ``created_at``。

命名说明：
    - Python 属性使用 ``snake_case``（如 ``created_at``），符合 PEP 8。
    - SQLAlchemy 默认将 ``snake_case`` 属性映射到同名列，无需手动指定 ``__map__``。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BigInteger 在 SQLite 上不支持 AUTOINCREMENT，用 variant 降级为 Integer
_BigInt = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。

    所有 ORM 模型须继承此类（直接或通过 ``BaseEntity``）。
    ``Base.metadata`` 收集所有表定义，用于 ``create_all()`` / ``drop_all()``。
    """

    pass


class BaseEntity(Base):
    """通用业务实体基类。

    封装 §7.1 必选字段（``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at``），业务实体继承后只需定义业务列。

    软删除约定：
        - 查询须过滤 ``WHERE is_deleted = 0``。
        - 删除用 ``UPDATE SET is_deleted=1, deleted_at=NOW(3)``，
          禁止物理删除（``DELETE FROM``）。

    时间字段说明：
        - ``created_at``: 数据库层 ``DEFAULT CURRENT_TIMESTAMP(3)`` 自动填充，
          Python 层 ``default=datetime.utcnow`` 作为 ORM flush 时的回退值。
        - ``updated_at``: 数据库层 ``ON UPDATE CURRENT_TIMESTAMP(3)`` 自动更新，
          Python 层 ``onupdate=datetime.utcnow`` 作为 ORM flush 时的回退值。

    Attributes:
        id: 自增主键，``BIGINT UNSIGNED``。
        created_at: 创建时间。
        updated_at: 更新时间（自动更新）。
        is_deleted: 软删除标记，``0`` = 否，``1`` = 是。
        deleted_at: 软删除时间，未删除为 ``None``。
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(
        _BigInt, primary_key=True, autoincrement=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


__all__ = ["Base", "BaseEntity"]
