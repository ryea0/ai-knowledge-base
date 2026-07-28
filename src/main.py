"""AI 知识库助手入口脚本。

执行完整工作流：采集 -> 分析 -> 整理 -> 分发。
可通过 ``--stage`` 参数指定只执行某一阶段。
"""

import argparse
import logging
import sys

from src.config.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    """CLI 入口。

    Returns:
        0 表示成功，非 0 表示失败。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库助手：采集 -> 分析 -> 整理 -> 分发"
    )
    parser.add_argument(
        "--stage",
        choices=["collect", "analyze", "curate", "all"],
        default="all",
        help="执行阶段，默认 all（全流程）",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别，默认 INFO",
    )
    args = parser.parse_args()

    setup_logging(log_level=args.log_level)

    logger.info("启动 AI 知识库助手，阶段: %s", args.stage)

    try:
        if args.stage in ("collect", "all"):
            logger.info("采集阶段开始")
        if args.stage in ("analyze", "all"):
            logger.info("分析阶段开始")
        if args.stage in ("curate", "all"):
            logger.info("整理/分发阶段开始")
    except Exception:
        logger.exception("工作流执行失败")
        return 1

    logger.info("工作流完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
