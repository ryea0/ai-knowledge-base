"""Metrics API Pydantic 请求/响应模型。

与 :mod:`src.models.metrics` ORM 模型对应但不耦合。
ORM -> Schema 转换在 :mod:`src.api.metrics_service` 中完成。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.json_config import JsonDateTime


class RunSummaryResponse(BaseModel):
    """Pipeline 运行摘要响应。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="运行 ID")
    trace_id: str = Field(..., description="链路追踪 ID")
    status: str = Field(..., description="执行终态 success/human_flagged/error")
    started_at: JsonDateTime | None = Field(None, description="开始时间")
    ended_at: JsonDateTime | None = Field(None, description="结束时间")
    duration_ms: int | None = Field(None, description="总耗时毫秒")
    source_count: int = Field(0, description="采集条目数")
    analysis_count: int = Field(0, description="分析条目数")
    article_count: int = Field(0, description="整理后条目数")
    saved_count: int = Field(0, description="保存条目数")
    human_flagged: bool = Field(False, description="是否被人工标记")
    review_passed: bool = Field(False, description="审核是否通过")
    iteration: int = Field(0, description="审核循环次数")
    total_cost_yuan: float = Field(0.0, description="LLM 总成本（元）")
    created_at: JsonDateTime = Field(..., description="记录创建时间")


class NodeMetricResponse(BaseModel):
    """节点级指标响应。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="节点指标 ID")
    node_name: str = Field(..., description="节点名称")
    duration_ms: int = Field(..., description="节点耗时毫秒")
    cost_data: dict[str, Any] | None = Field(
        None, description="节点 LLM 成本数据"
    )
    review_passed: bool | None = Field(None, description="审核是否通过")
    iteration: int | None = Field(None, description="审核轮次")
    error: str = Field("", description="错误信息")
    created_at: JsonDateTime = Field(..., description="记录创建时间")


class RunDetailResponse(RunSummaryResponse):
    """Pipeline 运行详情响应（含节点指标）。"""

    nodes: list[NodeMetricResponse] = Field(
        default_factory=list, description="节点级指标列表"
    )


class DailySummary(BaseModel):
    """单日汇总指标。"""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(..., description="日期 YYYY-MM-DD")
    run_count: int = Field(0, description="运行次数")
    success_count: int = Field(0, description="成功次数")
    source_count: int = Field(0, description="采集条目数")
    article_count: int = Field(0, description="整理后条目数")
    saved_count: int = Field(0, description="保存条目数")
    review_passed_count: int = Field(0, description="审核通过次数")
    total_cost_yuan: float = Field(0.0, description="LLM 总成本（元）")


class SummaryTotals(BaseModel):
    """日期范围汇总指标。"""

    model_config = ConfigDict(extra="forbid")

    total_runs: int = Field(0, description="总运行次数")
    total_success: int = Field(0, description="总成功次数")
    avg_review_pass_rate: float = Field(
        0.0, description="平均审核通过率 0.0-1.0"
    )
    total_source_count: int = Field(0, description="总采集条目数")
    total_article_count: int = Field(0, description="总整理后条目数")
    total_saved_count: int = Field(0, description="总保存条目数")
    total_cost_yuan: float = Field(0.0, description="总 LLM 成本（元）")


class SummaryResponse(BaseModel):
    """Dashboard 汇总响应。"""

    model_config = ConfigDict(extra="forbid")

    daily: list[DailySummary] = Field(
        default_factory=list, description="每日汇总列表"
    )
    totals: SummaryTotals = Field(
        ..., description="日期范围汇总指标"
    )


class LlmCostItem(BaseModel):
    """LLM 成本明细项。"""

    model_config = ConfigDict(extra="forbid")

    provider_id: int = Field(..., description="供应商 ID")
    provider_code: str = Field(..., description="供应商代码")
    model_id: int = Field(..., description="模型 ID")
    model_code: str = Field(..., description="模型代码")
    call_count: int = Field(0, description="调用次数")
    success_count: int = Field(0, description="成功次数")
    total_input_tokens: int = Field(0, description="总输入 token 数")
    total_output_tokens: int = Field(0, description="总输出 token 数")
    total_tokens: int = Field(0, description="总 token 数")
    total_cost: float = Field(0.0, description="总成本")
    currency: str = Field("CNY", description="币种 CNY/USD")


class LlmCostGrandTotal(BaseModel):
    """LLM 成本总计。"""

    model_config = ConfigDict(extra="forbid")

    total_cost_cny: float = Field(0.0, description="CNY 总成本")
    total_cost_usd: float = Field(0.0, description="USD 总成本")
    total_calls: int = Field(0, description="总调用次数")
    total_tokens: int = Field(0, description="总 token 数")


class LlmCostResponse(BaseModel):
    """LLM 成本 breakdown 响应。"""

    model_config = ConfigDict(extra="forbid")

    items: list[LlmCostItem] = Field(
        default_factory=list, description="成本明细列表"
    )
    grand_total: LlmCostGrandTotal = Field(
        ..., description="成本总计"
    )


__all__ = [
    "DailySummary",
    "LlmCostGrandTotal",
    "LlmCostItem",
    "LlmCostResponse",
    "NodeMetricResponse",
    "RunDetailResponse",
    "RunSummaryResponse",
    "SummaryResponse",
    "SummaryTotals",
]
