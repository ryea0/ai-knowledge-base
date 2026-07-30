"""Metrics 查询服务层。

提供 pipeline 运行指标、节点级指标、Dashboard 汇总和 LLM 成本 breakdown
的查询逻辑。作为 API 路由层和 ORM 层之间的业务逻辑层。

所有函数为只读查询，不修改数据。参数校验在此层完成，无效参数抛出
``BizException(ErrorCode.PARAM_ERROR)``。

事务约定：
    本模块不调用 ``session.commit()``，仅执行查询。
    事务由调用方控制（FastAPI ``get_db`` 依赖）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.api.metrics_schemas import (
    DailySummary,
    LlmCostGrandTotal,
    LlmCostItem,
    LlmCostResponse,
    NodeMetricResponse,
    RunDetailResponse,
    RunSummaryResponse,
    SummaryResponse,
    SummaryTotals,
)
from src.common.exceptions import BizException, ErrorCode
from src.llm.orm import LlmCallLog, LlmModel, LlmProvider
from src.models.metrics import NodeMetric, PipelineRun

logger = logging.getLogger(__name__)

_MAX_DAYS = 90
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 20


def _validate_pagination(page: int, size: int) -> None:
    """校验分页参数。

    Args:
        page: 页码，从 1 开始。
        size: 每页条数。

    Raises:
        BizException: 参数非法时抛出 PARAM_ERROR。
    """
    if page < 1:
        raise BizException(ErrorCode.PARAM_ERROR, "page 须 >= 1")
    if size < 1 or size > _MAX_PAGE_SIZE:
        raise BizException(
            ErrorCode.PARAM_ERROR, f"size 须在 1-{_MAX_PAGE_SIZE} 之间"
        )


def _validate_days(days: int) -> int:
    """校验 days 参数，返回截断后的值。

    Args:
        days: 天数。

    Returns:
        截断到 1-90 范围内的天数。

    Raises:
        BizException: days < 1 时抛出 PARAM_ERROR。
    """
    if days < 1:
        raise BizException(ErrorCode.PARAM_ERROR, "days 须 >= 1")
    return min(days, _MAX_DAYS)


def _orm_to_run_summary(run: PipelineRun) -> RunSummaryResponse:
    """将 PipelineRun ORM 对象转换为 RunSummaryResponse。

    Args:
        run: PipelineRun ORM 实例。

    Returns:
        RunSummaryResponse Pydantic 模型。
    """
    return RunSummaryResponse(
        id=run.id,
        trace_id=run.trace_id,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_ms=run.duration_ms,
        source_count=run.source_count,
        analysis_count=run.analysis_count,
        article_count=run.article_count,
        saved_count=run.saved_count,
        human_flagged=bool(run.human_flagged),
        review_passed=bool(run.review_passed),
        iteration=run.iteration,
        total_cost_yuan=float(run.total_cost_yuan),
        created_at=run.created_at,
    )


def _orm_to_node_metric(node: NodeMetric) -> NodeMetricResponse:
    """将 NodeMetric ORM 对象转换为 NodeMetricResponse。

    Args:
        node: NodeMetric ORM 实例。

    Returns:
        NodeMetricResponse Pydantic 模型。
    """
    return NodeMetricResponse(
        id=node.id,
        node_name=node.node_name,
        duration_ms=node.duration_ms,
        cost_data=node.cost_data,
        review_passed=bool(node.review_passed) if node.review_passed is not None else None,
        iteration=node.iteration,
        error=node.error,
        created_at=node.created_at,
    )


def list_runs(
    session: Session,
    *,
    page: int = 1,
    size: int = _DEFAULT_PAGE_SIZE,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    status: str | None = None,
) -> tuple[list[RunSummaryResponse], int]:
    """分页查询 pipeline 运行列表。

    Args:
        session: SQLAlchemy Session。
        page: 页码，从 1 开始。
        size: 每页条数，最大 100。
        start_date: 起始日期（含），按 started_at 过滤。
        end_date: 结束日期（含），按 started_at 过滤。
        status: 终态过滤（success / human_flagged / error）。

    Returns:
        (运行列表, 总条数) 元组。
    """
    _validate_pagination(page, size)

    stmt = select(PipelineRun)
    count_stmt = select(func.count()).select_from(PipelineRun)

    if start_date is not None:
        stmt = stmt.where(PipelineRun.started_at >= start_date)
        count_stmt = count_stmt.where(PipelineRun.started_at >= start_date)
    if end_date is not None:
        end_inclusive = end_date.replace(hour=23, minute=59, second=59)
        stmt = stmt.where(PipelineRun.started_at <= end_inclusive)
        count_stmt = count_stmt.where(PipelineRun.started_at <= end_inclusive)
    if status is not None:
        stmt = stmt.where(PipelineRun.status == status)
        count_stmt = count_stmt.where(PipelineRun.status == status)

    total = session.execute(count_stmt).scalar_one()

    stmt = stmt.order_by(PipelineRun.started_at.desc())
    offset = (page - 1) * size
    stmt = stmt.offset(offset).limit(size)

    runs = session.execute(stmt).scalars().all()
    items = [_orm_to_run_summary(r) for r in runs]

    logger.debug(
        "list_runs: page=%d size=%d total=%d returned=%d",
        page, size, total, len(items),
    )
    return items, total


def get_run_detail(
    session: Session,
    run_id: int,
) -> RunDetailResponse:
    """查询单个 pipeline 运行详情（含节点指标）。

    Args:
        session: SQLAlchemy Session。
        run_id: 运行 ID。

    Returns:
        RunDetailResponse 含节点指标列表。

    Raises:
        BizException: 运行不存在时抛出 NOT_FOUND。
    """
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise BizException(ErrorCode.NOT_FOUND, "资源不存在")

    node_stmt = (
        select(NodeMetric)
        .where(NodeMetric.run_id == run_id)
        .order_by(NodeMetric.created_at.asc())
    )
    nodes = session.execute(node_stmt).scalars().all()

    summary = _orm_to_run_summary(run)
    return RunDetailResponse(
        **summary.model_dump(),
        nodes=[_orm_to_node_metric(n) for n in nodes],
    )


def get_summary(
    session: Session,
    days: int = 7,
) -> SummaryResponse:
    """查询 Dashboard 汇总指标。

    使用 SQL GROUP BY DATE(started_at) 聚合，缺失日期在 Python 中补零。

    Args:
        session: SQLAlchemy Session。
        days: 聚合天数，1-90。

    Returns:
        SummaryResponse 含每日列表和汇总。
    """
    days = _validate_days(days)

    now = datetime.now(UTC).replace(tzinfo=None)
    start = now - timedelta(days=days - 1)

    stmt = (
        select(
            func.date(PipelineRun.started_at).label("run_date"),
            func.count().label("run_count"),
            func.sum(
                case(
                    (PipelineRun.status == "success", 1),
                    else_=0,
                )
            ).label("success_count"),
            func.coalesce(func.sum(PipelineRun.source_count), 0).label(
                "source_count"
            ),
            func.coalesce(func.sum(PipelineRun.article_count), 0).label(
                "article_count"
            ),
            func.coalesce(func.sum(PipelineRun.saved_count), 0).label(
                "saved_count"
            ),
            func.sum(
                case(
                    (PipelineRun.review_passed == 1, 1),
                    else_=0,
                )
            ).label("review_passed_count"),
            func.coalesce(func.sum(PipelineRun.total_cost_yuan), 0.0).label(
                "total_cost_yuan"
            ),
        )
        .where(PipelineRun.started_at >= start)
        .group_by(func.date(PipelineRun.started_at))
    )

    rows = session.execute(stmt).all()
    db_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        date_str = str(row.run_date)
        db_map[date_str] = {
            "run_count": int(row.run_count or 0),
            "success_count": int(row.success_count or 0),
            "source_count": int(row.source_count or 0),
            "article_count": int(row.article_count or 0),
            "saved_count": int(row.saved_count or 0),
            "review_passed_count": int(row.review_passed_count or 0),
            "total_cost_yuan": float(row.total_cost_yuan or 0.0),
        }

    daily: list[DailySummary] = []
    for i in range(days):
        date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        data = db_map.get(date, {})
        daily.append(
            DailySummary(
                date=date,
                run_count=data.get("run_count", 0),
                success_count=data.get("success_count", 0),
                source_count=data.get("source_count", 0),
                article_count=data.get("article_count", 0),
                saved_count=data.get("saved_count", 0),
                review_passed_count=data.get("review_passed_count", 0),
                total_cost_yuan=data.get("total_cost_yuan", 0.0),
            )
        )

    total_runs = sum(d.run_count for d in daily)
    total_success = sum(d.success_count for d in daily)
    total_review_passed = sum(d.review_passed_count for d in daily)
    avg_pass_rate = (
        total_review_passed / total_runs if total_runs > 0 else 0.0
    )

    totals = SummaryTotals(
        total_runs=total_runs,
        total_success=total_success,
        avg_review_pass_rate=round(avg_pass_rate, 4),
        total_source_count=sum(d.source_count for d in daily),
        total_article_count=sum(d.article_count for d in daily),
        total_saved_count=sum(d.saved_count for d in daily),
        total_cost_yuan=round(sum(d.total_cost_yuan for d in daily), 6),
    )

    return SummaryResponse(daily=daily, totals=totals)


def get_llm_cost(
    session: Session,
    days: int = 7,
) -> LlmCostResponse:
    """查询 LLM 调用成本 breakdown。

    关联 ``kb_llm_call_log`` 与 ``kb_llm_provider`` / ``kb_llm_model``，
    按 (provider_id, model_id, currency) 分组聚合。

    Args:
        session: SQLAlchemy Session。
        days: 聚合天数，1-90。

    Returns:
        LlmCostResponse 含明细列表和总计。
    """
    days = _validate_days(days)

    now = datetime.now(UTC).replace(tzinfo=None)
    start = now - timedelta(days=days - 1)

    stmt = (
        select(
            LlmCallLog.provider_id,
            LlmProvider.provider_code,
            LlmCallLog.model_id,
            LlmModel.model_code,
            LlmCallLog.cost_currency.label("currency"),
            func.count().label("call_count"),
            func.sum(
                case(
                    (LlmCallLog.is_success == 1, 1),
                    else_=0,
                )
            ).label("success_count"),
            func.coalesce(func.sum(LlmCallLog.input_tokens), 0).label(
                "total_input_tokens"
            ),
            func.coalesce(func.sum(LlmCallLog.output_tokens), 0).label(
                "total_output_tokens"
            ),
            func.coalesce(func.sum(LlmCallLog.total_tokens), 0).label(
                "total_tokens"
            ),
            func.coalesce(func.sum(LlmCallLog.cost_amount), 0.0).label(
                "total_cost"
            ),
        )
        .select_from(LlmCallLog)
        .join(
            LlmProvider,
            LlmCallLog.provider_id == LlmProvider.id,
            isouter=True,
        )
        .join(
            LlmModel,
            LlmCallLog.model_id == LlmModel.id,
            isouter=True,
        )
        .where(LlmCallLog.called_at >= start)
        .where(LlmCallLog.is_deleted == 0)
        .group_by(
            LlmCallLog.provider_id,
            LlmProvider.provider_code,
            LlmCallLog.model_id,
            LlmModel.model_code,
            LlmCallLog.cost_currency,
        )
        .order_by(func.coalesce(func.sum(LlmCallLog.cost_amount), 0.0).desc())
    )

    rows = session.execute(stmt).all()

    items: list[LlmCostItem] = []
    total_cost_cny = 0.0
    total_cost_usd = 0.0
    total_calls = 0
    total_tokens = 0

    for row in rows:
        currency = row.currency or "CNY"
        cost = float(row.total_cost or 0.0)
        item = LlmCostItem(
            provider_id=row.provider_id,
            provider_code=row.provider_code or "unknown",
            model_id=row.model_id,
            model_code=row.model_code or "unknown",
            call_count=int(row.call_count or 0),
            success_count=int(row.success_count or 0),
            total_input_tokens=int(row.total_input_tokens or 0),
            total_output_tokens=int(row.total_output_tokens or 0),
            total_tokens=int(row.total_tokens or 0),
            total_cost=round(cost, 6),
            currency=currency,
        )
        items.append(item)

        if currency == "USD":
            total_cost_usd += cost
        else:
            total_cost_cny += cost
        total_calls += item.call_count
        total_tokens += item.total_tokens

    grand_total = LlmCostGrandTotal(
        total_cost_cny=round(total_cost_cny, 6),
        total_cost_usd=round(total_cost_usd, 6),
        total_calls=total_calls,
        total_tokens=total_tokens,
    )

    return LlmCostResponse(items=items, grand_total=grand_total)


__all__ = [
    "get_llm_cost",
    "get_run_detail",
    "get_summary",
    "list_runs",
]
