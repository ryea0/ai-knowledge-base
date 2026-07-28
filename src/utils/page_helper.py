"""分页查询工具。

提供 ``IPage`` 分页数据容器和 ``PageHelper`` 静态工具类，
封装 SQLAlchemy 分页查询的 offset/limit 计算与结果组装，
使 Service 层无需手写分页样板代码。

设计思路：
    - ``toPage``: 将前端 page/pageSize 参数应用到一个 SQLAlchemy ``Select`` 语句，
      执行查询并连同 total 组装为 ``IPage`` 对象。
    - ``toPageResult``: 将 ``IPage`` 转为 API 响应 ``PageResult``。

Usage::

    from src.utils.page_helper import PageHelper

    stmt = select(Article).where(Article.is_deleted == 0).order_by(Article.id)
    page = PageHelper.toPage(session, stmt, page=1, pageSize=20)
    return PageHelper.toPageResult(page)          # -> PageResult[...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.common.response import PageResult

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass
class IPage[T]:
    """分页查询结果容器（中间层）。

    由 ``PageHelper.toPage`` 产出，携带当前页数据和分页元信息，
    可经 ``PageHelper.toPageResult`` 转为 API 响应。

    Attributes:
        records: 当前页数据列表。
        total: 总条数。
        page: 当前页码（从 1 开始）。
        size: 每页条数。
        pages: 总页数。
    """

    records: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE

    @property
    def pages(self) -> int:
        """总页数（向上取整）。"""
        if self.size <= 0:
            return 0
        return (self.total + self.size - 1) // self.size


class PageHelper:
    """分页查询静态工具类。

    所有方法为 ``@staticmethod``，无需实例化。
    """

    @staticmethod
    def toPage(
        session: Session,
        stmt: Select[Any],
        page: int = 1,
        pageSize: int = DEFAULT_PAGE_SIZE,
    ) -> IPage[Any]:
        """执行分页查询，返回 ``IPage`` 结果容器。

        将前端传入的 page/pageSize 应用到 SQLAlchemy ``Select`` 语句，
        自动计算 offset/limit，并执行 count 查询获取总数。

        Args:
            session: SQLAlchemy Session。
            stmt: 已构建好的 ``Select`` 语句（含 where/order_by，不含 offset/limit）。
            page: 页码，从 1 开始，默认 1。
            pageSize: 每页条数，默认 20，最大 100。

        Returns:
            包含当前页数据和分页元信息的 ``IPage`` 对象。

        Raises:
            ValueError: page 或 pageSize 非正整数。
        """
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError(f"page 必须为正整数，实际: {page}")
        if (
            not isinstance(pageSize, int)
            or isinstance(pageSize, bool)
            or pageSize < 1
        ):
            raise ValueError(f"pageSize 必须为正整数，实际: {pageSize}")

        if pageSize > MAX_PAGE_SIZE:
            pageSize = MAX_PAGE_SIZE

        count_stmt = select(func.count()).select_from(
            stmt.order_by(None).limit(None).offset(None).subquery()
        )
        total = session.execute(count_stmt).scalar_one()

        offset = (page - 1) * pageSize
        rows = session.execute(stmt.offset(offset).limit(pageSize)).scalars().all()

        return IPage(
            records=list(rows),
            total=total,
            page=page,
            size=pageSize,
        )

    @staticmethod
    def toPageResult(ipage: IPage[T]) -> PageResult[T]:
        """将 ``IPage`` 转为 API 分页响应 ``PageResult``。

        Args:
            ipage: 分页查询结果容器。

        Returns:
            ``code=0`` 的 ``PageResult`` 实例，data 为当前页记录列表。
        """
        return PageResult[T].ok(
            data=ipage.records,  # type: ignore[arg-type]
            total=ipage.total,
            page=ipage.page,
            size=ipage.size,
        )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "IPage",
    "MAX_PAGE_SIZE",
    "PageHelper",
]
