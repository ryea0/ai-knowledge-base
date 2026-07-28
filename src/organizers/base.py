"""整理器抽象基类。

整理器职责（见 AGENTS.md §5、§4）：
    1. 接收采集元信息 + 分析 JSON 产出。
    2. 去重检查（查 DB ``kb_article.source_url`` 或 ``knowledge/raw/``）。
    3. 格式化为标准 JSON 知识条目（字段定义见 §4）。
    4. 写入 DB（事务内，先 INSERT 取 id，再回填 article_id）。
    5. 同步投影至 ``knowledge/articles/<article_id>.json``。
    6. 初始状态为 ``pending``。

权限：允许 Read / Grep / Glob / Write / Edit，禁止 WebFetch / Bash。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseOrganizer(ABC):
    """知识整理器抽象基类。

    子类须实现 :meth:`organize` 方法，完成去重、格式化和存盘。
    """

    @abstractmethod
    def organize(
        self,
        collected_meta: dict[str, Any],
        analysis_result: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """整理单条知识条目。

        Args:
            collected_meta: 采集元信息（title/url/source_platform/source_score/collected_at）。
            analysis_result: 分析产出（summary/highlights/score/tags/category/language）。
            **kwargs: 子类特定参数。

        Returns:
            格式化后的标准知识条目 dict（见 §4 字段定义）；
            若去重检查判定为重复则返回 ``None``。

        Raises:
            RuntimeError: DB 写入或文件写入失败。
        """
        ...
