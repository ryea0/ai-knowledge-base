"""src.pipeline.pipeline 的单元测试。

测试覆盖：
- Pipeline.run 完整流程
- 干跑模式
- 采集源选择
- 错误处理
- CLI 参数解析
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.pipeline import Pipeline, PipelineStats, parse_args, run_pipeline


class TestParseArgs:
    """CLI 参数解析测试。"""

    def test_default_args(self) -> None:
        """默认参数。"""
        args = parse_args([])
        assert args.sources == "github,rss"
        assert args.limit == 20
        assert not args.dry_run
        assert not args.verbose

    def test_sources_arg(self) -> None:
        """--sources 参数。"""
        args = parse_args(["--sources", "github"])
        assert args.sources == "github"

    def test_limit_arg(self) -> None:
        """--limit 参数。"""
        args = parse_args(["--sources", "rss", "--limit", "5"])
        assert args.limit == 5

    def test_dry_run_flag(self) -> None:
        """--dry-run 标志。"""
        args = parse_args(["--dry-run"])
        assert args.dry_run

    def test_verbose_flag(self) -> None:
        """--verbose 标志。"""
        args = parse_args(["--verbose"])
        assert args.verbose


class TestPipelineRun:
    """Pipeline.run 方法测试。"""

    @patch("src.pipeline.pipeline.RSSCollector")
    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_full_pipeline(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
        mock_rss_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """完整流水线：采集 -> 分析 -> 保存。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = [
            {
                "title": "langchain/langchain",
                "url": "https://github.com/langchain/langchain",
                "source": "github",
                "popularity": 99000,
                "summary": "LLM framework",
                "collected_at": "2026-07-29T08:00:00Z",
            }
        ]
        mock_github_cls.return_value = mock_github

        mock_rss = MagicMock()
        mock_rss.collect.return_value = []
        mock_rss_cls.return_value = mock_rss

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = {
            "summary": "LLM 框架",
            "highlights": ["h1"],
            "score": 8,
            "tags": ["llm"],
            "category": "tool",
            "language": "en",
        }
        mock_analyzer_cls.return_value = mock_analyzer

        mock_organizer = MagicMock()
        mock_organizer.organize.return_value = {
            "article_id": "kb-20260729-aabbccdd",
            "title": "langchain/langchain",
            "status": "pending",
        }
        mock_organizer_cls.return_value = mock_organizer

        pipeline = Pipeline(["github", "rss"], limit=5)
        stats = pipeline.run()

        assert stats.collected == 1
        assert stats.analyzed == 1
        assert stats.saved == 1
        assert stats.skipped_duplicates == 0
        assert stats.errors == 0
        assert not stats.dry_run

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_dry_run(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """干跑模式不保存。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = [
            {"title": "test", "url": "https://example.com", "source": "github",
             "popularity": 10, "summary": "desc"}
        ]
        mock_github_cls.return_value = mock_github

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = {
            "summary": "s", "highlights": [], "score": 5,
            "tags": ["ai"], "category": "news", "language": "en",
        }
        mock_analyzer_cls.return_value = mock_analyzer

        mock_organizer = MagicMock()
        mock_organizer_cls.return_value = mock_organizer

        pipeline = Pipeline(["github"], limit=5, dry_run=True)
        stats = pipeline.run()

        assert stats.collected == 1
        assert stats.analyzed == 1
        assert stats.saved == 0
        assert stats.dry_run
        mock_organizer.organize.assert_not_called()

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_duplicate_skipped(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """重复条目被跳过。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = [
            {"title": "dup", "url": "https://example.com", "source": "github",
             "popularity": 5, "summary": "s"}
        ]
        mock_github_cls.return_value = mock_github

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = {
            "summary": "s", "highlights": [], "score": 5,
            "tags": ["ai"], "category": "news", "language": "en",
        }
        mock_analyzer_cls.return_value = mock_analyzer

        mock_organizer = MagicMock()
        mock_organizer.organize.return_value = None
        mock_organizer_cls.return_value = mock_organizer

        pipeline = Pipeline(["github"], limit=5)
        stats = pipeline.run()

        assert stats.skipped_duplicates == 1
        assert stats.saved == 0

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_organize_error_counted(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """保存失败计入 errors。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = [
            {"title": "t", "url": "https://example.com", "source": "github",
             "popularity": 5, "summary": "s"}
        ]
        mock_github_cls.return_value = mock_github

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = {
            "summary": "s", "highlights": [], "score": 5,
            "tags": ["ai"], "category": "news", "language": "en",
        }
        mock_analyzer_cls.return_value = mock_analyzer

        mock_organizer = MagicMock()
        mock_organizer.organize.side_effect = OSError("disk full")
        mock_organizer_cls.return_value = mock_organizer

        pipeline = Pipeline(["github"], limit=5)
        stats = pipeline.run()

        assert stats.errors == 1

    @patch("src.pipeline.pipeline.GitHubCollector")
    def test_run_collect_error_continues(self, mock_github_cls: MagicMock) -> None:
        """采集失败不中断流水线。"""
        mock_github = MagicMock()
        mock_github.collect.side_effect = RuntimeError("API down")
        mock_github_cls.return_value = mock_github

        pipeline = Pipeline(["github"], limit=5)
        stats = pipeline.run()

        assert stats.collected == 0
        assert stats.saved == 0

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    def test_run_no_items(
        self,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """无候选条目时提前结束。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = []
        mock_github_cls.return_value = mock_github

        pipeline = Pipeline(["github"], limit=5)
        stats = pipeline.run()

        assert stats.collected == 0
        assert stats.analyzed == 0
        mock_analyzer_cls.assert_called_once()

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_unknown_source_skipped(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """未知数据源被跳过。"""
        pipeline = Pipeline(["unknown"], limit=5)
        stats = pipeline.run()

        assert stats.collected == 0

    @patch("src.pipeline.pipeline.GitHubCollector")
    @patch("src.pipeline.pipeline.LLMAnalyzer")
    @patch("src.pipeline.pipeline.Organizer")
    def test_run_analyze_error_skipped(
        self,
        mock_organizer_cls: MagicMock,
        mock_analyzer_cls: MagicMock,
        mock_github_cls: MagicMock,
    ) -> None:
        """分析失败的条目被跳过。"""
        mock_github = MagicMock()
        mock_github.collect.return_value = [
            {"title": "t1", "url": "https://a.com", "source": "github",
             "popularity": 1, "summary": "s"},
            {"title": "t2", "url": "https://b.com", "source": "github",
             "popularity": 2, "summary": "s"},
        ]
        mock_github_cls.return_value = mock_github

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.side_effect = [
            Exception("unexpected error"),
            {"summary": "s", "highlights": [], "score": 5,
             "tags": ["ai"], "category": "news", "language": "en"},
        ]
        mock_analyzer_cls.return_value = mock_analyzer

        mock_organizer = MagicMock()
        mock_organizer.organize.return_value = {"article_id": "kb-test"}
        mock_organizer_cls.return_value = mock_organizer

        pipeline = Pipeline(["github"], limit=5)
        stats = pipeline.run()

        assert stats.analyzed == 1
        assert stats.saved == 1


class TestRunPipeline:
    """run_pipeline 便捷函数测试。"""

    @patch("src.pipeline.pipeline.Pipeline")
    def test_run_pipeline_delegates(self, mock_pipeline_cls: MagicMock) -> None:
        """run_pipeline 委托给 Pipeline。"""
        mock_pipeline = MagicMock()
        expected_stats = PipelineStats(collected=5, saved=3)
        mock_pipeline.run.return_value = expected_stats
        mock_pipeline_cls.return_value = mock_pipeline

        stats = run_pipeline(["github"], limit=10)

        assert stats.collected == 5
        assert stats.saved == 3
        mock_pipeline_cls.assert_called_once_with(["github"], 10, dry_run=False)


class TestPipelineStats:
    """PipelineStats 数据类测试。"""

    def test_default_values(self) -> None:
        """默认值为零。"""
        stats = PipelineStats()
        assert stats.collected == 0
        assert stats.analyzed == 0
        assert stats.saved == 0
        assert stats.skipped_duplicates == 0
        assert stats.errors == 0
        assert stats.dry_run is False
        assert stats.sources == []
