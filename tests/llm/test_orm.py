"""src.llm.orm 和 src.models.article 的单元测试。

测试覆盖：
- ORM 模型表名映射
- ORM 模型字段存在性
- Base 声明式基类
- BaseEntity 继承关系
"""

from __future__ import annotations

from sqlalchemy import inspect

from src.common.base_entity import Base, BaseEntity
from src.llm.orm import LlmCallLog, LlmHealth, LlmModel, LlmProvider
from src.models.article import Article  # noqa: F401 -- 注册到 Base.metadata
from src.models.enums import ArticleStatus


class TestLlmProvider:
    """LlmProvider ORM 模型测试。"""

    def test_tablename(self) -> None:
        """表名为 kb_llm_provider。"""
        assert LlmProvider.__tablename__ == "kb_llm_provider"

    def test_has_required_columns(self) -> None:
        """包含所有必要字段。"""
        mapper = inspect(LlmProvider)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "provider_code",
            "display_name",
            "provider_type",
            "base_url",
            "litellm_provider",
            "auth_type",
            "api_key_encrypted",
            "secret_key_encrypted",
            "header_name",
            "token_url",
            "is_enabled",
            "priority",
            "timeout_seconds",
            "max_retries",
            "rpm_limit",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        }
        assert required.issubset(column_names)

    def test_no_health_fields(self) -> None:
        """不再包含健康状态字段（已移至 LlmHealth）。"""
        mapper = inspect(LlmProvider)
        column_names = {c.key for c in mapper.columns}
        removed = {
            "health_status",
            "health_check_enabled",
            "last_check_at",
            "last_success_at",
            "last_failure_at",
            "consecutive_failures",
            "failure_threshold",
            "last_error",
            "auth_config",
        }
        assert not (removed & column_names)

    def test_inherits_base_entity(self) -> None:
        """继承 BaseEntity。"""
        assert issubclass(LlmProvider, BaseEntity)
        assert issubclass(LlmProvider, Base)


class TestLlmModel:
    """LlmModel ORM 模型测试。"""

    def test_tablename(self) -> None:
        """表名为 kb_llm_model。"""
        assert LlmModel.__tablename__ == "kb_llm_model"

    def test_has_required_columns(self) -> None:
        """包含所有必要字段。"""
        mapper = inspect(LlmModel)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "provider_id",
            "model_code",
            "litellm_model",
            "display_name",
            "description",
            "context_window",
            "max_output_tokens",
            "supports_streaming",
            "supports_function_calling",
            "supports_vision",
            "input_price_per_1m",
            "output_price_per_1m",
            "is_enabled",
            "is_default",
            "source",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        }
        assert required.issubset(column_names)

    def test_inherits_base_entity(self) -> None:
        """继承 BaseEntity。"""
        assert issubclass(LlmModel, BaseEntity)


class TestLlmHealth:
    """LlmHealth ORM 模型测试。"""

    def test_tablename(self) -> None:
        """表名为 kb_llm_health。"""
        assert LlmHealth.__tablename__ == "kb_llm_health"

    def test_has_required_columns(self) -> None:
        """包含所有必要字段。"""
        mapper = inspect(LlmHealth)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "provider_id",
            "model_id",
            "health_status",
            "consecutive_failures",
            "failure_threshold",
            "health_check_enabled",
            "last_check_at",
            "last_success_at",
            "last_failure_at",
            "last_latency_ms",
            "last_error",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        }
        assert required.issubset(column_names)

    def test_inherits_base_entity(self) -> None:
        """继承 BaseEntity（不再是纯追加日志表）。"""
        assert issubclass(LlmHealth, BaseEntity)
        assert issubclass(LlmHealth, Base)


class TestLlmCallLog:
    """LlmCallLog ORM 模型测试。"""

    def test_tablename(self) -> None:
        """表名为 kb_llm_call_log。"""
        assert LlmCallLog.__tablename__ == "kb_llm_call_log"

    def test_has_required_columns(self) -> None:
        """包含所有必要字段。"""
        mapper = inspect(LlmCallLog)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "trace_id",
            "provider_id",
            "model_id",
            "is_success",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
            "latency_ms",
            "error_msg",
            "called_at",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        }
        assert required.issubset(column_names)

    def test_inherits_base_not_base_entity(self) -> None:
        """继承 Base（纯追加日志表），不继承 BaseEntity。"""
        assert issubclass(LlmCallLog, Base)
        assert not issubclass(LlmCallLog, BaseEntity)


class TestArticle:
    """Article ORM 模型测试。"""

    def test_tablename(self) -> None:
        """表名为 kb_article。"""
        assert Article.__tablename__ == "kb_article"

    def test_has_required_columns(self) -> None:
        """包含所有必要字段。"""
        mapper = inspect(Article)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "article_id",
            "title",
            "source_url",
            "source_platform",
            "source_score",
            "summary",
            "content_path",
            "tags",
            "category",
            "status",
            "language",
            "collected_at",
            "analyzed_at",
            "published_at",
            "published_channels",
            "score",
            "score_reason",
            "highlights",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        }
        assert required.issubset(column_names)

    def test_inherits_base_entity(self) -> None:
        """继承 BaseEntity。"""
        assert issubclass(Article, BaseEntity)

    def test_default_status_pending(self) -> None:
        """默认状态为 PENDING。"""
        assert Article.status.default.arg is ArticleStatus.PENDING


class TestBase:
    """Base 声明式基类测试。"""

    def test_is_declarative_base(self) -> None:
        """Base 是 DeclarativeBase 子类。"""
        from sqlalchemy.orm import DeclarativeBase

        assert issubclass(Base, DeclarativeBase)

    def test_all_models_registered(self) -> None:
        """所有 ORM 模型已注册到 Base.metadata。"""
        table_names = set(Base.metadata.tables.keys())
        assert "kb_llm_provider" in table_names
        assert "kb_llm_model" in table_names
        assert "kb_llm_health" in table_names
        assert "kb_llm_call_log" in table_names
        assert "kb_article" in table_names


class TestBaseEntity:
    """BaseEntity 通用基类测试。"""

    def test_is_abstract(self) -> None:
        """BaseEntity 是抽象基类，不映射到具体表。"""
        assert BaseEntity.__abstract__ is True

    def test_has_common_fields(self) -> None:
        """BaseEntity 定义了通用字段（通过子类检查）。"""
        # BaseEntity 是抽象类，无法直接 inspect，通过子类检查
        provider_cols = {c.key for c in inspect(LlmProvider).columns}
        common = {"id", "created_at", "updated_at", "is_deleted", "deleted_at"}
        assert common.issubset(provider_cols)

    def test_providers_share_base_entity_fields(self) -> None:
        """LlmProvider 和 Article 共享 BaseEntity 的通用字段。"""
        provider_cols = {c.key for c in inspect(LlmProvider).columns}
        article_cols = {c.key for c in inspect(Article).columns}
        common = {"id", "created_at", "updated_at", "is_deleted", "deleted_at"}
        assert common.issubset(provider_cols)
        assert common.issubset(article_cols)
