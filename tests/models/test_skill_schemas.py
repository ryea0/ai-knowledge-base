"""src.models.skill_schemas 的单元测试。

测试覆盖：
- GithubTrendingItem / GithubTrendingBatch 验证
- HackerNewsRawItem 验证
- DistributeResult 验证
- 字段约束（pattern、min_length、max_length）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.skill_schemas import (
    DistributeResult,
    GithubTrendingBatch,
    GithubTrendingItem,
    HackerNewsRawItem,
)


class TestGithubTrendingItem:
    """GithubTrendingItem 测试。"""

    def test_valid_item(self) -> None:
        """合法条目。"""
        item = GithubTrendingItem(
            name="owner/repo",
            url="https://github.com/owner/repo",
            summary="这是一个测试摘要，长度足够。",
            stars=100,
            language="Python",
            topics=["ai", "llm"],
        )
        assert item.name == "owner/repo"
        assert item.stars == 100

    def test_invalid_name_format(self) -> None:
        """name 不符合 owner/repo 格式。"""
        with pytest.raises(ValidationError):
            GithubTrendingItem(
                name="invalid",
                url="https://github.com/owner/repo",
                summary="这是一个测试摘要，长度足够。",
                stars=0,
            )

    def test_invalid_url(self) -> None:
        """url 不符合 github.com 格式。"""
        with pytest.raises(ValidationError):
            GithubTrendingItem(
                name="owner/repo",
                url="https://gitlab.com/owner/repo",
                summary="这是一个测试摘要，长度足够。",
                stars=0,
            )

    def test_summary_too_short(self) -> None:
        """摘要太短。"""
        with pytest.raises(ValidationError):
            GithubTrendingItem(
                name="owner/repo",
                url="https://github.com/owner/repo",
                summary="短",
                stars=0,
            )

    def test_negative_stars(self) -> None:
        """star 数不能为负。"""
        with pytest.raises(ValidationError):
            GithubTrendingItem(
                name="owner/repo",
                url="https://github.com/owner/repo",
                summary="这是一个测试摘要，长度足够。",
                stars=-1,
            )

    def test_default_language_and_topics(self) -> None:
        """language 和 topics 有默认值。"""
        item = GithubTrendingItem(
            name="owner/repo",
            url="https://github.com/owner/repo",
            summary="这是一个测试摘要，长度足够。",
            stars=0,
        )
        assert item.language == ""
        assert item.topics == []


class TestGithubTrendingBatch:
    """GithubTrendingBatch 测试。"""

    def test_valid_batch(self) -> None:
        """合法批次。"""
        batch = GithubTrendingBatch(
            collected_at="2026-07-27T08:00:00Z",
            items=[
                GithubTrendingItem(
                    name="owner/repo",
                    url="https://github.com/owner/repo",
                    summary="这是一个测试摘要，长度足够。",
                    stars=100,
                )
            ],
        )
        assert batch.source == "github_trending"
        assert batch.skill == "github-trending"
        assert len(batch.items) == 1

    def test_invalid_collected_at_format(self) -> None:
        """collected_at 格式不合法。"""
        with pytest.raises(ValidationError):
            GithubTrendingBatch(
                collected_at="2026-07-27 08:00:00",
                items=[],
            )

    def test_extra_fields_forbidden(self) -> None:
        """禁止额外字段。"""
        with pytest.raises(ValidationError):
            GithubTrendingBatch(
                collected_at="2026-07-27T08:00:00Z",
                items=[],
                extra_field="bad",  # type: ignore[call-arg]
            )


class TestHackerNewsRawItem:
    """HackerNewsRawItem 测试。"""

    def test_valid_item(self) -> None:
        """合法条目。"""
        item = HackerNewsRawItem(
            article_id="kb-20260727-0001",
            title="测试标题",
            source_url="https://news.ycombinator.com/item?id=12345",
            source_score=2941,
            collected_at="2026-07-27T08:00:00Z",
            body="正文内容",
        )
        assert item.source_platform == "hackernews"
        assert item.source_score == 2941

    def test_invalid_article_id(self) -> None:
        """article_id 格式不合法。"""
        with pytest.raises(ValidationError):
            HackerNewsRawItem(
                article_id="invalid-id",
                title="测试",
                source_url="https://example.com",
                source_score=0,
                collected_at="2026-07-27T08:00:00Z",
                body="正文",
            )

    def test_title_too_long(self) -> None:
        """标题超过 120 字符。"""
        with pytest.raises(ValidationError):
            HackerNewsRawItem(
                article_id="kb-20260727-0001",
                title="x" * 121,
                source_url="https://example.com",
                source_score=0,
                collected_at="2026-07-27T08:00:00Z",
                body="正文",
            )

    def test_empty_body(self) -> None:
        """body 不能为空。"""
        with pytest.raises(ValidationError):
            HackerNewsRawItem(
                article_id="kb-20260727-0001",
                title="测试",
                source_url="https://example.com",
                source_score=0,
                collected_at="2026-07-27T08:00:00Z",
                body="",
            )


class TestDistributeResult:
    """DistributeResult 测试。"""

    def test_success_result(self) -> None:
        """成功分发结果。"""
        result = DistributeResult(
            article_id="kb-20260727-0001",
            channel="telegram",
            status="success",
            attempted_at="2026-07-27T10:00:00Z",
            published_at="2026-07-27T10:00:01Z",
        )
        assert result.status == "success"
        assert result.error is None

    def test_skipped_result(self) -> None:
        """跳过分发结果。"""
        result = DistributeResult(
            article_id="kb-20260727-0001",
            channel="feishu",
            status="skipped",
            attempted_at="2026-07-27T10:00:00Z",
        )
        assert result.published_at is None
        assert result.error is None

    def test_failed_result(self) -> None:
        """失败分发结果。"""
        result = DistributeResult(
            article_id="kb-20260727-0001",
            channel="telegram",
            status="failed",
            attempted_at="2026-07-27T10:00:00Z",
            error="Connection timeout",
        )
        assert result.published_at is None
        assert result.error == "Connection timeout"

    def test_invalid_channel(self) -> None:
        """无效渠道。"""
        with pytest.raises(ValidationError):
            DistributeResult(
                article_id="kb-20260727-0001",
                channel="slack",  # type: ignore[arg-type]
                status="success",
                attempted_at="2026-07-27T10:00:00Z",
            )

    def test_invalid_status(self) -> None:
        """无效状态。"""
        with pytest.raises(ValidationError):
            DistributeResult(
                article_id="kb-20260727-0001",
                channel="telegram",
                status="pending",  # type: ignore[arg-type]
                attempted_at="2026-07-27T10:00:00Z",
            )
