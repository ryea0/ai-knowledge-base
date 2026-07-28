"""通用工具函数模块。

提供跨模块复用的工具函数，不依赖业务逻辑。

子模块：
    - ``github_api``: GitHub API 封装（限速、重试、Token 鉴权）
    - ``id_gen``: 知识条目 ID 生成器（格式 ``kb-YYYYMMDD-NNNN``）
"""
