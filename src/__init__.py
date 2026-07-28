"""AI 知识库助手核心包。

子模块：
    - ``collectors``: 数据源采集器（GitHub Trending / Hacker News）
    - ``analyzers``: AI 分析与摘要生成
    - ``organizers``: 知识整理与去重
    - ``distributors``: 多渠道分发（Telegram / 飞书）
    - ``models``: Pydantic 模型与枚举定义
    - ``llm``: LLM 供应商管理与调用
    - ``graph``: LangGraph 工作流定义
    - ``config``: 配置加载
    - ``common``: 通用基础设施（响应模型、异常、DB）
    - ``utils``: 通用工具函数
"""

__all__ = [
    "analyzers",
    "collectors",
    "common",
    "config",
    "distributors",
    "graph",
    "llm",
    "models",
    "organizers",
    "utils",
]
