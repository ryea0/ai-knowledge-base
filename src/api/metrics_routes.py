"""Metrics 指标监控 REST API 路由。

提供 pipeline 运行指标查询、节点级指标、Dashboard 汇总和 LLM 成本 breakdown 接口。

路由前缀：``/api/metrics``

端点总览：
    - ``GET /api/metrics/runs``           -- pipeline 运行列表（分页 + 筛选）
    - ``GET /api/metrics/runs/{run_id}``  -- 运行详情（含节点指标）
    - ``GET /api/metrics/summary``        -- Dashboard 汇总
    - ``GET /api/metrics/llm-cost``       -- LLM 成本 breakdown
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.metrics_schemas import (
    LlmCostResponse,
    RunDetailResponse,
    RunSummaryResponse,
    SummaryResponse,
)
from src.api.metrics_service import (
    get_llm_cost,
    get_run_detail,
    get_summary,
    list_runs,
)
from src.common.response import PageResult, Result
from src.config.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["指标监控"])


@router.get("/runs", summary="Pipeline 运行列表", response_model=None)
def list_runs_api(
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    size: Annotated[
        int, Query(ge=1, le=100, description="每页条数，1-100")
    ] = 20,
    start_date: Annotated[
        str | None, Query(description="起始日期 YYYY-MM-DD")
    ] = None,
    end_date: Annotated[
        str | None, Query(description="结束日期 YYYY-MM-DD")
    ] = None,
    status: Annotated[
        str | None,
        Query(description="终态过滤 success/human_flagged/error"),
    ] = None,
) -> PageResult[RunSummaryResponse]:
    """查询 pipeline 运行列表，支持分页和筛选。"""
    start_dt = None
    end_dt = None
    if start_date is not None:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date is not None:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    items, total = list_runs(
        db,
        page=page,
        size=size,
        start_date=start_dt,
        end_date=end_dt,
        status=status,
    )
    return PageResult.ok(
        data=items,  # type: ignore[arg-type]
        total=total,
        page=page,
        size=size,
    )


@router.get("/runs/{run_id}", summary="运行详情（含节点指标）")
def get_run_detail_api(
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Result[RunDetailResponse]:
    """查询单个 pipeline 运行详情，含节点级指标。"""
    detail = get_run_detail(db, run_id)
    return Result.ok(data=detail)


@router.get("/summary", summary="Dashboard 汇总")
def get_summary_api(
    db: Annotated[Session, Depends(get_db)],
    days: Annotated[
        int, Query(ge=1, le=90, description="聚合天数，1-90")
    ] = 7,
) -> Result[SummaryResponse]:
    """查询 Dashboard 汇总指标（每日 + 总计）。"""
    summary = get_summary(db, days=days)
    return Result.ok(data=summary)


@router.get("/llm-cost", summary="LLM 成本 breakdown")
def get_llm_cost_api(
    db: Annotated[Session, Depends(get_db)],
    days: Annotated[
        int, Query(ge=1, le=90, description="聚合天数，1-90")
    ] = 7,
) -> Result[LlmCostResponse]:
    """查询 LLM 调用成本 breakdown，按供应商/模型分组。"""
    cost = get_llm_cost(db, days=days)
    return Result.ok(data=cost)


__all__ = ["router"]
