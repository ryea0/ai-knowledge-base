#!/usr/bin/env python3
"""知识条目 5 维度质量评分脚本。

用法:
    python hooks/check_quality.py <json_file> [json_file2 ...]

支持单文件和通配符多文件输入（由 shell 展开后传入多个路径参数）。
对每个知识条目按 5 个维度评分（加权总分 100 分），输出可视化进度条、
每维度得分及等级（A/B/C）。存在 C 级条目时 exit 1，否则 exit 0。

评分维度:
    摘要质量 (25 分): >=50 字满分，>=20 字基本分，含技术关键词有奖励
    技术深度 (25 分): 基于 score 字段（1-10 映射到 0-25）
    格式规范 (20 分): id/title/source_url/status/时间戳五项各 4 分
    标签精度 (15 分): 3-8 个合法标签最佳，含标准标签列表校验
    空洞词检测 (15 分): 不含中英空洞词满分
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------

# 技术关键词（摘要中出现则奖励），对齐 docs/specs/content-spec.md §6.1 采集关键词
TECH_KEYWORDS: set[str] = {
    "llm", "gpt", "transformer", "fine-tuning", "rag", "agent",
    "multimodal", "embedding", "vllm", "langchain", "llama", "diffusion",
    "inference", "prompt", "token", "attention", "bert", "claude",
    "openai", "pytorch", "tensorflow", "mcp",
}

# 标准标签白名单（对齐 docs/specs/content-spec.md §6.4: 禁止 ai/tech/other 等过宽标签）
STANDARD_TAGS: set[str] = {
    "llm", "gpt", "transformer", "fine-tuning", "rag", "agent",
    "multimodal", "embedding", "vllm", "langchain", "llama", "diffusion",
    "inference", "prompt-engineering", "tokenization", "attention",
    "bert", "claude", "openai", "pytorch", "tensorflow", "mcp",
    "autonomous-agents", "multi-agent", "multi-modal", "multi-provider",
    "code-review", "coding-agent", "cli", "ollama", "optimization",
    "orchestration", "nlp", "deep-learning", "foundation-model",
    "knowledge-graph", "context-engineering", "tool-calling",
    "memory", "security", "monitoring", "workflow", "tutorial",
    "data-extraction", "web-scraping", "text-processing", "visualization",
    "time-series", "token-optimization", "token-compression",
    "local-deployment", "low-code",
    "routing", "gateway", "springai", "glm", "qwen", "deepseek",
    "hermes", "dify", "langflow", "firecrawl", "markitdown", "opencode",
    "cross-harness", "subagent-driven-development", "parallel-execution",
    "methodology", "community", "education", "finance", "news-aggregation",
    "templates", "tdd", "skills", "personal-agent", "git-worktree",
    "code-graph", "tree-sitter", "ai-application", "microsoft", "anthropic",
    "chatgpt", "claude-code", "typescript", "java", "markdown",
}

# 禁止标签（对齐 §6.4: 禁止 ai/tech/other 等过宽标签）
BANNED_TAGS: set[str] = {"ai", "tech", "other", "new", "best", "top"}

# 中文空洞词黑名单
BUZZWORDS_ZH: list[str] = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑", "颗粒度",
    "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

# 英文空洞词黑名单（小写匹配）
BUZZWORDS_EN: list[str] = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "next-generation", "state-of-the-art", "world-class", "best-in-class",
    "paradigm-shifting", "disruptive", "seamless", "leverage", "synergy",
]

# article_id 格式：kb-YYYYMMDD-NNNN（对齐 AGENTS.md §4）
ARTICLE_ID_PATTERN = re.compile(r"^kb-\d{8}-\d{4}$")

# URL 格式
URL_PATTERN = re.compile(r"^https?://.+")

# ISO 8601 UTC 时间格式
ISO_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# 摘要维度参数
SUMMARY_FULL_LEN = 50
SUMMARY_BASE_LEN = 20

# 标签维度参数（对齐 §6.4: 3-8 个）
TAGS_MIN = 3
TAGS_MAX = 8

# 等级阈值
GRADE_A_THRESHOLD = 80
GRADE_B_THRESHOLD = 60


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """单个维度的评分结果。

    Attributes:
        name: 维度名称。
        score: 实际得分。
        max_score: 该维度满分。
        detail: 评分细节说明（扣分原因等）。
    """

    name: str
    score: float
    max_score: float
    detail: str


@dataclass
class QualityReport:
    """单个知识条目的质量评分报告。

    Attributes:
        file_path: 文件路径。
        article_id: 条目业务 ID（解析失败时为空字符串）。
        dimensions: 各维度评分列表。
        total_score: 加权总分。
        grade: 等级（A/B/C）。
        errors: 解析或致命错误列表（非评分扣分，而是无法评分的错误）。
    """

    file_path: Path
    article_id: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    grade: str = "C"
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """是否可正常评分（无致命错误）。"""
        return not self.errors


# ---------------------------------------------------------------------------
# 维度评分函数
# ---------------------------------------------------------------------------


def score_summary(summary: str, max_score: float = 25.0) -> DimensionScore:
    """评分摘要质量维度。

    规则:
        - >= 50 字：满分基础分
        - >= 20 字且 < 50 字：基本分（按比例折算）
        - < 20 字：低分
        - 含技术关键词额外奖励

    Args:
        summary: 摘要文本。
        max_score: 该维度满分，默认 25。

    Returns:
        DimensionScore 评分结果。
    """
    length = len(summary)
    detail_parts: list[str] = []

    # 基础分：按长度分段给分
    base_ratio: float
    if length >= SUMMARY_FULL_LEN:
        base_ratio = 1.0
        detail_parts.append(f"长度 {length} 字 >= {SUMMARY_FULL_LEN}，基础满分")
    elif length >= SUMMARY_BASE_LEN:
        ratio = (length - SUMMARY_BASE_LEN) / (SUMMARY_FULL_LEN - SUMMARY_BASE_LEN)
        base_ratio = 0.6 + 0.4 * ratio
        detail_parts.append(
            f"长度 {length} 字，{SUMMARY_BASE_LEN}-{SUMMARY_FULL_LEN} 区间，"
            f"基础分 {base_ratio:.0%}"
        )
    else:
        base_ratio = max(0.1, length / SUMMARY_BASE_LEN * 0.6)
        detail_parts.append(f"长度 {length} 字 < {SUMMARY_BASE_LEN}，基础分低")

    base_score = base_ratio * max_score

    # 技术关键词奖励：最多 +5 分（从满分中预留）
    keyword_bonus_max = 5.0
    base_max = max_score - keyword_bonus_max
    base_score = min(base_score, base_max)

    summary_lower = summary.lower()
    matched_keywords = [kw for kw in TECH_KEYWORDS if kw in summary_lower]
    keyword_bonus = min(len(matched_keywords) * 2.5, keyword_bonus_max)

    if matched_keywords:
        detail_parts.append(f"含技术关键词 {len(matched_keywords)} 个: {matched_keywords[:3]}")

    final_score = base_score + keyword_bonus
    final_score = min(final_score, max_score)

    return DimensionScore(
        name="摘要质量",
        score=round(final_score, 1),
        max_score=max_score,
        detail="；".join(detail_parts),
    )


def score_technical_depth(score: Any, max_score: float = 25.0) -> DimensionScore:
    """评分技术深度维度。

    规则:
        - 基于 article 的 score 字段（1-10）线性映射到 0-25 分
        - 无 score 字段记 0 分

    Args:
        score: 条目的 score 字段值。
        max_score: 该维度满分，默认 25。

    Returns:
        DimensionScore 评分结果。
    """
    if score is None:
        return DimensionScore(
            name="技术深度",
            score=0.0,
            max_score=max_score,
            detail="无 score 字段，记 0 分",
        )

    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return DimensionScore(
            name="技术深度",
            score=0.0,
            max_score=max_score,
            detail=f"score 类型无效 ({type(score).__name__})，记 0 分",
        )

    raw = float(score)
    if raw <= 0:
        return DimensionScore(
            name="技术深度",
            score=0.0,
            max_score=max_score,
            detail=f"score={raw}，记 0 分",
        )

    mapped = min(raw / 10.0, 1.0) * max_score
    return DimensionScore(
        name="技术深度",
        score=round(mapped, 1),
        max_score=max_score,
        detail=f"score={raw}，映射 {mapped:.1f}/{max_score}",
    )


def score_format(data: dict[str, Any], max_score: float = 20.0) -> DimensionScore:
    """评分格式规范维度。

    规则:
        - article_id 格式正确：4 分
        - title 非空：4 分
        - source_url 格式正确：4 分
        - status 合法枚举：4 分
        - 时间戳（collected_at）格式正确：4 分

    Args:
        data: JSON 解析后的字典。
        max_score: 该维度满分，默认 20。

    Returns:
        DimensionScore 评分结果。
    """
    item_score = max_score / 5.0
    detail_parts: list[str] = []
    earned = 0.0

    # article_id
    article_id = data.get("article_id")
    if isinstance(article_id, str) and ARTICLE_ID_PATTERN.match(article_id):
        earned += item_score
        detail_parts.append("article_id ✓")
    else:
        detail_parts.append(f"article_id ✗ (无效: {article_id!r})")

    # title
    title = data.get("title")
    if isinstance(title, str) and len(title) > 0:
        earned += item_score
        detail_parts.append("title ✓")
    else:
        detail_parts.append("title ✗")

    # source_url
    source_url = data.get("source_url")
    if isinstance(source_url, str) and URL_PATTERN.match(source_url):
        earned += item_score
        detail_parts.append("source_url ✓")
    else:
        detail_parts.append("source_url ✗")

    # status
    status = data.get("status")
    if status in ("pending", "reviewed", "published", "archived"):
        earned += item_score
        detail_parts.append(f"status ✓ ({status})")
    else:
        detail_parts.append(f"status ✗ (无效: {status!r})")

    # 时间戳（collected_at）
    collected_at = data.get("collected_at")
    if isinstance(collected_at, str) and ISO_UTC_PATTERN.match(collected_at):
        earned += item_score
        detail_parts.append("collected_at ✓")
    else:
        detail_parts.append(f"collected_at ✗ (无效: {collected_at!r})")

    return DimensionScore(
        name="格式规范",
        score=round(earned, 1),
        max_score=max_score,
        detail="；".join(detail_parts),
    )


def score_tags(tags: Any, max_score: float = 15.0) -> DimensionScore:
    """评分标签精度维度。

    规则:
        - 标签数量 3-8 个（对齐 §6.4）：满分基础
        - 数量不足或过多扣分
        - 含禁止标签（ai/tech/other 等）扣分
        - 含标准标签有奖励（覆盖率）

    Args:
        tags: 标签列表。
        max_score: 该维度满分，默认 15。

    Returns:
        DimensionScore 评分结果。
    """
    if not isinstance(tags, list) or len(tags) == 0:
        return DimensionScore(
            name="标签精度",
            score=0.0,
            max_score=max_score,
            detail="无标签或类型错误，记 0 分",
        )

    count = len(tags)
    detail_parts: list[str] = [f"共 {count} 个标签"]

    # 数量评分（满分 7 分）
    count_max = 7.0
    if TAGS_MIN <= count <= TAGS_MAX:
        count_score = count_max
        detail_parts.append(f"数量 {count} 在 {TAGS_MIN}-{TAGS_MAX} 范围内，满分")
    elif count < TAGS_MIN:
        count_score = count_max * (count / TAGS_MIN)
        detail_parts.append(f"数量不足（< {TAGS_MIN}），扣分")
    else:
        count_score = max(0, count_max - (count - TAGS_MAX) * 1.5)
        detail_parts.append(f"数量过多（> {TAGS_MAX}），扣分")

    # 标签质量评分（满分 8 分）
    quality_max = 8.0
    banned_found = [t for t in tags if isinstance(t, str) and t.lower() in BANNED_TAGS]
    valid_tags = [t for t in tags if isinstance(t, str) and t.lower() not in BANNED_TAGS]
    standard_matched = [t for t in valid_tags if t.lower() in STANDARD_TAGS]
    non_standard = [t for t in valid_tags if t.lower() not in STANDARD_TAGS]

    quality_score = quality_max
    if banned_found:
        penalty = len(banned_found) * 3.0
        quality_score -= penalty
        detail_parts.append(f"含禁止标签 {len(banned_found)} 个: {banned_found}")

    coverage = len(standard_matched) / count if count > 0 else 0
    if coverage >= 0.5:
        detail_parts.append(f"标准标签覆盖率 {coverage:.0%}")
    else:
        quality_score -= (0.5 - coverage) * 8.0
        detail_parts.append(f"标准标签覆盖率低 ({coverage:.0%})")

    if non_standard:
        detail_parts.append(f"非标准标签 {len(non_standard)} 个: {non_standard[:3]}")

    quality_score = max(0, quality_score)
    final_score = min(count_score + quality_score, max_score)

    return DimensionScore(
        name="标签精度",
        score=round(final_score, 1),
        max_score=max_score,
        detail="；".join(detail_parts),
    )


def score_buzzword(
    summary: str, title: str = "", max_score: float = 15.0
) -> DimensionScore:
    """评分空洞词检测维度。

    规则:
        - summary 和 title 中不含任何空洞词：满分
        - 每出现一个空洞词扣 3 分，扣完为止

    Args:
        summary: 摘要文本。
        title: 标题文本。
        max_score: 该维度满分，默认 15。

    Returns:
        DimensionScore 评分结果。
    """
    combined = f"{summary} {title}"
    combined_lower = combined.lower()
    found: list[str] = []

    for word in BUZZWORDS_ZH:
        if word in combined:
            found.append(word)

    for word in BUZZWORDS_EN:
        if word in combined_lower:
            found.append(word)

    if not found:
        return DimensionScore(
            name="空洞词检测",
            score=max_score,
            max_score=max_score,
            detail="未检测到空洞词，满分",
        )

    penalty = len(found) * 3.0
    final_score = max(0, max_score - penalty)
    return DimensionScore(
        name="空洞词检测",
        score=round(final_score, 1),
        max_score=max_score,
        detail=f"检测到 {len(found)} 个空洞词: {found}，扣 {penalty:.0f} 分",
    )


# ---------------------------------------------------------------------------
# 可视化与报告
# ---------------------------------------------------------------------------


def render_bar(score: float, max_score: float, width: int = 20) -> str:
    """渲染得分进度条。

    Args:
        score: 实际得分。
        max_score: 满分。
        width: 进度条宽度（字符数）。

    Returns:
        形如 ``[████████░░░░░░░░] 12.0/20`` 的进度条字符串。
    """
    ratio = score / max_score if max_score > 0 else 0
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {score:.1f}/{max_score:.0f}"


def calc_grade(total: float) -> str:
    """根据总分计算等级。

    Args:
        total: 加权总分（0-100）。

    Returns:
        等级字符 A/B/C。
    """
    if total >= GRADE_A_THRESHOLD:
        return "A"
    if total >= GRADE_B_THRESHOLD:
        return "B"
    return "C"


def print_report(report: QualityReport) -> None:
    """输出单个条目的质量报告。

    Args:
        report: 质量评分报告。
    """
    print(f"\n{'─' * 60}")
    print(f"文件: {report.file_path}")
    if report.article_id:
        print(f"ID:   {report.article_id}")

    if not report.is_valid:
        print("状态: 无法评分（致命错误）")
        for err in report.errors:
            print(f"  ✗ {err}")
        print(f"等级: {report.grade} (0 分)")
        return

    for dim in report.dimensions:
        bar = render_bar(dim.score, dim.max_score)
        print(f"  {dim.name:<8} {bar}  {dim.detail}")

    print(f"\n  总分: {report.total_score:.1f}/100  等级: [{report.grade}]")


# ---------------------------------------------------------------------------
# 主评分逻辑
# ---------------------------------------------------------------------------


def evaluate_entry(data: Any, file_path: Path) -> QualityReport:
    """对单个 JSON 条目执行 5 维度评分。

    Args:
        data: JSON 解析后的数据。
        file_path: 文件路径。

    Returns:
        QualityReport 评分报告。
    """
    report = QualityReport(file_path=file_path, article_id="")

    if not isinstance(data, dict):
        report.errors.append("顶层结构不是 JSON 对象")
        report.grade = "C"
        return report

    report.article_id = data.get("article_id", "") if isinstance(
        data.get("article_id"), str
    ) else ""

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    title = data.get("title", "")
    if not isinstance(title, str):
        title = ""

    tags = data.get("tags", [])
    score_val = data.get("score")

    # 5 维度评分
    report.dimensions = [
        score_summary(summary, 25.0),
        score_technical_depth(score_val, 25.0),
        score_format(data, 20.0),
        score_tags(tags, 15.0),
        score_buzzword(summary, title, 15.0),
    ]

    report.total_score = round(sum(d.score for d in report.dimensions), 1)
    report.grade = calc_grade(report.total_score)

    return report


def evaluate_file(file_path: Path) -> QualityReport:
    """读取并评分单个 JSON 文件。

    Args:
        file_path: 待评分的 JSON 文件路径。

    Returns:
        QualityReport 评分报告。
    """
    report = QualityReport(file_path=file_path, article_id="")

    if not file_path.is_file():
        report.errors.append("文件不存在或不是普通文件")
        return report

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        report.errors.append(f"文件读取失败: {exc}")
        return report

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.errors.append(f"JSON 解析失败 (行 {exc.lineno}, 列 {exc.colno}): {exc.msg}")
        return report

    return evaluate_entry(data, file_path)


def main(argv: list[str] | None = None) -> int:
    """脚本入口，解析命令行参数并执行批量质量评分。

    Args:
        argv: 命令行参数列表，默认从 sys.argv 读取。

    Returns:
        0 表示无 C 级条目，1 表示存在 C 级条目。
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(
            "用法: python hooks/check_quality.py <json_file> [json_file2 ...]",
            file=sys.stderr,
        )
        return 1

    reports: list[QualityReport] = []

    for arg in args:
        path = Path(arg)
        reports.append(evaluate_file(path))

    # 输出各报告
    for report in reports:
        print_report(report)

    # 汇总统计
    total = len(reports)
    grade_a = sum(1 for r in reports if r.grade == "A")
    grade_b = sum(1 for r in reports if r.grade == "B")
    grade_c = sum(1 for r in reports if r.grade == "C")
    avg_score = (
        sum(r.total_score for r in reports) / total if total > 0 else 0
    )

    print(f"\n{'═' * 60}")
    print(
        f"质量汇总: 共 {total} 个条目, "
        f"A={grade_a}  B={grade_b}  C={grade_c}, "
        f"平均分 {avg_score:.1f}"
    )

    if grade_c > 0:
        print(f"存在 {grade_c} 个 C 级条目")
        print("═" * 60)
        return 1

    print("═" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
