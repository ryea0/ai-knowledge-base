"""src.models.enums 的单元测试。

测试覆盖：
- ArticleStatus 枚举值与 JSON 字符串互转
- Category 枚举值与 JSON 字符串互转
- SourcePlatform 枚举值与 JSON 字符串互转
- LLM 供应商相关枚举互转
- from_json_str 无效值抛 ValueError
"""

from __future__ import annotations

import pytest

from src.models.enums import (
    ArticleStatus,
    Category,
    LlmAuthType,
    LlmHealthStatus,
    LlmModelSource,
    LlmProviderType,
    SourcePlatform,
)


class TestArticleStatus:
    """ArticleStatus 枚举测试。"""

    def test_enum_values(self) -> None:
        """枚举整数值与 §6.6 映射表一致。"""
        assert ArticleStatus.PENDING == 0
        assert ArticleStatus.REVIEWED == 1
        assert ArticleStatus.PUBLISHED == 2
        assert ArticleStatus.ARCHIVED == 3

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ArticleStatus.PENDING, "pending"),
            (ArticleStatus.REVIEWED, "reviewed"),
            (ArticleStatus.PUBLISHED, "published"),
            (ArticleStatus.ARCHIVED, "archived"),
        ],
    )
    def test_to_json_str(self, status: ArticleStatus, expected: str) -> None:
        """to_json_str 返回小写字符串名。"""
        assert status.to_json_str() == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("pending", ArticleStatus.PENDING),
            ("reviewed", ArticleStatus.REVIEWED),
            ("published", ArticleStatus.PUBLISHED),
            ("archived", ArticleStatus.ARCHIVED),
        ],
    )
    def test_from_json_str(self, value: str, expected: ArticleStatus) -> None:
        """from_json_str 正确解析。"""
        assert ArticleStatus.from_json_str(value) == expected

    def test_from_json_str_case_insensitive(self) -> None:
        """from_json_str 不区分大小写。"""
        assert ArticleStatus.from_json_str("PENDING") == ArticleStatus.PENDING
        assert ArticleStatus.from_json_str("Published") == ArticleStatus.PUBLISHED

    def test_from_json_str_invalid(self) -> None:
        """无效字符串抛 ValueError。"""
        with pytest.raises(ValueError, match="无效的状态字符串"):
            ArticleStatus.from_json_str("invalid")

    def test_from_json_str_error_message_lists_valid_values(self) -> None:
        """错误消息包含合法值列表。"""
        with pytest.raises(ValueError, match="pending"):
            ArticleStatus.from_json_str("bad")


class TestCategory:
    """Category 枚举测试。"""

    def test_enum_values(self) -> None:
        """枚举整数值正确。"""
        assert Category.MODEL_RELEASE == 0
        assert Category.PAPER == 1
        assert Category.TOOL == 2
        assert Category.TUTORIAL == 3
        assert Category.NEWS == 4

    @pytest.mark.parametrize(
        ("cat", "expected"),
        [
            (Category.MODEL_RELEASE, "model_release"),
            (Category.PAPER, "paper"),
            (Category.TOOL, "tool"),
            (Category.TUTORIAL, "tutorial"),
            (Category.NEWS, "news"),
        ],
    )
    def test_to_json_str(self, cat: Category, expected: str) -> None:
        """to_json_str 返回小写字符串名。"""
        assert cat.to_json_str() == expected

    def test_from_json_str(self) -> None:
        """from_json_str 正确解析。"""
        assert Category.from_json_str("tool") == Category.TOOL
        assert Category.from_json_str("MODEL_RELEASE") == Category.MODEL_RELEASE

    def test_from_json_str_invalid(self) -> None:
        """无效字符串抛 ValueError。"""
        with pytest.raises(ValueError, match="无效的分类字符串"):
            Category.from_json_str("nonexistent")


class TestSourcePlatform:
    """SourcePlatform 枚举测试。"""

    def test_enum_values(self) -> None:
        """枚举整数值正确。"""
        assert SourcePlatform.GITHUB_TRENDING == 0
        assert SourcePlatform.HACKERNEWS == 1

    def test_to_json_str(self) -> None:
        """to_json_str 返回小写字符串名。"""
        assert SourcePlatform.GITHUB_TRENDING.to_json_str() == "github_trending"
        assert SourcePlatform.HACKERNEWS.to_json_str() == "hackernews"

    def test_from_json_str(self) -> None:
        """from_json_str 正确解析。"""
        assert SourcePlatform.from_json_str("github_trending") == SourcePlatform.GITHUB_TRENDING
        assert SourcePlatform.from_json_str("HACKERNEWS") == SourcePlatform.HACKERNEWS

    def test_from_json_str_invalid(self) -> None:
        """无效字符串抛 ValueError。"""
        with pytest.raises(ValueError, match="无效的平台字符串"):
            SourcePlatform.from_json_str("reddit")


class TestLlmProviderType:
    """LlmProviderType 枚举测试。"""

    def test_enum_values(self) -> None:
        assert LlmProviderType.CLOUD == 0
        assert LlmProviderType.LOCAL == 1

    def test_to_json_str(self) -> None:
        assert LlmProviderType.CLOUD.to_json_str() == "cloud"
        assert LlmProviderType.LOCAL.to_json_str() == "local"

    def test_from_json_str(self) -> None:
        assert LlmProviderType.from_json_str("cloud") == LlmProviderType.CLOUD
        assert LlmProviderType.from_json_str("LOCAL") == LlmProviderType.LOCAL

    def test_from_json_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="无效的供应商类型字符串"):
            LlmProviderType.from_json_str("hybrid")


class TestLlmAuthType:
    """LlmAuthType 枚举测试。"""

    def test_enum_values(self) -> None:
        assert LlmAuthType.BEARER == 0
        assert LlmAuthType.OAUTH == 1
        assert LlmAuthType.HEADER == 2
        assert LlmAuthType.NONE == 3

    def test_to_json_str(self) -> None:
        assert LlmAuthType.BEARER.to_json_str() == "bearer"
        assert LlmAuthType.OAUTH.to_json_str() == "oauth"
        assert LlmAuthType.HEADER.to_json_str() == "header"
        assert LlmAuthType.NONE.to_json_str() == "none"

    def test_from_json_str(self) -> None:
        assert LlmAuthType.from_json_str("bearer") == LlmAuthType.BEARER
        assert LlmAuthType.from_json_str("OAUTH") == LlmAuthType.OAUTH
        assert LlmAuthType.from_json_str("Header") == LlmAuthType.HEADER
        assert LlmAuthType.from_json_str("none") == LlmAuthType.NONE

    def test_from_json_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="无效的鉴权类型字符串"):
            LlmAuthType.from_json_str("basic")


class TestLlmHealthStatus:
    """LlmHealthStatus 枚举测试。"""

    def test_enum_values(self) -> None:
        assert LlmHealthStatus.HEALTHY == 0
        assert LlmHealthStatus.DEGRADED == 1
        assert LlmHealthStatus.UNHEALTHY == 2
        assert LlmHealthStatus.UNKNOWN == 3

    def test_to_json_str(self) -> None:
        assert LlmHealthStatus.HEALTHY.to_json_str() == "healthy"
        assert LlmHealthStatus.DEGRADED.to_json_str() == "degraded"
        assert LlmHealthStatus.UNHEALTHY.to_json_str() == "unhealthy"
        assert LlmHealthStatus.UNKNOWN.to_json_str() == "unknown"

    def test_from_json_str(self) -> None:
        assert LlmHealthStatus.from_json_str("healthy") == LlmHealthStatus.HEALTHY
        assert LlmHealthStatus.from_json_str("UNHEALTHY") == LlmHealthStatus.UNHEALTHY

    def test_from_json_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="无效的健康状态字符串"):
            LlmHealthStatus.from_json_str("broken")


class TestLlmModelSource:
    """LlmModelSource 枚举测试。"""

    def test_enum_values(self) -> None:
        assert LlmModelSource.PRESET == 0
        assert LlmModelSource.DISCOVERED == 1
        assert LlmModelSource.MANUAL == 2

    def test_to_json_str(self) -> None:
        assert LlmModelSource.PRESET.to_json_str() == "preset"
        assert LlmModelSource.DISCOVERED.to_json_str() == "discovered"
        assert LlmModelSource.MANUAL.to_json_str() == "manual"

    def test_from_json_str(self) -> None:
        assert LlmModelSource.from_json_str("preset") == LlmModelSource.PRESET
        assert LlmModelSource.from_json_str("MANUAL") == LlmModelSource.MANUAL

    def test_from_json_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="无效的模型来源字符串"):
            LlmModelSource.from_json_str("auto")
