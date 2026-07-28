"""AI 分析与摘要生成模块。

读取 ``knowledge/raw/`` 中的原始内容，调用 LLM 生成中文摘要、亮点提炼、
1-10 评分与建议标签。分析 Agent 采用只读设计，输出 JSON 分析结果，不直接写文件。

子模块：
    - ``base``: 分析器抽象基类
    - ``llm_analyzer``: 基于 LLM 的内容分析器
"""

from src.analyzers.base import BaseAnalyzer

__all__ = ["BaseAnalyzer"]
