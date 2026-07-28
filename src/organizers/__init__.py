"""知识整理与去重模块。

整理 Agent 是工作流中唯一允许写入 ``knowledge/articles/`` 的角色。
职责（见 AGENTS.md §5）：
    1. 对采集+分析产出执行去重检查（查 DB ``kb_article.source_url``）。
    2. 格式化为标准 JSON 知识条目。
    3. 写入 DB（事务内）并同步投影至 ``knowledge/articles/<id>.json``。
    4. 初始状态为 ``pending``。

子模块：
    - ``base``: 整理器抽象基类
    - ``dedup``: 去重算法
    - ``formatter``: JSON 格式化与存盘
"""

from src.organizers.base import BaseOrganizer

__all__ = ["BaseOrganizer"]
