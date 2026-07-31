"""src.bot.knowledge_bot 的单元测试。

测试覆盖：
- recognize_intent: 命令前缀 + 自然语言 + 边界情况
- KnowledgeSearchEngine: 关键词/标签/日期过滤、today、top
- SubscriptionManager: 订阅/取消/列表
- PermissionManager: 权限检查/授予/撤销/级别包含
- KnowledgeBot.handle_message: 端到端消息处理 + 权限拦截
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.bot.knowledge_bot import (
    BotIntent,
    KnowledgeBot,
    KnowledgeSearchEngine,
    PermissionLevel,
    PermissionManager,
    SubscriptionManager,
)

# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

_SAMPLE_ARTICLES = [
    {
        "article_id": "kb-20260730-0001",
        "title": "OpenAI 发布 GPT-5",
        "source_url": "https://example.com/gpt5",
        "source_platform": "github_trending",
        "source_score": 900,
        "summary": "GPT-5 支持原生多模态推理",
        "content_path": "knowledge/raw/kb-20260730-0001.md",
        "tags": ["llm", "openai", "multimodal"],
        "category": "model_release",
        "status": "pending",
        "language": "zh",
        "collected_at": "2026-07-30T08:00:00Z",
        "analyzed_at": "2026-07-30T08:05:00Z",
        "published_at": None,
        "published_channels": None,
        "score": 9,
    },
    {
        "article_id": "kb-20260730-0002",
        "title": "LangChain Agent 框架解析",
        "source_url": "https://example.com/langchain",
        "source_platform": "hackernews",
        "source_score": 500,
        "summary": "LangChain 提供了一套完整的 Agent 工作流",
        "content_path": "knowledge/raw/kb-20260730-0002.md",
        "tags": ["agent", "framework"],
        "category": "tool",
        "status": "reviewed",
        "language": "zh",
        "collected_at": "2026-07-30T10:00:00Z",
        "analyzed_at": "2026-07-30T10:05:00Z",
        "published_at": None,
        "published_channels": None,
        "score": 7,
    },
    {
        "article_id": "kb-20260729-0003",
        "title": "LLM 推理优化技术综述",
        "source_url": "https://example.com/llm-opt",
        "source_platform": "github_trending",
        "source_score": 1200,
        "summary": "本文综述了 LLM 推理加速的主要技术方向",
        "content_path": "knowledge/raw/kb-20260729-0003.md",
        "tags": ["llm", "inference", "optimization"],
        "category": "paper",
        "status": "published",
        "language": "zh",
        "collected_at": "2026-07-29T12:00:00Z",
        "analyzed_at": "2026-07-29T12:10:00Z",
        "published_at": None,
        "published_channels": None,
        "score": 8,
    },
]


def _write_sample_articles(tmp_path: Path) -> Path:
    """将样例条目写入临时目录，返回目录路径。"""
    for article in _SAMPLE_ARTICLES:
        filename = f"{article['article_id']}.json"
        with open(tmp_path / filename, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False)
    return tmp_path


# ---------------------------------------------------------------------------
# recognize_intent 测试
# ---------------------------------------------------------------------------


class TestRecognizeIntent:
    """KnowledgeBot.recognize_intent 意图识别测试。"""

    @pytest.mark.parametrize(
        ("text", "expected_intent", "expected_params"),
        [
            ("/search LLM", BotIntent.SEARCH, "LLM"),
            ("/search", BotIntent.SEARCH, ""),
            ("/today", BotIntent.TODAY, ""),
            ("/top 10", BotIntent.TOP, "10"),
            ("/subscribe tag:llm", BotIntent.SUBSCRIBE, "tag:llm"),
            ("/help", BotIntent.HELP, ""),
        ],
    )
    def test_command_prefix(
        self, text: str, expected_intent: BotIntent, expected_params: str
    ) -> None:
        """命令前缀正确匹配意图与参数。"""
        intent, params = KnowledgeBot.recognize_intent(text)
        assert intent == expected_intent
        assert params == expected_params

    @pytest.mark.parametrize(
        ("text", "expected_intent"),
        [
            ("搜索 LLM", BotIntent.SEARCH),
            ("查询 agent", BotIntent.SEARCH),
            ("今天有什么", BotIntent.TODAY),
            ("今日简报", BotIntent.TOP),
            ("热门文章", BotIntent.TOP),
            ("订阅 tag:llm", BotIntent.SUBSCRIBE),
            ("帮助", BotIntent.HELP),
            ("help", BotIntent.HELP),
        ],
    )
    def test_natural_language(self, text: str, expected_intent: BotIntent) -> None:
        """自然语言关键词正确匹配意图。"""
        intent, _ = KnowledgeBot.recognize_intent(text)
        assert intent == expected_intent

    def test_empty_text(self) -> None:
        """空文本返回 UNKNOWN。"""
        assert KnowledgeBot.recognize_intent("")[0] == BotIntent.UNKNOWN
        assert KnowledgeBot.recognize_intent("   ")[0] == BotIntent.UNKNOWN

    def test_unknown_text(self) -> None:
        """无法识别的文本返回 UNKNOWN。"""
        intent, params = KnowledgeBot.recognize_intent("xyzrandom")
        assert intent == BotIntent.UNKNOWN
        assert params == "xyzrandom"

    def test_command_takes_priority_over_nl(self) -> None:
        """命令前缀优先于自然语言。"""
        # "/search 今天" 应该匹配 /search 而非"今天"
        intent, params = KnowledgeBot.recognize_intent("/search 今天有什么")
        assert intent == BotIntent.SEARCH
        assert params == "今天有什么"


# ---------------------------------------------------------------------------
# PermissionLevel 测试
# ---------------------------------------------------------------------------


class TestPermissionLevel:
    """PermissionLevel 枚举测试。"""

    @pytest.mark.parametrize(
        ("level", "other", "expected"),
        [
            (PermissionLevel.READ, PermissionLevel.READ, True),
            (PermissionLevel.WRITE, PermissionLevel.READ, True),
            (PermissionLevel.DELETE, PermissionLevel.READ, True),
            (PermissionLevel.DELETE, PermissionLevel.WRITE, True),
            (PermissionLevel.READ, PermissionLevel.WRITE, False),
            (PermissionLevel.READ, PermissionLevel.DELETE, False),
            (PermissionLevel.WRITE, PermissionLevel.DELETE, False),
        ],
    )
    def test_includes(
        self, level: PermissionLevel, other: PermissionLevel, expected: bool
    ) -> None:
        """权限级别包含关系正确。"""
        assert level.includes(other) == expected


# ---------------------------------------------------------------------------
# PermissionManager 测试
# ---------------------------------------------------------------------------


class TestPermissionManager:
    """PermissionManager 权限管理测试。"""

    def test_default_permission_is_read(self) -> None:
        """未注册用户默认 READ 权限。"""
        pm = PermissionManager()
        assert pm.get_level("user1") == PermissionLevel.READ
        assert pm.check_permission("user1", PermissionLevel.READ) is True
        assert pm.check_permission("user1", PermissionLevel.WRITE) is False

    def test_grant_write(self) -> None:
        """授予 WRITE 权限后包含 READ。"""
        pm = PermissionManager()
        pm.grant("user1", PermissionLevel.WRITE)
        assert pm.check_permission("user1", PermissionLevel.READ) is True
        assert pm.check_permission("user1", PermissionLevel.WRITE) is True
        assert pm.check_permission("user1", PermissionLevel.DELETE) is False

    def test_grant_keeps_higher_level(self) -> None:
        """授予低级别不降低已有高级别。"""
        pm = PermissionManager()
        pm.grant("user1", PermissionLevel.DELETE)
        pm.grant("user1", PermissionLevel.READ)
        assert pm.get_level("user1") == PermissionLevel.DELETE

    def test_revoke(self) -> None:
        """撤销权限后恢复 READ。"""
        pm = PermissionManager()
        pm.grant("user1", PermissionLevel.WRITE)
        pm.revoke("user1")
        assert pm.get_level("user1") == PermissionLevel.READ

    def test_revoke_nonexistent_user(self) -> None:
        """撤销未注册用户不报错。"""
        pm = PermissionManager()
        pm.revoke("nobody")


# ---------------------------------------------------------------------------
# SubscriptionManager 测试
# ---------------------------------------------------------------------------


class TestSubscriptionManager:
    """SubscriptionManager 订阅管理测试。"""

    def test_subscribe_creates_record(self) -> None:
        """创建订阅返回包含 sub_id 的记录。"""
        sm = SubscriptionManager()
        sub = sm.subscribe("user1", tags=["llm"], keywords=["GPT"])
        assert sub["sub_id"].startswith("sub-")
        assert sub["user_id"] == "user1"
        assert sub["tags"] == ["llm"]
        assert sub["keywords"] == ["GPT"]
        assert "created_at" in sub

    def test_subscribe_increments_id(self) -> None:
        """多次订阅 sub_id 递增。"""
        sm = SubscriptionManager()
        sub1 = sm.subscribe("user1", tags=["a"])
        sub2 = sm.subscribe("user1", tags=["b"])
        assert sub1["sub_id"] != sub2["sub_id"]

    def test_subscribe_requires_tags_or_keywords(self) -> None:
        """tags 和 keywords 同时为空时抛 ValueError。"""
        sm = SubscriptionManager()
        with pytest.raises(ValueError, match="至少指定"):
            sm.subscribe("user1")
        with pytest.raises(ValueError, match="至少指定"):
            sm.subscribe("user1", tags=[], keywords=[])

    def test_unsubscribe_success(self) -> None:
        """取消存在的订阅返回 True。"""
        sm = SubscriptionManager()
        sub = sm.subscribe("user1", tags=["llm"])
        assert sm.unsubscribe("user1", sub["sub_id"]) is True
        assert sm.list_subscriptions("user1") == []

    def test_unsubscribe_nonexistent(self) -> None:
        """取消不存在的订阅返回 False。"""
        sm = SubscriptionManager()
        assert sm.unsubscribe("user1", "sub-999") is False

    def test_list_subscriptions(self) -> None:
        """列出用户所有订阅。"""
        sm = SubscriptionManager()
        sm.subscribe("user1", tags=["a"])
        sm.subscribe("user1", tags=["b"])
        sm.subscribe("user2", tags=["c"])
        assert len(sm.list_subscriptions("user1")) == 2
        assert len(sm.list_subscriptions("user2")) == 1
        assert sm.list_subscriptions("nobody") == []


# ---------------------------------------------------------------------------
# KnowledgeSearchEngine 测试
# ---------------------------------------------------------------------------


class TestKnowledgeSearchEngine:
    """KnowledgeSearchEngine 搜索引擎测试。"""

    def test_search_by_keyword_title(self, tmp_path: Path) -> None:
        """关键词匹配标题。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="GPT-5")
        assert len(results) == 1
        assert "GPT-5" in results[0]["title"]

    def test_search_by_keyword_summary(self, tmp_path: Path) -> None:
        """关键词匹配摘要。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="推理加速")
        assert len(results) == 1
        assert "推理加速" in results[0]["summary"]

    def test_search_case_insensitive(self, tmp_path: Path) -> None:
        """关键词搜索不区分大小写。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="gpt")
        assert len(results) == 1
        assert "GPT-5" in results[0]["title"]

    def test_search_by_tags(self, tmp_path: Path) -> None:
        """标签过滤（OR 语义）。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(tags=["agent"])
        assert len(results) == 1
        assert "agent" in results[0]["tags"]

    def test_search_by_tags_multiple(self, tmp_path: Path) -> None:
        """多标签 OR 匹配。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(tags=["agent", "openai"])
        assert len(results) == 2

    def test_search_by_date_range(self, tmp_path: Path) -> None:
        """日期范围过滤。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        start = datetime(2026, 7, 30, tzinfo=UTC)
        results = engine.search(date_start=start)
        assert len(results) == 2
        for r in results:
            assert r["collected_at"].startswith("2026-07-30")

    def test_search_combined_filters(self, tmp_path: Path) -> None:
        """关键词 + 标签组合过滤（AND 语义）。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="GPT", tags=["openai"])
        assert len(results) == 1
        results = engine.search(keyword="GPT", tags=["agent"])
        assert len(results) == 0

    def test_search_limit(self, tmp_path: Path) -> None:
        """limit 限制返回条数。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="LLM", limit=1)
        assert len(results) == 1

    def test_search_empty_dir(self, tmp_path: Path) -> None:
        """空目录返回空列表。"""
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.search(keyword="test")
        assert results == []

    def test_search_nonexistent_dir(self) -> None:
        """不存在的目录返回空列表。"""
        engine = KnowledgeSearchEngine("/nonexistent/path")
        results = engine.search(keyword="test")
        assert results == []

    def test_get_today(self, tmp_path: Path) -> None:
        """get_today 返回当天条目。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # 写一篇今天日期的条目
        today_article = {
            "article_id": "kb-today-0001",
            "title": "Today Article",
            "source_url": "https://example.com/today",
            "source_platform": "github_trending",
            "source_score": 100,
            "summary": "Today's content about LLM",
            "content_path": "knowledge/raw/today.md",
            "tags": ["llm"],
            "category": "news",
            "status": "pending",
            "language": "zh",
            "collected_at": f"{today}T08:00:00Z",
            "analyzed_at": None,
            "published_at": None,
            "published_channels": None,
            "score": 6,
        }
        with open(tmp_path / "kb-today-0001.json", "w", encoding="utf-8") as f:
            json.dump(today_article, f)

        results = engine.get_today()
        assert len(results) >= 1
        assert any(r["title"] == "Today Article" for r in results)

    def test_get_top(self, tmp_path: Path) -> None:
        """get_top 按评分降序返回。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.get_top(n=3)
        assert len(results) == 3
        assert results[0]["score"] >= results[1]["score"]
        assert results[1]["score"] >= results[2]["score"]
        assert results[0]["score"] == 9

    def test_get_top_with_date(self, tmp_path: Path) -> None:
        """get_top 按日期过滤。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        results = engine.get_top(n=10, date="2026-07-29")
        assert len(results) == 1
        assert results[0]["article_id"] == "kb-20260729-0003"


# ---------------------------------------------------------------------------
# KnowledgeBot.handle_message 端到端测试
# ---------------------------------------------------------------------------


class TestKnowledgeBotHandleMessage:
    """KnowledgeBot.handle_message 端到端测试。"""

    @pytest.fixture
    def bot_with_data(self, tmp_path: Path) -> KnowledgeBot:
        """创建带样例数据的 Bot 实例。"""
        _write_sample_articles(tmp_path)
        engine = KnowledgeSearchEngine(str(tmp_path))
        return KnowledgeBot(
            search_engine=engine,
            subscription_manager=SubscriptionManager(),
            permission_manager=PermissionManager(),
        )

    def test_handle_search(self, bot_with_data: KnowledgeBot) -> None:
        """搜索命令返回结果。"""
        resp = bot_with_data.handle_message("user1", "/search GPT")
        assert "GPT" in resp
        assert "搜索" in resp

    def test_handle_search_no_keyword(self, bot_with_data: KnowledgeBot) -> None:
        """搜索无关键词时提示用法。"""
        resp = bot_with_data.handle_message("user1", "/search")
        assert "关键词" in resp

    def test_handle_search_no_results(self, bot_with_data: KnowledgeBot) -> None:
        """搜索无结果时提示未找到。"""
        resp = bot_with_data.handle_message("user1", "/search xyznonexistent")
        assert "未找到" in resp

    def test_handle_today(self, bot_with_data: KnowledgeBot) -> None:
        """today 命令返回当日条目。"""
        resp = bot_with_data.handle_message("user1", "/today")
        # 样例数据日期是 2026-07-30，可能非今日
        assert "新增" in resp or "暂无" in resp

    def test_handle_top(self, bot_with_data: KnowledgeBot) -> None:
        """top 命令返回热门条目。"""
        resp = bot_with_data.handle_message("user1", "/top 2")
        assert "热门" in resp
        assert "GPT-5" in resp  # score=9 排第一

    def test_handle_help(self, bot_with_data: KnowledgeBot) -> None:
        """help 命令返回帮助信息。"""
        resp = bot_with_data.handle_message("user1", "/help")
        assert "知识库 Bot" in resp
        assert "/search" in resp
        assert "/subscribe" in resp

    def test_handle_unknown_falls_back_to_help(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """未知意图回退到 help。"""
        resp = bot_with_data.handle_message("user1", "xyzrandom")
        assert "知识库 Bot" in resp

    def test_handle_natural_language_search(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """自然语言搜索正常工作。"""
        resp = bot_with_data.handle_message("user1", "搜索 GPT")
        assert "GPT" in resp

    # -- 权限控制测试 -------------------------------------------------------

    def test_subscribe_requires_write_permission(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """默认 READ 用户无法订阅，返回权限不足提示。"""
        resp = bot_with_data.handle_message("user1", "/subscribe tag:llm")
        assert "权限不足" in resp

    def test_subscribe_with_write_permission(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """WRITE 权限用户可以订阅。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        resp = bot_with_data.handle_message("admin1", "/subscribe tag:llm")
        assert "订阅成功" in resp

    def test_subscribe_list_with_write_permission(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """WRITE 权限用户可以查看订阅列表。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        bot_with_data.handle_message("admin1", "/subscribe tag:llm")
        resp = bot_with_data.handle_message("admin1", "/subscribe list")
        assert "订阅" in resp
        assert "llm" in resp

    def test_subscribe_unsubscribe_with_write_permission(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """WRITE 权限用户可以取消订阅。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        bot_with_data.handle_message("admin1", "/subscribe tag:llm")
        resp = bot_with_data.handle_message("admin1", "/subscribe list")
        # 提取 sub_id
        for line in resp.split("\n"):
            if "sub-" in line:
                start = line.find("sub-")
                sub_id = line[start:start + 7]
                break
        cancel_resp = bot_with_data.handle_message(
            "admin1", f"/subscribe remove {sub_id}"
        )
        assert "已取消" in cancel_resp

    def test_search_allowed_with_read_permission(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """READ 权限用户可以搜索。"""
        resp = bot_with_data.handle_message("readonly", "/search GPT")
        assert "GPT" in resp

    def test_delete_permission_includes_write(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """DELETE 权限用户可以订阅（包含 WRITE）。"""
        bot_with_data._permission.grant("root", PermissionLevel.DELETE)
        resp = bot_with_data.handle_message("root", "/subscribe tag:llm")
        assert "订阅成功" in resp

    # -- subscribe 参数解析测试 ---------------------------------------------

    def test_subscribe_keyword_only(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """仅关键词订阅成功。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        resp = bot_with_data.handle_message("admin1", "/subscribe keyword:agent")
        assert "订阅成功" in resp
        assert "agent" in resp

    def test_subscribe_both_tag_and_keyword(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """同时指定标签和关键词订阅成功。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        resp = bot_with_data.handle_message(
            "admin1", "/subscribe tag:llm keyword:GPT"
        )
        assert "订阅成功" in resp
        assert "llm" in resp
        assert "GPT" in resp

    def test_subscribe_remove_nonexistent(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """取消不存在的订阅返回提示。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        resp = bot_with_data.handle_message(
            "admin1", "/subscribe remove sub-999"
        )
        assert "不存在" in resp

    def test_subscribe_empty_list(
        self, bot_with_data: KnowledgeBot
    ) -> None:
        """无订阅时列出返回提示。"""
        bot_with_data._permission.grant("admin1", PermissionLevel.WRITE)
        resp = bot_with_data.handle_message("admin1", "/subscribe list")
        assert "无订阅" in resp
