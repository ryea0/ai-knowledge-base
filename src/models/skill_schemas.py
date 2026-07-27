"""技能输出数据的 Pydantic 模型。

本模块镜像各技能目录下 ``schema.json`` 的结构，为代码路径（采集器/分发器）
提供运行时校验能力。每个模型与其对应的 ``schema.json`` 须保持一致；
如有变更，**先改 ``schema.json``** 再同步本模块。

对应关系：
    - GithubTrendingBatch   <-> .opencode/skills/fetch-github-trending/schema.json
    - HackerNewsRawItem     <-> .opencode/skills/fetch-hackernews/schema.json
    - DistributeResult      <-> .opencode/skills/distribute-message/schema.json
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_ARTICLE_ID_PATTERN = r"^kb-\d{8}-\d{4}$"
_ISO_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


class GithubTrendingItem(BaseModel):
    """GitHub Trending 单条仓库信息。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ..., pattern=r"^[^/]+/[^/]+$", description="仓库全名 owner/repo"
    )
    url: str = Field(
        ...,
        pattern=r"^https://github\.com/[^/]+/[^/]+$",
        description="仓库链接",
    )
    summary: str = Field(
        ..., min_length=10, max_length=200, description="中文摘要"
    )
    stars: int = Field(..., ge=0, description="star 数")
    language: str = Field("", description="主语言，无则为空字符串")
    topics: list[str] = Field(default_factory=list, description="话题标签数组")


class GithubTrendingBatch(BaseModel):
    """github-trending 技能输出的采集批次。

    对应 ``.opencode/skills/fetch-github-trending/schema.json``。
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["github_trending"] = "github_trending"
    skill: Literal["github-trending"] = "github-trending"
    collected_at: str = Field(
        ..., pattern=_ISO_UTC_PATTERN, description="采集时间 ISO 8601 UTC"
    )
    items: list[GithubTrendingItem] = Field(
        ..., max_length=15, description="候选条目数组，按 stars 降序"
    )


class HackerNewsRawItem(BaseModel):
    """fetch-hackernews 技能输出的原始条目 front-matter。

    对应 ``.opencode/skills/fetch-hackernews/schema.json``。
    """

    model_config = ConfigDict(extra="forbid")

    article_id: str = Field(
        ..., pattern=_ARTICLE_ID_PATTERN, description="业务ID kb-YYYYMMDD-NNNN"
    )
    title: str = Field(..., min_length=1, max_length=120, description="条目标题")
    source_url: str = Field(..., description="原始链接")
    source_platform: Literal["hackernews"] = "hackernews"
    source_score: int = Field(..., ge=0, description="来源热度 points")
    collected_at: str = Field(
        ..., pattern=_ISO_UTC_PATTERN, description="采集时间 ISO 8601 UTC"
    )
    body: str = Field(..., min_length=1, description="正文内容 Markdown")


class DistributeResult(BaseModel):
    """distribute-message 技能执行后的分发结果。

    对应 ``.opencode/skills/distribute-message/schema.json``。
    """

    model_config = ConfigDict(extra="forbid")

    article_id: str = Field(
        ..., pattern=_ARTICLE_ID_PATTERN, description="被推送的知识条目业务ID"
    )
    channel: Literal["telegram", "feishu"] = Field(..., description="推送渠道名")
    status: Literal["success", "skipped", "failed"] = Field(
        ..., description="推送结果"
    )
    attempted_at: str = Field(
        ..., pattern=_ISO_UTC_PATTERN, description="推送尝试时间 ISO 8601 UTC"
    )
    published_at: str | None = Field(
        None,
        pattern=_ISO_UTC_PATTERN,
        description="成功时填条目发布时间；失败/跳过为 null",
    )
    error: str | None = Field(None, description="失败原因；成功/跳过为 null")


__all__ = [
    "DistributeResult",
    "GithubTrendingBatch",
    "GithubTrendingItem",
    "HackerNewsRawItem",
]
