"""src.utils.page_helper 的单元测试。

测试覆盖：
- IPage.pages 总页数计算（含边界）
- PageHelper.toPage 参数校验与边界
- PageHelper.toPage 分页查询正确性（SQLite 集成）
- PageHelper.toPageResult 转换正确性
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.common.base_entity import Base
from src.common.response import PageResult
from src.llm.orm import LlmProvider
from src.utils.page_helper import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    IPage,
    PageHelper,
)


@pytest.fixture
def engine() -> Engine:
    """SQLite 内存数据库 Engine，建表并插入测试数据。"""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    factory: sessionmaker[Session] = sessionmaker(bind=eng)
    with factory() as session:
        for i in range(1, 26):
                session.add(
                    LlmProvider(
                        provider_code=f"test-provider-{i:02d}",
                        display_name=f"测试供应商{i:02d}",
                        provider_type=0,
                        auth_type=0,
                        litellm_provider="openai",
                        base_url="https://api.example.com/v1",
                        api_key_encrypted="enc:fake",
                        priority=i,
                        is_enabled=True,
                    )
                )
        session.commit()
    return eng


@pytest.fixture
def session(engine: Engine) -> Session:
    """SQLite Session fixture。"""
    factory: sessionmaker[Session] = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()


class TestIPage:
    """IPage 数据容器测试。"""

    def test_pages_calculation_normal(self) -> None:
        """正常向上取整。"""
        page = IPage(records=[], total=25, page=1, size=10)
        assert page.pages == 3

    def test_pages_calculation_exact(self) -> None:
        """整除无余页。"""
        page = IPage(records=[], total=20, page=1, size=10)
        assert page.pages == 2

    def test_pages_calculation_zero_total(self) -> None:
        """总数为 0 时页数为 0。"""
        page = IPage(records=[], total=0, page=1, size=10)
        assert page.pages == 0

    def test_default_values(self) -> None:
        """默认值正确。"""
        page = IPage()
        assert page.records == []
        assert page.total == 0
        assert page.page == 1
        assert page.size == DEFAULT_PAGE_SIZE


class TestToPage:
    """PageHelper.toPage 测试。"""

    def test_first_page(self, session: Session) -> None:
        """第一页返回正确数量和分页信息。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=1, pageSize=10)
        assert isinstance(page, IPage)
        assert len(page.records) == 10
        assert page.total == 25
        assert page.page == 1
        assert page.size == 10
        assert page.pages == 3

    def test_last_page_partial(self, session: Session) -> None:
        """最后一页不足 pageSize。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=3, pageSize=10)
        assert len(page.records) == 5
        assert page.total == 25

    def test_beyond_last_page(self, session: Session) -> None:
        """超出总页数返回空列表。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=10, pageSize=10)
        assert len(page.records) == 0
        assert page.total == 25

    def test_default_page_size(self, session: Session) -> None:
        """未传 pageSize 使用默认值 20。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=1)
        assert page.size == DEFAULT_PAGE_SIZE
        assert len(page.records) == DEFAULT_PAGE_SIZE
        assert page.total == 25

    def test_max_page_size_cap(self, session: Session) -> None:
        """pageSize 超过 100 被截断为 100。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=1, pageSize=200)
        assert page.size == MAX_PAGE_SIZE

    def test_invalid_page_zero(self, session: Session) -> None:
        """page=0 抛 ValueError。"""
        stmt = select(LlmProvider)
        with pytest.raises(ValueError, match="page"):
            PageHelper.toPage(session, stmt, page=0)

    def test_invalid_page_negative(self, session: Session) -> None:
        """page 为负数抛 ValueError。"""
        stmt = select(LlmProvider)
        with pytest.raises(ValueError, match="page"):
            PageHelper.toPage(session, stmt, page=-1)

    def test_invalid_page_size_zero(self, session: Session) -> None:
        """pageSize=0 抛 ValueError。"""
        stmt = select(LlmProvider)
        with pytest.raises(ValueError, match="pageSize"):
            PageHelper.toPage(session, stmt, page=1, pageSize=0)

    def test_invalid_page_type(self, session: Session) -> None:
        """page 非整数抛 ValueError。"""
        stmt = select(LlmProvider)
        with pytest.raises(ValueError, match="page"):
            PageHelper.toPage(session, stmt, page=1.5)  # type: ignore[arg-type]

    def test_bool_page_rejected(self, session: Session) -> None:
        """page 为 bool 抛 ValueError（bool 是 int 子类但须排除）。"""
        stmt = select(LlmProvider)
        with pytest.raises(ValueError, match="page"):
            PageHelper.toPage(session, stmt, page=True)  # type: ignore[arg-type]

    def test_with_where_clause(self, session: Session) -> None:
        """带 WHERE 条件的分页查询。"""
        stmt = (
            select(LlmProvider)
            .where(LlmProvider.priority <= 5)
            .order_by(LlmProvider.id)
        )
        page = PageHelper.toPage(session, stmt, page=1, pageSize=10)
        assert len(page.records) == 5
        assert page.total == 5

    def test_records_are_orm_instances(self, session: Session) -> None:
        """返回的 records 是 ORM 实例。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        page = PageHelper.toPage(session, stmt, page=1, pageSize=3)
        assert all(isinstance(r, LlmProvider) for r in page.records)
        assert page.records[0].provider_code == "test-provider-01"


class TestToPageResult:
    """PageHelper.toPageResult 测试。"""

    def test_converts_to_page_result(self) -> None:
        """IPage 正确转为 PageResult。"""
        ipage: IPage[Any] = IPage(
            records=["a", "b", "c"],
            total=25,
            page=3,
            size=10,
        )
        result = PageHelper.toPageResult(ipage)
        assert isinstance(result, PageResult)
        assert result.code == 0
        assert result.data == ["a", "b", "c"]
        assert result.total == 25
        assert result.page == 3
        assert result.size == 10

    def test_empty_page(self) -> None:
        """空页转为 PageResult。"""
        ipage: IPage[Any] = IPage(records=[], total=0, page=1, size=10)
        result = PageHelper.toPageResult(ipage)
        assert result.data == []
        assert result.total == 0
        assert result.page == 1

    def test_end_to_end(self, session: Session) -> None:
        """端到端：toPage -> toPageResult。"""
        stmt = select(LlmProvider).order_by(LlmProvider.id)
        ipage = PageHelper.toPage(session, stmt, page=2, pageSize=10)
        result = PageHelper.toPageResult(ipage)
        assert result.code == 0
        assert len(result.data) == 10  # type: ignore[arg-type]
        assert result.total == 25
        assert result.page == 2
        assert result.size == 10
