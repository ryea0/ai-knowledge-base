"""分析器抽象基类。

分析器职责（见 AGENTS.md §5）：
    1. 读取 ``knowledge/raw/`` 中的原始内容。
    2. 调用 LLM 生成中文摘要（2-4 句话、150 字以内）。
    3. 提炼亮点（highlights）。
    4. 对内容质量打分（1-10）。
    5. 建议标签（3-8 个，小写英文）。
    6. 判定分类（model_release/paper/tool/tutorial/news）。
    7. 检测原文语言（zh/en）。

输出 JSON 对象，不落盘。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseAnalyzer(ABC):
    """内容分析器抽象基类。

    子类须实现 :meth:`analyze` 方法，读取原始内容并返回分析结果。
    """

    @abstractmethod
    def analyze(self, content_path: str, **kwargs: Any) -> dict[str, Any]:
        """分析原始内容，返回结构化分析结果。

        Args:
            content_path: 原始内容文件路径（相对项目根目录）。
            **kwargs: 子类特定参数。

        Returns:
            分析结果 dict，包含以下键:
                - ``title`` (str): 条目标题。
                - ``summary`` (str): AI 生成中文摘要。
                - ``highlights`` (list[str]): 亮点列表。
                - ``score`` (int): 质量评分 1-10。
                - ``tags`` (list[str]): 建议标签（小写英文）。
                - ``category`` (str): 分类字符串。
                - ``language`` (str): 原文语言 zh/en。

        Raises:
            FileNotFoundError: 原始内容文件不存在。
            RuntimeError: LLM 调用失败。
        """
        ...
