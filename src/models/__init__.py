"""数据模型与 Schema 定义模块。

提供跨模块共享的 Pydantic 模型和枚举定义。
枚举的唯一定义点为 ``enums.py``，变更须同步 AGENTS.md。

子模块：
    - ``enums``: 知识条目与 LLM 供应商相关枚举（ArticleStatus / Category / ...）
    - ``skill_schemas``: 技能输出数据的 Pydantic 模型（镜像各技能 schema.json）
"""
