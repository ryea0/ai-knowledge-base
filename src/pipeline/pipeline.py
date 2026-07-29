"""知识库自动化流水线主编排。

四步流水线：采集 -> 分析 -> 整理 -> 保存。

    python -m src.pipeline.pipeline --sources github,rss --limit 20
    python -m src.pipeline.pipeline --sources github --limit 5 --dry-run
    python -m src.pipeline.pipeline --sources rss --limit 10 --verbose

设计：
    - Step 1 Collect: GitHub Search API + RSS 源采集
    - Step 2 Analyze: 调用 LLM 生成摘要/评分/标签
    - Step 3 Organize: 去重 + 格式标准化 + 校验
    - Step 4 Save: 原始内容存 knowledge/raw/，条目存 knowledge/articles/

复用项目现有模块：
    - ``src.llm.client.quick_chat``: LLM 调用（自动路由供应商）
    - ``src.config.settings.get_settings``: 配置加载
    - ``src.config.logging_config.setup_logging``: 日志配置
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.pipeline.analyzer import LLMAnalyzer
from src.pipeline.github_collector import GitHubCollector
from src.pipeline.organizer import Organizer
from src.pipeline.rss_collector import RSSCollector

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """流水线执行统计。

    Attributes:
        collected: 采集条目数。
        analyzed: 分析条目数（含降级）。
        saved: 保存条目数。
        skipped_duplicates: 去重跳过数。
        errors: 错误数。
        started_at: 开始时间。
        finished_at: 结束时间。
        sources: 使用的数据源列表。
        limit: 每源采集上限。
        dry_run: 是否干跑模式。
    """

    collected: int = 0
    analyzed: int = 0
    saved: int = 0
    skipped_duplicates: int = 0
    errors: int = 0
    started_at: str = ""
    finished_at: str = ""
    sources: list[str] = field(default_factory=list)
    limit: int = 0
    dry_run: bool = False


class Pipeline:
    """知识库自动化流水线编排器。

    协调采集器、分析器、整理器完成四步流水线。
    支持 GitHub / RSS 双数据源、干跑模式、verbose 日志。

    Attributes:
        sources: 数据源列表（"github" / "rss"）。
        limit: 每个数据源最大采集条数。
        dry_run: 干跑模式（仅采集和分析，不保存）。
    """

    def __init__(
        self,
        sources: list[str],
        limit: int = 20,
        *,
        dry_run: bool = False,
    ) -> None:
        """初始化流水线。

        Args:
            sources: 数据源列表，元素为 "github" 或 "rss"。
            limit: 每个数据源最大采集条数。
            dry_run: 干跑模式，仅采集和分析不保存。
        """
        self.sources = sources
        self.limit = limit
        self.dry_run = dry_run
        self._analyzer = LLMAnalyzer()
        self._organizer = Organizer()

    def run(self) -> PipelineStats:
        """执行完整流水线。

        Returns:
            执行统计信息。
        """
        stats = PipelineStats(
            started_at=datetime.now(UTC).isoformat(),
            sources=list(self.sources),
            limit=self.limit,
            dry_run=self.dry_run,
        )

        logger.info(
            "流水线启动: sources=%s limit=%d dry_run=%s",
            self.sources,
            self.limit,
            self.dry_run,
        )

        # Step 1: Collect
        items = self._collect()
        stats.collected = len(items)
        logger.info("Step 1 采集完成: %d 条", stats.collected)

        if not items:
            logger.info("无候选条目，流水线结束")
            stats.finished_at = datetime.now(UTC).isoformat()
            return stats

        # Step 2: Analyze
        analyzed_items = self._analyze_batch(items)
        stats.analyzed = len(analyzed_items)
        logger.info("Step 2 分析完成: %d 条", stats.analyzed)

        if self.dry_run:
            logger.info("干跑模式，跳过保存步骤")
            stats.finished_at = datetime.now(UTC).isoformat()
            self._log_dry_run(analyzed_items)
            return stats

        # Step 3 + 4: Organize & Save
        for item, analysis in analyzed_items:
            try:
                result = self._organizer.organize(item, analysis)
                if result is None:
                    stats.skipped_duplicates += 1
                else:
                    stats.saved += 1
            except Exception:
                stats.errors += 1
                logger.exception("保存条目失败: %s", item.get("url", ""))

        logger.info(
            "Step 3+4 整理保存完成: saved=%d duplicates=%d errors=%d",
            stats.saved,
            stats.skipped_duplicates,
            stats.errors,
        )

        stats.finished_at = datetime.now(UTC).isoformat()
        logger.info("流水线完成: %s", stats)
        return stats

    def _collect(self) -> list[dict[str, Any]]:
        """执行采集步骤。

        按配置的数据源分别调用采集器，合并结果。

        Returns:
            所有数据源的候选条目列表。
        """
        all_items: list[dict[str, Any]] = []

        for source in self.sources:
            try:
                if source == "github":
                    gh_collector = GitHubCollector(limit=self.limit)
                    all_items.extend(gh_collector.collect())
                elif source == "rss":
                    rss_collector = RSSCollector(limit=self.limit)
                    all_items.extend(rss_collector.collect())
                else:
                    logger.warning("未知数据源: %s，跳过", source)
            except Exception:
                logger.exception("采集 %s 失败", source)

        return all_items

    def _analyze_batch(
        self, items: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """批量分析采集条目。

        对每条条目调用 LLM 分析器，返回 (item, analysis) 元组列表。
        分析失败的条目使用降级分析结果。

        Args:
            items: 采集条目列表。

        Returns:
            (item, analysis_result) 元组列表。
        """
        results: list[tuple[dict[str, Any], dict[str, Any]]] = []

        for item in items:
            try:
                analysis = self._analyzer.analyze(item)
                results.append((item, analysis))
            except Exception:
                logger.exception(
                    "分析失败（含降级），跳过: %s", item.get("title", "")
                )

        return results

    @staticmethod
    def _log_dry_run(
        analyzed_items: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        """干跑模式下输出分析结果摘要。

        Args:
            analyzed_items: (item, analysis) 元组列表。
        """
        for item, analysis in analyzed_items:
            logger.info(
                "[DRY-RUN] %s | score=%d | category=%s | tags=%s",
                item.get("title", ""),
                analysis.get("score", 0),
                analysis.get("category", ""),
                analysis.get("tags", []),
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。

    Args:
        argv: 命令行参数列表，None 时使用 sys.argv。

    Returns:
        解析后的 argparse.Namespace。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库流水线：采集 -> 分析 -> 整理 -> 保存",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github,rss",
        help="数据源列表，逗号分隔（github, rss），默认 'github,rss'",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="每个数据源最大采集条数，默认 20",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式：仅采集和分析，不保存文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志输出（DEBUG 级别）",
    )
    return parser.parse_args(argv)


def run_pipeline(
    sources: list[str],
    limit: int = 20,
    *,
    dry_run: bool = False,
) -> PipelineStats:
    """运行流水线的便捷函数。

    Args:
        sources: 数据源列表。
        limit: 每源采集上限。
        dry_run: 是否干跑模式。

    Returns:
        执行统计信息。
    """
    pipeline = Pipeline(sources, limit, dry_run=dry_run)
    return pipeline.run()


def main() -> int:
    """CLI 入口。

    Returns:
        0 表示成功，1 表示失败。
    """
    args = parse_args()

    from src.common.trace import generate_trace_id, set_trace_id
    from src.config.logging_config import setup_logging

    setup_logging(log_level="DEBUG" if args.verbose else "INFO")

    trace_id = generate_trace_id()
    set_trace_id(trace_id)
    logger.info("trace_id=%s", trace_id)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        logger.error("未指定有效数据源")
        return 1

    pipeline = Pipeline(sources, args.limit, dry_run=args.dry_run)
    stats = pipeline.run()

    print(
        f"\n{'='*60}\n"
        f"Pipeline Summary\n"
        f"{'='*60}\n"
        f"  Sources:          {', '.join(stats.sources)}\n"
        f"  Limit per source: {stats.limit}\n"
        f"  Collected:        {stats.collected}\n"
        f"  Analyzed:         {stats.analyzed}\n"
        f"  Saved:            {stats.saved}\n"
        f"  Skipped (dup):    {stats.skipped_duplicates}\n"
        f"  Errors:           {stats.errors}\n"
        f"  Dry run:          {stats.dry_run}\n"
        f"  Started:          {stats.started_at}\n"
        f"  Finished:         {stats.finished_at}\n"
        f"{'='*60}"
    )

    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
