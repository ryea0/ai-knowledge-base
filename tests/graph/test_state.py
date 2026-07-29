"""KBState 工作流状态定义的单元测试。

测试覆盖：
- KBState 可用部分字段创建（TypedDict total=False）
- KBState 包含全部字段
- 各字段的类型与默认值符合设计
- "报告式通信"原则：字段存储结构化摘要而非原始数据
- trace_id / errors 新增字段
"""

from __future__ import annotations

from src.graph.state import KBState


class TestKBStateCreation:
    """KBState 创建与字段测试。"""

    def test_can_create_empty(self) -> None:
        """KBState 可以创建空状态（total=False）。"""
        state: KBState = {}
        assert state == {}

    def test_can_create_partial(self) -> None:
        """KBState 可以只设置部分字段。"""
        state: KBState = {"iteration": 1, "review_passed": False}
        assert state["iteration"] == 1
        assert state["review_passed"] is False

    def test_all_fields(self) -> None:
        """KBState 可以包含全部字段且类型正确。"""
        state: KBState = {
            "trace_id": "a1b2c3d4",
            "sources": [
                {
                    "title": "Test Project",
                    "url": "https://github.com/test/repo",
                    "source_platform": "github_trending",
                    "source_score": 100,
                    "summary": "A test project",
                    "content_path": "knowledge/raw/kb-20260730-0001.md",
                },
            ],
            "analyses": [
                {
                    "title": "测试项目分析",
                    "summary": "这是一个测试项目的分析摘要",
                    "highlights": ["亮点1", "亮点2"],
                    "score": 8,
                    "tags": ["llm", "agent"],
                    "category": "tool",
                    "language": "en",
                },
            ],
            "articles": [
                {
                    "article_id": "kb-20260730-0001",
                    "title": "测试项目",
                    "source_url": "https://github.com/test/repo",
                    "source_platform": "github_trending",
                    "summary": "中文摘要",
                    "content_path": "knowledge/raw/kb-20260730-0001.md",
                    "tags": ["llm", "agent"],
                    "category": "tool",
                    "status": "pending",
                },
            ],
            "review_feedback": "摘要深度不足，请补充技术细节",
            "review_passed": False,
            "iteration": 2,
            "cost_tracker": {
                "collect": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "analyze": {
                    "prompt_tokens": 1234,
                    "completion_tokens": 567,
                    "total_tokens": 1801,
                },
            },
            "errors": [],
        }

        assert state["trace_id"] == "a1b2c3d4"
        assert len(state["sources"]) == 1
        assert state["sources"][0]["source_platform"] == "github_trending"
        assert len(state["analyses"]) == 1
        assert state["analyses"][0]["score"] == 8
        assert len(state["articles"]) == 1
        assert state["articles"][0]["status"] == "pending"
        assert state["review_feedback"] == "摘要深度不足，请补充技术细节"
        assert state["review_passed"] is False
        assert state["iteration"] == 2
        assert state["cost_tracker"]["analyze"]["prompt_tokens"] == 1234
        assert state["cost_tracker"]["analyze"]["total_tokens"] == 1801


class TestReportStyleCommunication:
    """报告式通信原则：字段存储结构化摘要而非原始数据。"""

    def test_sources_is_summary_not_raw_html(self) -> None:
        """sources 存储结构化摘要，而非原始 HTML。"""
        state: KBState = {
            "sources": [
                {
                    "title": "项目标题",
                    "url": "https://example.com",
                    "source_platform": "hackernews",
                    "source_score": 50,
                    "summary": "摘要文本",
                    "content_path": "knowledge/raw/kb-20260730-0001.md",
                },
            ],
        }
        source = state["sources"][0]
        assert "title" in source
        assert "url" in source
        assert "summary" in source
        assert "<html>" not in str(source)

    def test_analyses_is_structured_not_raw_llm_output(self) -> None:
        """analyses 存储结构化字段，而非 LLM 原始文本输出。"""
        state: KBState = {
            "analyses": [
                {
                    "title": "标题",
                    "summary": "摘要",
                    "highlights": ["h1"],
                    "score": 7,
                    "tags": ["tag"],
                    "category": "paper",
                    "language": "zh",
                },
            ],
        }
        analysis = state["analyses"][0]
        assert isinstance(analysis["tags"], list)
        assert isinstance(analysis["highlights"], list)
        assert isinstance(analysis["score"], int)
        assert isinstance(analysis["summary"], str)

    def test_articles_follows_article_format(self) -> None:
        """articles 中每个条目包含 article-format.md 要求的核心字段。"""
        state: KBState = {
            "articles": [
                {
                    "article_id": "kb-20260730-0001",
                    "title": "标题",
                    "source_url": "https://example.com",
                    "source_platform": "github_trending",
                    "summary": "摘要",
                    "content_path": "knowledge/raw/kb-20260730-0001.md",
                    "tags": ["tag"],
                    "category": "tool",
                    "status": "pending",
                },
            ],
        }
        article = state["articles"][0]
        required_keys = {
            "article_id",
            "title",
            "source_url",
            "source_platform",
            "summary",
            "content_path",
            "tags",
            "category",
            "status",
        }
        assert required_keys.issubset(article.keys())


class TestReviewLoopFields:
    """审核循环相关字段测试。"""

    def test_initial_state_no_feedback(self) -> None:
        """初始状态审核反馈为空/未设置。"""
        state: KBState = {"iteration": 1, "review_passed": False}
        assert "review_feedback" not in state or state["review_feedback"] == ""

    def test_feedback_after_failed_review(self) -> None:
        """审核不通过后，feedback 包含具体改进建议。"""
        state: KBState = {
            "review_feedback": "摘要过短，需补充技术细节；缺少与同类工具的对比",
            "review_passed": False,
            "iteration": 1,
        }
        assert state["review_passed"] is False
        assert len(state["review_feedback"]) > 0

    def test_passed_after_successful_review(self) -> None:
        """审核通过后，review_passed 为 True，feedback 为空。"""
        state: KBState = {
            "review_feedback": "",
            "review_passed": True,
            "iteration": 2,
        }
        assert state["review_passed"] is True

    def test_iteration_max_is_three(self) -> None:
        """iteration 最大值为 3（设计约束，非运行时强制）。"""
        state: KBState = {"iteration": 3, "review_passed": False}
        assert state["iteration"] <= 3


class TestCostTracker:
    """cost_tracker 字段测试。"""

    def test_cost_tracker_structure(self) -> None:
        """cost_tracker 按节点名分组，每组包含 token 用量。"""
        state: KBState = {
            "cost_tracker": {
                "analyze": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                },
                "review": {
                    "prompt_tokens": 800,
                    "completion_tokens": 20,
                    "total_tokens": 820,
                },
            },
        }
        assert "analyze" in state["cost_tracker"]
        assert "review" in state["cost_tracker"]
        assert state["cost_tracker"]["analyze"]["prompt_tokens"] == 1000
        assert state["cost_tracker"]["analyze"]["total_tokens"] == 1500

    def test_cost_tracker_empty_initial(self) -> None:
        """初始状态 cost_tracker 为空或未设置。"""
        state: KBState = {}
        assert "cost_tracker" not in state or state["cost_tracker"] == {}


class TestNewFields:
    """新增字段测试。"""

    def test_trace_id_field(self) -> None:
        """trace_id 字段可以设置和读取。"""
        state: KBState = {"trace_id": "abc12345"}
        assert state["trace_id"] == "abc12345"

    def test_errors_field(self) -> None:
        """errors 字段可以存储错误列表。"""
        state: KBState = {
            "errors": [
                {
                    "node": "collect",
                    "error": "network timeout",
                    "timestamp": "2026-07-30T10:00:00+00:00",
                },
            ],
        }
        assert len(state["errors"]) == 1
        assert state["errors"][0]["node"] == "collect"

    def test_errors_empty_initial(self) -> None:
        """初始状态 errors 未设置或为空。"""
        state: KBState = {}
        assert "errors" not in state or state["errors"] == []
