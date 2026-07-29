"""LangGraph 工作流状态定义。

定义工作流的全局状态结构，在各节点间传递。
工作流阶段：采集 -> 分析 -> 整理 -> 分发（见 AGENTS.md §5）。
"""

from __future__ import annotations

from typing import Any, TypedDict


class KBState(TypedDict, total=False):
    """带审核循环的 LangGraph 工作流共享状态。

    遵循"报告式通信"原则：各字段存储的是节点产出的结构化摘要，
    而非原始网页 HTML、原始 API 响应等未加工数据。
    每个节点完成后将产出写入对应字段，下游节点读取上游摘要进行下一步处理。

    工作流流程::

        采集 -> 分析 -> 整理 -> [审核]
                                    ├─ 通过 -> 保存
                                    └─ 不通过 -> 整理（带 feedback），最多 3 轮

    Attributes:
        trace_id: 链路追踪 ID，工作流入口生成，各节点通过
            :func:`src.common.trace.set_trace_id` 注入日志上下文。
        sources: 采集节点产出的数据源摘要列表。
            每个元素是一条候选条目的结构化摘要::

                {
                    "title": "条目标题",
                    "url": "来源链接",
                    "source_platform": "github_trending | hackernews",
                    "source_score": int,          # 热度（star/points）
                    "summary": "原始摘要或简介",
                    "content_path": "knowledge/raw/<id>.md",
                }

        analyses: 分析节点产出的 LLM 分析结果列表。
            每个元素对应 ``sources`` 中一条条目的 AI 分析摘要::

                {
                    "title": "分析后的标题",
                    "summary": "AI 生成的中文摘要（2-4 句话）",
                    "highlights": ["亮点1", "亮点2"],
                    "score": int,                  # 质量评分 1-10
                    "tags": ["llm", "agent"],      # 小写标签
                    "category": "model_release | paper | tool | tutorial | news",
                    "language": "zh | en",
                }

        articles: 整理节点产出的标准知识条目列表（已去重、格式化）。
            每个元素遵循 :doc:`article-format </docs/specs/article-format>` 的 JSON 结构::

                {
                    "article_id": "kb-YYYYMMDD-NNNN",
                    "title": "条目标题",
                    "source_url": "https://...",
                    "source_platform": "github_trending | hackernews",
                    "summary": "中文摘要",
                    "content_path": "knowledge/raw/<id>.md",
                    "tags": ["tag1", "tag2"],
                    "category": "model_release",
                    "status": "pending | reviewed | published | archived",
                    ...
                }

        review_feedback: 审核节点的反馈意见。
            审核通过时为空字符串；不通过时包含具体的改进建议，
            整理节点在下一轮重做时将该反馈注入 Worker prompt。
        review_passed: 审核是否通过。
            ``True`` -> 进入保存节点；``False`` -> 回到整理节点重做。
        iteration: 当前审核循环次数，从 1 开始，最多 3 次。
            达到上限仍未通过则强制返回最后结果。
        cost_tracker: Token 用量追踪字典。
            累积各节点的 LLM 调用成本，键为节点名称，值为该节点的用量摘要::

                {
                    "collect": {
                        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    },
                    "analyze": {
                        "prompt_tokens": 1234, "completion_tokens": 567, "total_tokens": 1801,
                    },
                    "review": {
                        "prompt_tokens": 890, "completion_tokens": 12, "total_tokens": 902,
                    },
                }

        errors: 工作流执行中累积的错误信息列表。
            每个元素包含 ``node``、``error``、``timestamp`` 三个键，
            供下游节点和调用方感知采集/分析等阶段的失败。
        saved_count: save_node 成功写入的知识条目数量。

    """

    # -- 链路追踪 --
    trace_id: str

    # -- 采集产出 --
    # 结构：title/url/source_platform/source_score/summary/content_path
    sources: list[dict[str, Any]]

    # -- 分析产出 --
    # 结构：title/summary/highlights/score/tags/category/language
    analyses: list[dict[str, Any]]

    # -- 整理产出 --
    # 遵循 docs/specs/article-format.md 的 JSON 结构
    articles: list[dict[str, Any]]

    # -- 审核状态 --
    # 不通过时含具体改进建议，通过时为空
    review_feedback: str
    # True -> 保存，False -> 回整理重做
    review_passed: bool
    # 1-3，达上限强制返回
    iteration: int

    # -- 成本追踪 --
    # 键=节点名，值={prompt_tokens, completion_tokens, total_tokens}
    cost_tracker: dict[str, Any]

    # -- 错误累积 --
    # 每个元素：{node: str, error: str, timestamp: str}
    errors: list[dict[str, Any]]

    # -- 保存结果 --
    # save_node 写入的条目数
    saved_count: int
