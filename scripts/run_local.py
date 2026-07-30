#!/usr/bin/env python
"""本地运行脚本：graph 工作流 / pipeline 流水线。

Usage::

    # graph 模式（LangGraph 状态机：采集 -> 分析 -> 审核 -> 整理 -> 保存 -> 推送简报）
    uv run python scripts/run_local.py graph

    # pipeline 模式（四步流水线：采集 -> 分析 -> 整理 -> 保存）
    uv run python scripts/run_local.py pipeline --sources github,rss --limit 10

    # pipeline 干跑模式（不保存）
    uv run python scripts/run_local.py pipeline --dry-run

    # 指定日志级别
    uv run python scripts/run_local.py graph --log-level DEBUG
"""

from __future__ import annotations

import argparse
import sys


def run_graph(log_level: str) -> int:
    """运行 LangGraph 工作流。

    Args:
        log_level: 日志级别。

    Returns:
        0 表示成功，1 表示失败。
    """
    from src.common.trace import generate_trace_id, set_trace_id
    from src.config.logging_config import setup_logging
    from src.graph.graph import run_workflow

    setup_logging(log_level=log_level)
    trace_id = generate_trace_id()
    set_trace_id(trace_id)

    print(f"{'=' * 60}")
    print(f"LangGraph 工作流启动  trace_id={trace_id}")
    print(f"{'-' * 60}")

    try:
        run_workflow()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("工作流执行失败")
        return 1

    print(f"{'=' * 60}")
    print("工作流执行完成")
    print(f"{'=' * 60}")
    return 0


def run_pipeline(
    sources: str,
    limit: int,
    dry_run: bool,
    log_level: str,
) -> int:
    """运行 pipeline 流水线。

    Args:
        sources: 逗号分隔的数据源列表。
        limit: 每个数据源最大采集条数。
        dry_run: 是否干跑模式。
        log_level: 日志级别。

    Returns:
        0 表示成功，1 表示失败。
    """
    from src.common.trace import generate_trace_id, set_trace_id
    from src.config.logging_config import setup_logging
    from src.pipeline.pipeline import Pipeline

    setup_logging(log_level=log_level)
    trace_id = generate_trace_id()
    set_trace_id(trace_id)

    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    if not source_list:
        print("错误: 未指定有效数据源")
        return 1

    print(f"{'=' * 60}")
    print(f"Pipeline 流水线启动  trace_id={trace_id}")
    print(f"  数据源: {', '.join(source_list)}")
    print(f"  上限:   {limit}")
    print(f"  干跑:   {dry_run}")
    print(f"{'-' * 60}")

    try:
        pipeline = Pipeline(source_list, limit, dry_run=dry_run)
        stats = pipeline.run()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("流水线执行失败")
        return 1

    print(f"{'=' * 60}")
    print("Pipeline Summary")
    print(f"{'=' * 60}")
    print(f"  Sources:          {', '.join(stats.sources)}")
    print(f"  Limit per source: {stats.limit}")
    print(f"  Collected:        {stats.collected}")
    print(f"  Analyzed:         {stats.analyzed}")
    print(f"  Saved:            {stats.saved}")
    print(f"  Skipped (dup):    {stats.skipped_duplicates}")
    print(f"  Errors:           {stats.errors}")
    print(f"  Dry run:          {stats.dry_run}")
    print(f"  Started:          {stats.started_at}")
    print(f"  Finished:         {stats.finished_at}")
    print(f"{'=' * 60}")

    return 0 if stats.errors == 0 else 1


def main() -> int:
    """CLI 入口。

    Returns:
        0 表示成功，1 表示失败。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库本地运行脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  uv run python scripts/run_local.py graph\n"
            "  uv run python scripts/run_local.py pipeline --sources github,rss --limit 10\n"
            "  uv run python scripts/run_local.py pipeline --dry-run\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True, help="运行模式")

    # graph 子命令
    graph_parser = subparsers.add_parser(
        "graph", help="LangGraph 工作流模式"
    )
    graph_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别，默认 INFO",
    )

    # pipeline 子命令
    pipeline_parser = subparsers.add_parser(
        "pipeline", help="Pipeline 流水线模式"
    )
    pipeline_parser.add_argument(
        "--sources",
        type=str,
        default="github,rss",
        help="数据源列表，逗号分隔（github, rss），默认 'github,rss'",
    )
    pipeline_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="每个数据源最大采集条数，默认 20",
    )
    pipeline_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式：仅采集和分析，不保存文件",
    )
    pipeline_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别，默认 INFO",
    )

    args = parser.parse_args()

    if args.mode == "graph":
        return run_graph(args.log_level)
    elif args.mode == "pipeline":
        return run_pipeline(
            sources=args.sources,
            limit=args.limit,
            dry_run=args.dry_run,
            log_level=args.log_level,
        )
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
