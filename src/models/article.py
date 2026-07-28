"""知识条目 SQLAlchemy ORM 模型。

对应 DB 表 ``kb_article``，DDL 见 ``deploy/sql/05_kb_article.sql``，
字段定义见 AGENTS.md §4 / §7.5，SPEC §4.10 扩展字段（score/highlights/score_reason）。

数据权威：MySQL ``kb_article`` 表为知识条目的唯一 source of truth；
``knowledge/articles/<id>.json`` 为 DB 记录的磁盘投影，可从 DB 重建。
写入顺序：先写 DB（事务内），成功后同步写 JSON 文件；两者不一致时以 DB 为准。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_entity import BaseEntity
from src.models.enums import ArticleStatus


class Article(BaseEntity):
    """知识条目 ORM 模型，对应 ``kb_article`` 表。

    存储采集 -> 分析 -> 整理后的结构化知识条目，
    支持状态流转（pending -> reviewed -> published -> archived）。

    继承 :class:`BaseEntity` 获得 ``id`` / ``created_at`` / ``updated_at`` /
    ``is_deleted`` / ``deleted_at`` 字段，无需重复定义。

    Attributes:
        article_id: 业务 ID，格式 ``kb-YYYYMMDD-NNNN``。
        title: 条目标题。
        source_url: 原始链接。
        source_platform: 来源平台字符串（github_trending / hackernews）。
        source_score: 来源热度（star 数 / points）。
        summary: AI 生成中文摘要。
        content_path: 原始内容文件路径（相对项目根目录）。
        tags: 标签数组（JSON）。
        category: 内容分类字符串（model_release / paper / tool / tutorial / news）。
        status: 生命周期状态（TINYINT，映射见 ArticleStatus）。
        language: 原文语言（zh / en）。
        collected_at: 采集时间。
        analyzed_at: 分析完成时间，未分析为 None。
        published_at: 发布时间，未发布为 None。
        published_channels: 已推送渠道列表，未分发为 None。
        score: analyzer 评分 1-10（SPEC §4.10 扩展），未分析为 None。
        score_reason: 评分理由（SPEC §4.10 扩展）。
        highlights: 亮点数组（SPEC §4.10 扩展）。
    """

    __tablename__ = "kb_article"

    article_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)
    source_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    content_path: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[ArticleStatus] = mapped_column(
        Integer, nullable=False, default=ArticleStatus.PENDING
    )
    language: Mapped[str] = mapped_column(CHAR(2), nullable=False, default="zh")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    published_channels: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    highlights: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)


__all__ = ["Article"]
