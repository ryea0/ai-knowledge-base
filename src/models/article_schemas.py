"""知识条目 Pydantic 请求/响应模型。

用于前端 API 层校验，与 :mod:`src.models.article` 的 ORM 模型对应但不耦合。
ORM -> Schema 转换在 Article Service 层完成。

字段定义见 AGENTS.md §4，必填性对齐 §7.5 DDL 约束。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.common.json_config import JsonDateTime
from src.models.enums import ArticleStatus, Category, SourcePlatform


class ArticleResponse(BaseModel):
    """知识条目响应模型。

    与 ``kb_article`` 表字段一一对应，``article_id`` 为业务标识。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="自增主键")
    article_id: str = Field(..., description="业务ID，格式 kb-YYYYMMDD-NNNN")
    title: str = Field(..., description="条目标题")
    source_url: str = Field(..., description="原始链接")
    source_platform: SourcePlatform = Field(..., description="来源平台")
    source_score: int = Field(0, description="来源热度")
    summary: str = Field(..., description="AI生成中文摘要")
    content_path: str = Field(..., description="原始内容文件路径")
    tags: list[str] = Field(..., description="标签数组")
    category: Category = Field(..., description="内容分类")
    status: ArticleStatus = Field(..., description="生命周期状态")
    language: str = Field("zh", description="原文语言")
    collected_at: JsonDateTime = Field(..., description="采集时间")
    analyzed_at: JsonDateTime | None = Field(None, description="分析完成时间")
    published_at: JsonDateTime | None = Field(None, description="发布时间")
    published_channels: list[str] | None = Field(
        None, description="已推送渠道列表"
    )
    is_deleted: bool = Field(False, description="是否软删除")
    deleted_at: JsonDateTime | None = Field(None, description="软删除时间")
    created_at: JsonDateTime = Field(..., description="创建时间")
    updated_at: JsonDateTime = Field(..., description="更新时间")


class ArticleCreate(BaseModel):
    """创建知识条目请求（由整理 Agent 构造）。

    整合采集元信息与分析结果，字段对齐 AGENTS.md §4。
    ``article_id`` 由 DB 自增主键生成，不在请求中传入。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=120, description="条目标题")
    source_url: str = Field(..., min_length=1, max_length=512, description="原始链接")
    source_platform: SourcePlatform = Field(..., description="来源平台")
    source_score: int = Field(0, ge=0, description="来源热度")
    summary: str = Field(..., min_length=1, max_length=500, description="AI生成中文摘要")
    content_path: str = Field(..., min_length=1, max_length=255, description="原始内容文件路径")
    tags: list[str] = Field(..., min_length=1, max_length=20, description="标签数组")
    category: Category = Field(..., description="内容分类")
    language: str = Field("zh", min_length=2, max_length=2, description="原文语言")
    collected_at: JsonDateTime = Field(..., description="采集时间")
    analyzed_at: JsonDateTime | None = Field(None, description="分析完成时间")


class ArticleUpdate(BaseModel):
    """更新知识条目请求（所有字段可选）。

    仅允许在 ``status`` 为 ``pending`` 或 ``reviewed`` 时修改内容字段。
    ``published`` 后禁止修改内容（AGENTS.md 红线 #2），仅允许转 ``archived``。
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=120)
    summary: str | None = Field(None, min_length=1, max_length=500)
    tags: list[str] | None = Field(None, min_length=1, max_length=20)
    category: Category | None = None
    content_path: str | None = Field(None, min_length=1, max_length=255)
    language: str | None = Field(None, min_length=2, max_length=2)
    analyzed_at: JsonDateTime | None = None


class ArticleListQuery(BaseModel):
    """知识条目列表查询参数。

    支持按状态、分类、来源平台、标签筛选，以及关键词搜索。
    """

    model_config = ConfigDict(extra="forbid")

    status: ArticleStatus | None = Field(None, description="按状态筛选")
    category: Category | None = Field(None, description="按分类筛选")
    source_platform: SourcePlatform | None = Field(None, description="按来源平台筛选")
    tags: list[str] | None = Field(None, description="按标签筛选（多选，OR 语义）")
    keyword: str | None = Field(
        None, max_length=100, description="关键词搜索（标题+摘要）"
    )
    page: int = Field(1, ge=1, description="页码，从1开始")
    size: int = Field(10, ge=1, le=100, description="每页条数")
    sort_by: str = Field("created_at", description="排序字段")
    sort_order: str = Field("desc", description="排序方向 asc/desc")


class ArticleStatusUpdate(BaseModel):
    """状态流转请求。

    须遵循 AGENTS.md §6.6 转换矩阵：
        - pending -> reviewed / archived
        - reviewed -> published / archived
        - published -> archived
        - archived -> （终态，不可转换）
    """

    model_config = ConfigDict(extra="forbid")

    status: ArticleStatus = Field(..., description="目标状态")
    reason: str | None = Field(
        None, max_length=200, description="状态变更原因（可选，用于审计日志）"
    )


class ArticleDistributeRequest(BaseModel):
    """触发分发请求。

    指定要推送的渠道列表，须遵循分发幂等（§6.6 第5条）。
    条目状态须为 ``reviewed`` 方可分发。
    """

    model_config = ConfigDict(extra="forbid")

    channels: list[str] = Field(
        ..., min_length=1, description="目标渠道列表，如 ['telegram', 'feishu']"
    )


class ArticleStats(BaseModel):
    """知识条目统计信息（仪表盘用）。

    提供各状态计数和今日新增数。
    """

    model_config = ConfigDict(extra="forbid")

    total: int = Field(0, ge=0, description="条目总数（不含软删除）")
    pending: int = Field(0, ge=0, description="待审核条目数")
    reviewed: int = Field(0, ge=0, description="已审核条目数")
    published: int = Field(0, ge=0, description="已发布条目数")
    archived: int = Field(0, ge=0, description="已归档条目数")
    today_new: int = Field(0, ge=0, description="今日新增条目数")


class ArticleRawContent(BaseModel):
    """原始内容响应（条目详情页原始 Markdown 阅读）。

    对应 ``GET /articles/:id/raw`` 端点，返回 content_path 指向的 Markdown 原文。
    原始内容只读，禁止编辑（AGENTS.md 红线 #1）。
    """

    model_config = ConfigDict(extra="forbid")

    article_id: str = Field(..., description="条目业务ID")
    content_path: str = Field(..., description="原始内容文件路径")
    content: str = Field(..., description="Markdown 原文内容")
    collected_at: JsonDateTime = Field(..., description="采集时间")


__all__ = [
    "ArticleCreate",
    "ArticleDistributeRequest",
    "ArticleListQuery",
    "ArticleRawContent",
    "ArticleResponse",
    "ArticleStats",
    "ArticleStatusUpdate",
    "ArticleUpdate",
]
