"""Pipeline 触发 REST API 路由。

提供通过 HTTP 接口触发完整知识库采集流程的能力。

路由前缀：``/api/pipeline``

端点总览：
    - ``POST /api/pipeline/run``   -- 触发完整流水线（graph 或 pipeline 模式）
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.common.response import Result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["采集流水线"])


class PipelineRunRequest(BaseModel):
    """流水线触发请求。

    Attributes:
        mode: 运行模式，``graph`` 为 LangGraph 工作流，``pipeline`` 为四步流水线。
        sources: 数据源列表（仅 pipeline 模式生效），逗号分隔。
        limit: 每个数据源最大采集条数（仅 pipeline 模式生效）。
        dry_run: 干跑模式（仅 pipeline 模式生效），不保存结果。
    """

    mode: Literal["graph", "pipeline"] = Field(
        default="graph",
        description="运行模式：graph=LangGraph 工作流，pipeline=四步流水线",
    )
    sources: str = Field(
        default="github,rss",
        description="数据源列表（仅 pipeline 模式），逗号分隔",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="每个数据源最大采集条数（仅 pipeline 模式）",
    )
    dry_run: bool = Field(
        default=False,
        description="干跑模式（仅 pipeline 模式），不保存结果",
    )


class PipelineRunResponse(BaseModel):
    """流水线触发响应。

    Attributes:
        mode: 实际运行模式。
        success: 是否成功完成。
        stats: 执行统计信息（键值对）。
    """

    mode: str = Field(description="运行模式")
    success: bool = Field(description="是否成功完成")
    stats: dict[str, Any] = Field(default_factory=dict, description="执行统计信息")


@router.post(
    "/run",
    response_model=Result[PipelineRunResponse],
    summary="触发完整采集流程",
    description=(
        "通过 HTTP 接口触发知识库采集流程。支持两种模式：\n\n"
        "- **graph**: LangGraph 工作流（采集 -> 分析 -> 审核 -> 整理 -> 保存 -> 推送简报）\n"
        "- **pipeline**: 四步流水线（采集 -> 分析 -> 整理 -> 保存）\n\n"
        "graph 模式会自动推送每日简报到飞书，pipeline 模式不会。"
    ),
)
def run_pipeline_api(
    req: Annotated[PipelineRunRequest, "请求参数"],
) -> Result[PipelineRunResponse]:
    """触发完整采集流程。

    Args:
        req: 请求参数。

    Returns:
        包含执行统计的统一响应。
    """
    from src.common.trace import generate_trace_id, set_trace_id

    trace_id = generate_trace_id()
    set_trace_id(trace_id)
    logger.info("API 触发流水线: mode=%s trace_id=%s", req.mode, trace_id)

    if req.mode == "graph":
        return Result.ok(data=_run_graph())
    else:
        return Result.ok(data=_run_pipeline(req.sources, req.limit, req.dry_run))


def _run_graph() -> PipelineRunResponse:
    """运行 LangGraph 工作流。

    Returns:
        工作流执行统计响应。
    """
    from src.graph.graph import run_workflow

    try:
        final_state = run_workflow()
    except Exception:
        logger.exception("graph 工作流执行失败")
        return PipelineRunResponse(
            mode="graph",
            success=False,
            stats={"error": "工作流执行失败，详见日志"},
        )

    stats: dict[str, Any] = {
        "sources": len(final_state.get("sources", [])),
        "analyses": len(final_state.get("analyses", [])),
        "articles": len(final_state.get("articles", [])),
        "saved_count": final_state.get("saved_count", 0),
        "review_passed": final_state.get("review_passed", False),
        "human_flagged": final_state.get("human_flagged", False),
    }

    guard = final_state.get("cost_guard")
    if guard is not None and guard.records:
        report = guard.get_report()
        summary = report["summary"]
        stats["cost_yuan"] = round(summary["total_cost_yuan"], 6)
        stats["call_count"] = summary["call_count"]

    return PipelineRunResponse(mode="graph", success=True, stats=stats)


def _run_pipeline(sources: str, limit: int, dry_run: bool) -> PipelineRunResponse:
    """运行四步流水线。

    Args:
        sources: 逗号分隔的数据源列表。
        limit: 每个数据源最大采集条数。
        dry_run: 是否干跑模式。

    Returns:
        流水线执行统计响应。
    """
    from src.pipeline.pipeline import Pipeline

    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    if not source_list:
        return PipelineRunResponse(
            mode="pipeline",
            success=False,
            stats={"error": "未指定有效数据源"},
        )

    pipeline = Pipeline(source_list, limit, dry_run=dry_run)
    result = pipeline.run()

    stats: dict[str, Any] = {
        "collected": result.collected,
        "analyzed": result.analyzed,
        "saved": result.saved,
        "skipped_duplicates": result.skipped_duplicates,
        "errors": result.errors,
        "dry_run": result.dry_run,
    }

    return PipelineRunResponse(
        mode="pipeline",
        success=result.errors == 0,
        stats=stats,
    )
