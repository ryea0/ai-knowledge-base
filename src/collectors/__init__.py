"""数据源采集器模块。

提供从外部数据源（GitHub Trending / Hacker News）采集 AI/LLM/Agent 领域技术动态的能力。
采集 Agent 采用只读设计，输出 JSON 候选列表，不直接写文件。

子模块：
    - ``base``: 采集器抽象基类
    - ``github_trending``: GitHub Trending 采集器
    - ``hackernews``: Hacker News 采集器
"""

from src.collectors.base import BaseCollector

__all__ = ["BaseCollector"]
