"""src.api.metrics_routes 的集成测试。

通过 FastAPI TestClient 测试所有 4 个 metrics 端点。
使用最小化 FastAPI 应用避免 lifespan 副作用。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.metrics_routes import router as metrics_router
from src.common.base_entity import Base
from src.common.exception_handler import GlobalExceptionHandler
from src.config.database import get_db
from src.llm.orm import LlmCallLog, LlmModel, LlmProvider  # noqa: F401 -- register tables
from src.models.metrics import NodeMetric, PipelineRun  # noqa: F401 -- register tables


@pytest.fixture()
def test_engine():
    """创建内存 SQLite 引擎并建表。

    使用 StaticPool 确保 TestClient 线程池中的请求共享同一内存数据库。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(test_engine) -> TestClient:
    """创建 TestClient，覆盖 get_db 依赖使用同一内存引擎。"""
    app = FastAPI()
    app.include_router(metrics_router)
    GlobalExceptionHandler.register(app)

    def _override_db() -> Iterator[Session]:
        factory = sessionmaker(bind=test_engine, expire_on_commit=False)
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _seed_session(test_engine) -> Session:
    """从测试引擎获取 Session（用于插入测试数据）。"""
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    return factory()


def _create_run(
    *,
    trace_id: str = "trace001",
    status: str = "success",
    started_at: datetime | None = None,
    source_count: int = 10,
    article_count: int = 5,
    saved_count: int = 3,
    review_passed: bool = True,
    iteration: int = 1,
    total_cost_yuan: float = 0.5,
) -> PipelineRun:
    """创建 PipelineRun 实例。"""
    return PipelineRun(
        trace_id=trace_id,
        status=status,
        started_at=started_at or datetime.now(UTC).replace(tzinfo=None),
        ended_at=started_at or datetime.now(UTC).replace(tzinfo=None),
        duration_ms=1000,
        source_count=source_count,
        analysis_count=8,
        article_count=article_count,
        saved_count=saved_count,
        human_flagged=0,
        review_passed=review_passed,
        iteration=iteration,
        total_cost_yuan=total_cost_yuan,
    )


# ---------------------------------------------------------------------------
# GET /api/metrics/runs
# ---------------------------------------------------------------------------


class TestListRunsApi:
    """GET /api/metrics/runs 测试。"""

    def test_list_runs_default(self, client: TestClient, test_engine) -> None:
        """默认分页。"""
        session = _seed_session(test_engine)
        session.add(_create_run(trace_id="t1"))
        session.add(_create_run(trace_id="t2"))
        session.commit()
        session.close()

        resp = client.get("/api/metrics/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["total"] == 2
        assert len(data["data"]) == 2
        assert data["page"] == 1
        assert data["size"] == 20

    def test_list_runs_status_filter(
        self, client: TestClient, test_engine
    ) -> None:
        """状态过滤。"""
        session = _seed_session(test_engine)
        session.add(_create_run(trace_id="t1", status="success"))
        session.add(_create_run(trace_id="t2", status="error"))
        session.commit()
        session.close()

        resp = client.get("/api/metrics/runs", params={"status": "error"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["data"][0]["trace_id"] == "t2"

    def test_list_runs_empty(self, client: TestClient) -> None:
        """空结果。"""
        resp = client.get("/api/metrics/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["total"] == 0
        assert data["data"] == []

    def test_list_runs_pagination(
        self, client: TestClient, test_engine
    ) -> None:
        """分页。"""
        session = _seed_session(test_engine)
        now = datetime.now(UTC).replace(tzinfo=None)
        for i in range(25):
            session.add(
                _create_run(
                    trace_id=f"t{i:03d}",
                    started_at=now - timedelta(minutes=i),
                )
            )
        session.commit()
        session.close()

        resp = client.get("/api/metrics/runs", params={"page": 2, "size": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 25
        assert len(data["data"]) == 10
        assert data["page"] == 2


# ---------------------------------------------------------------------------
# GET /api/metrics/runs/{run_id}
# ---------------------------------------------------------------------------


class TestGetRunDetailApi:
    """GET /api/metrics/runs/{run_id} 测试。"""

    def test_get_run_detail_success(
        self, client: TestClient, test_engine
    ) -> None:
        """成功获取运行详情。"""
        session = _seed_session(test_engine)
        run = _create_run()
        session.add(run)
        session.commit()
        run_id = run.id
        session.close()

        resp = client.get(f"/api/metrics/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == run_id
        assert data["data"]["nodes"] == []

    def test_get_run_detail_not_found(self, client: TestClient) -> None:
        """不存在的运行。"""
        resp = client.get("/api/metrics/runs/9999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 10004


# ---------------------------------------------------------------------------
# GET /api/metrics/summary
# ---------------------------------------------------------------------------


class TestGetSummaryApi:
    """GET /api/metrics/summary 测试。"""

    def test_get_summary_default(self, client: TestClient) -> None:
        """默认 7 天汇总。"""
        resp = client.get("/api/metrics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["daily"]) == 7

    def test_get_summary_30_days(self, client: TestClient) -> None:
        """30 天汇总。"""
        resp = client.get("/api/metrics/summary", params={"days": 30})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]["daily"]) == 30


# ---------------------------------------------------------------------------
# GET /api/metrics/llm-cost
# ---------------------------------------------------------------------------


class TestGetLlmCostApi:
    """GET /api/metrics/llm-cost 测试。"""

    def test_get_llm_cost_empty(self, client: TestClient) -> None:
        """无数据。"""
        resp = client.get("/api/metrics/llm-cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []
        assert data["data"]["grand_total"]["total_calls"] == 0

    def test_get_llm_cost_7_days(self, client: TestClient) -> None:
        """7 天参数。"""
        resp = client.get("/api/metrics/llm-cost", params={"days": 7})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
