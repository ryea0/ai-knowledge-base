"""知识库自动化流水线模块。

四步流水线：采集 -> 分析 -> 整理 -> 保存。

子模块：
    - ``pipeline``: 流水线主编排，CLI 入口
    - ``github_collector``: GitHub Search API 采集器
    - ``rss_collector``: RSS 源采集器（简易正则解析）
    - ``analyzer``: LLM 内容分析器
    - ``organizer``: 去重 + 格式标准化 + 校验 + 存盘
"""

__all__ = ["Pipeline", "run_pipeline"]


def __getattr__(name: str) -> object:
    """延迟导入 Pipeline 和 run_pipeline，避免循环依赖。

    Args:
        name: 属性名。

    Returns:
        对应的模块对象。

    Raises:
        AttributeError: 属性不存在。
    """
    if name in ("Pipeline", "run_pipeline"):
        from src.pipeline.pipeline import Pipeline, run_pipeline

        return {"Pipeline": Pipeline, "run_pipeline": run_pipeline}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
