"""Pipeline 指标 ORM 模型。

对应 DB 表 ``kb_pipeline_run`` 和 ``kb_node_metric``，
DDL 见 ``deploy/sql/10_kb_pipeline_metrics.sql``。

两张表均为**纯追加日志表**（db-conventions §7.1 例外），
仅需 ``id`` + ``created_at``，不需要 ``updated_at`` / ``is_deleted`` /
``deleted_at``。

关联关系：``kb_node_metric.run_id`` -> ``kb_pipeline_run.id``，
在应用层维护，不使用外键（db-conventions §7.1 禁用外键）。

PRD: ``_bmad-output/planning-artifacts/prd-pipeline-metrics.md``
架构: ``_bmad-output/planning-artifacts/arch-pipeline-metrics.md``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_entity import Base, _BigInt


class PipelineRun(Base):
    """工作流执行记录 ORM 模型，对应 ``kb_pipeline_run`` 表。

    每次工作流执行一行，记录 trace_id、起止时间、终态、转化漏斗。

    纯追加日志表，不继承 BaseEntity（无 updated_at / is_deleted）。

    Attributes:
        trace_id: 链路追踪 ID，关联 kb_node_metric.trace_id。
        status: 执行终态（success / human_flagged / error）。
        started_at: 工作流开始时间。
        ended_at: 工作流结束时间。
        duration_ms: 总耗时（毫秒）。
        source_count: 采集条目数（M5 漏斗入口）。
        analysis_count: 分析条目数（M5 漏斗中间）。
        article_count: 整理后条目数（M5 漏斗中间）。
        saved_count: 保存条目数（M5 漏斗出口）。
        human_flagged: 是否被人工标记。
        review_passed: 审核是否通过。
        iteration: 审核循环次数。
        total_cost_yuan: LLM 总成本（元）。
        created_at: 记录创建时间。
    """

    __tablename__ = "kb_pipeline_run"

    id: Mapped[int] = mapped_column(
        _BigInt, primary_key=True, autoincrement=True
    )
    trace_id: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    analysis_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    saved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    human_flagged: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    review_passed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    iteration: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    total_cost_yuan: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0.0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.now,
    )


class NodeMetric(Base):
    """节点级指标 ORM 模型，对应 ``kb_node_metric`` 表。

    每个节点每次执行一行（含循环中的重复执行），
    通过 ``run_id`` 和 ``trace_id`` 关联到 ``kb_pipeline_run``。

    纯追加日志表，不继承 BaseEntity。

    Attributes:
        run_id: 关联的 kb_pipeline_run.id（应用层维护，非 FK）。
        trace_id: 链路追踪 ID。
        node_name: 节点名称（collect / analyze / review / organize /
            revise / save / human_flag）。
        duration_ms: 节点耗时（毫秒）。
        cost_data: 节点 LLM 成本数据（JSON: prompt_tokens /
            completion_tokens / total_tokens）。
        review_passed: 审核是否通过（仅 review 节点填充）。
        iteration: 审核轮次（仅 review 节点填充）。
        error: 错误信息（脱敏后，正常执行时为空字符串）。
        created_at: 记录创建时间。
    """

    __tablename__ = "kb_node_metric"

    id: Mapped[int] = mapped_column(
        _BigInt, primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(16), nullable=False)
    node_name: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    review_passed: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.now,
    )


__all__ = ["NodeMetric", "PipelineRun"]
