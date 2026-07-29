#!/usr/bin/env python3
"""校验知识条目 JSON 文件的脚本。

用法:
    python hooks/validate_json.py <json_file> [json_file2 ...]

支持单文件和通配符多文件输入（由 shell 展开后传入多个路径参数）。
校验规则对齐 AGENTS.md §4（知识条目 JSON 格式）与 §6.6（状态定义）。
校验通过 exit 0，失败 exit 1 并输出错误列表与汇总统计。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# 必填字段：字段名 -> 期望类型（对齐 AGENTS.md §4 必填列与 §7.5 DDL 约束）
# DDL 带 DEFAULT 的字段（source_score/language）在 JSON 投影中始终写出实际值，
# 故视为必填校验。
REQUIRED_FIELDS: dict[str, type] = {
    "article_id": str,
    "title": str,
    "source_url": str,
    "source_platform": str,
    "source_score": int,
    "summary": str,
    "content_path": str,
    "tags": list,
    "category": str,
    "status": str,
    "language": str,
    "collected_at": str,
}

# 可空字段：字段名 -> (期望类型, 是否允许 None)
NULLABLE_FIELDS: dict[str, tuple[type, bool]] = {
    "analyzed_at": (str, True),
    "published_at": (str, True),
    "published_channels": (list, True),
}

# status 合法取值（对齐 §6.6）
VALID_STATUS: set[str] = {"pending", "reviewed", "published", "archived"}

# source_platform 合法取值（对齐 §4）
VALID_PLATFORMS: set[str] = {"github_trending", "hackernews"}

# category 合法取值（对齐 §6.5）
VALID_CATEGORIES: set[str] = {
    "model_release",
    "paper",
    "tool",
    "tutorial",
    "news",
}

# language 合法取值（对齐 §4）
VALID_LANGUAGES: set[str] = {"zh", "en"}

# article_id 格式：kb-YYYYMMDD-NNNN（DB 模式）或 kb-YYYYMMDD-XXXXXXXX（pipeline 独立模式）
ARTICLE_ID_PATTERN = re.compile(r"^kb-\d{8}-([0-9a-f]{4}|[0-9a-f]{8})$")

# URL 格式：http(s)://...
URL_PATTERN = re.compile(r"^https?://.+")

# ISO 8601 UTC 时间格式（如 2026-07-27T08:00:00Z）
ISO_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# 摘要最少字数（对齐 §6.3）
MIN_SUMMARY_LEN = 20

# 摘要最大字数（对齐 §6.3: ≤150 字；DDL VARCHAR(500) 为上限）
MAX_SUMMARY_LEN = 500

# 标题最大字数（对齐 §6.2: ≤60 字；DDL VARCHAR(120) 为上限）
MAX_TITLE_LEN = 120

# 标签数量范围（对齐 §6.4: 3-8 个）
MIN_TAGS = 3
MAX_TAGS = 8

# source_score 最小值（热度，star 数 / points，≥0）
SOURCE_SCORE_MIN = 0

# 分析评分取值范围（1-10，对齐 §5 分析 Agent 输出）
ANALYZER_SCORE_MIN = 1
ANALYZER_SCORE_MAX = 10


def _check_type(value: Any, expected: type, field: str, prefix: str) -> list[str]:
    """检查值类型是否匹配，返回错误消息列表。

    单独抽离以复用：bool 是 int 子类，需额外排除。

    Args:
        value: 待检查的值。
        expected: 期望的 Python 类型。
        field: 字段名（用于错误消息）。
        prefix: 错误消息前缀（含文件路径）。

    Returns:
        错误消息列表，无错误时为空。
    """
    if expected is int and isinstance(value, bool):
        return [f"{prefix} 字段 '{field}' 类型错误: 期望 int, 实际 bool"]
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        actual = type(value).__name__
        return [
            f"{prefix} 字段 '{field}' 类型错误: "
            f"期望 {expected.__name__}, 实际 {actual}"
        ]
    return []


def validate_entry(data: Any, file_path: Path) -> list[str]:
    """校验单个 JSON 条目，返回错误消息列表（空列表表示通过）。

    Args:
        data: JSON 解析后的数据对象。
        file_path: 文件路径，用于错误消息标注。

    Returns:
        错误消息列表，无错误时为空。
    """
    errors: list[str] = []
    prefix = f"[{file_path}]"

    if not isinstance(data, dict):
        errors.append(f"{prefix} 顶层结构不是 JSON 对象")
        return errors

    # --- 必填字段：存在性 + 类型 ---
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"{prefix} 缺少必填字段: {field}")
        else:
            errors.extend(_check_type(data[field], expected_type, field, prefix))

    # --- 可空/可选字段：类型校验 ---
    for field, (expected_type, allow_none) in NULLABLE_FIELDS.items():
        if field not in data:
            continue
        value = data[field]
        if value is None:
            if not allow_none:
                errors.append(f"{prefix} 字段 '{field}' 不允许为 null")
            continue
        errors.extend(_check_type(value, expected_type, field, prefix))

    # --- 以下为值格式校验，仅在前置类型检查通过后执行 ---

    # article_id 格式
    article_id = data.get("article_id")
    if isinstance(article_id, str) and not ARTICLE_ID_PATTERN.match(article_id):
        errors.append(
            f"{prefix} article_id 格式无效: '{article_id}'，"
            f"应为 kb-YYYYMMDD-NNNN（如 kb-20260727-0001）"
        )

    # status 枚举
    status = data.get("status")
    if isinstance(status, str) and status not in VALID_STATUS:
        errors.append(
            f"{prefix} status 值无效: '{status}'，"
            f"应为 {sorted(VALID_STATUS)} 之一"
        )

    # source_platform 枚举
    platform = data.get("source_platform")
    if isinstance(platform, str) and platform not in VALID_PLATFORMS:
        errors.append(
            f"{prefix} source_platform 值无效: '{platform}'，"
            f"应为 {sorted(VALID_PLATFORMS)} 之一"
        )

    # category 枚举
    category = data.get("category")
    if isinstance(category, str) and category not in VALID_CATEGORIES:
        errors.append(
            f"{prefix} category 值无效: '{category}'，"
            f"应为 {sorted(VALID_CATEGORIES)} 之一"
        )

    # language 枚举
    language = data.get("language")
    if isinstance(language, str) and language not in VALID_LANGUAGES:
        errors.append(
            f"{prefix} language 值无效: '{language}'，"
            f"应为 {sorted(VALID_LANGUAGES)} 之一"
        )

    # source_url 格式
    source_url = data.get("source_url")
    if isinstance(source_url, str) and not URL_PATTERN.match(source_url):
        errors.append(
            f"{prefix} source_url 格式无效: '{source_url}'，"
            f"应以 http:// 或 https:// 开头"
        )

    # title 长度上限（对齐 §6.2: ≤60 字；DDL VARCHAR(120) 为上限）
    title = data.get("title")
    if isinstance(title, str) and len(title) > MAX_TITLE_LEN:
        errors.append(
            f"{prefix} title 过长: {len(title)} 字，"
            f"最多 {MAX_TITLE_LEN} 字"
        )

    # summary 长度范围（对齐 §6.3: 2-4 句、≤150 字；DDL VARCHAR(500) 为上限）
    summary = data.get("summary")
    if isinstance(summary, str):
        if len(summary) < MIN_SUMMARY_LEN:
            errors.append(
                f"{prefix} summary 过短: {len(summary)} 字，"
                f"最少 {MIN_SUMMARY_LEN} 字"
            )
        elif len(summary) > MAX_SUMMARY_LEN:
            errors.append(
                f"{prefix} summary 过长: {len(summary)} 字，"
                f"最多 {MAX_SUMMARY_LEN} 字"
            )

    # tags 数量 + 小写检查（对齐 §6.4）
    tags = data.get("tags")
    if isinstance(tags, list):
        if len(tags) < MIN_TAGS:
            errors.append(f"{prefix} tags 数量不足: {len(tags)} 个，最少 {MIN_TAGS} 个")
        elif len(tags) > MAX_TAGS:
            errors.append(f"{prefix} tags 数量过多: {len(tags)} 个，最多 {MAX_TAGS} 个")
        for tag in tags:
            if not isinstance(tag, str):
                errors.append(f"{prefix} tags 中存在非字符串元素: {tag!r}")
            elif tag != tag.lower():
                errors.append(f"{prefix} 标签未小写: '{tag}'")

    # collected_at 时间格式
    collected_at = data.get("collected_at")
    if isinstance(collected_at, str) and not ISO_UTC_PATTERN.match(collected_at):
        errors.append(
            f"{prefix} collected_at 格式无效: '{collected_at}'，"
            f"应为 ISO 8601 UTC（如 2026-07-27T08:00:00Z）"
        )

    # analyzed_at 时间格式（可空，非 null 时校验）
    analyzed_at = data.get("analyzed_at")
    if isinstance(analyzed_at, str) and not ISO_UTC_PATTERN.match(analyzed_at):
        errors.append(
            f"{prefix} analyzed_at 格式无效: '{analyzed_at}'，"
            f"应为 ISO 8601 UTC（如 2026-07-27T08:05:00Z）"
        )

    # published_at 时间格式（可空，非 null 时校验）
    published_at = data.get("published_at")
    if isinstance(published_at, str) and not ISO_UTC_PATTERN.match(published_at):
        errors.append(
            f"{prefix} published_at 格式无效: '{published_at}'，"
            f"应为 ISO 8601 UTC（如 2026-07-27T08:10:00Z）"
        )

    # source_score 范围（≥0）
    source_score = data.get("source_score")
    if (
        source_score is not None
        and isinstance(source_score, int)
        and not isinstance(source_score, bool)
        and source_score < SOURCE_SCORE_MIN
    ):
        errors.append(
            f"{prefix} source_score 超出范围: {source_score}，"
            f"应 >= {SOURCE_SCORE_MIN}"
        )

    # 分析 Agent 产出字段（score/score_reason/highlights，非 §4 标准字段但
    # organizer 合并写入 article JSON，对齐 tech-summary SKILL.md）
    score = data.get("score")
    if score is not None:
        if not isinstance(score, int) or isinstance(score, bool):
            errors.append(
                f"{prefix} score 类型错误: 期望 int, 实际 {type(score).__name__}"
            )
        elif not (ANALYZER_SCORE_MIN <= score <= ANALYZER_SCORE_MAX):
            errors.append(
                f"{prefix} score 超出范围: {score}，"
                f"应为 {ANALYZER_SCORE_MIN}-{ANALYZER_SCORE_MAX}"
            )

    score_reason = data.get("score_reason")
    if score_reason is not None:
        errors.extend(_check_type(score_reason, str, "score_reason", prefix))

    highlights = data.get("highlights")
    if highlights is not None:
        if not isinstance(highlights, list):
            errors.append(
                f"{prefix} 字段 'highlights' 类型错误: "
                f"期望 list, 实际 {type(highlights).__name__}"
            )
        else:
            for item in highlights:
                if not isinstance(item, str):
                    errors.append(
                        f"{prefix} highlights 中存在非字符串元素: {item!r}"
                    )

    return errors


def validate_file(file_path: Path) -> list[str]:
    """校验单个 JSON 文件，返回错误消息列表。

    Args:
        file_path: 待校验的 JSON 文件路径。

    Returns:
        错误消息列表，无错误时为空。
    """
    if not file_path.is_file():
        return [f"[{file_path}] 文件不存在或不是普通文件"]

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"[{file_path}] 文件读取失败: {exc}"]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [
            f"[{file_path}] JSON 解析失败 (行 {exc.lineno}, 列 {exc.colno}): {exc.msg}"
        ]

    return validate_entry(data, file_path)


def main(argv: list[str] | None = None) -> int:
    """脚本入口，解析命令行参数并执行批量校验。

    Args:
        argv: 命令行参数列表，默认从 sys.argv 读取。

    Returns:
        0 表示全部校验通过，1 表示存在失败。
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(
            "用法: python hooks/validate_json.py <json_file> [json_file2 ...]",
            file=sys.stderr,
        )
        return 1

    all_errors: list[str] = []
    total = 0
    passed = 0

    for arg in args:
        path = Path(arg)
        total += 1
        errors = validate_file(path)
        if errors:
            all_errors.extend(errors)
        else:
            passed += 1
            print(f"[OK] {path}")

    failed = total - passed

    # 输出汇总统计
    print("\n" + "=" * 60)
    print(f"校验汇总: 共 {total} 个文件, 通过 {passed}, 失败 {failed}")

    if all_errors:
        print("-" * 60)
        print("错误详情:")
        for err in all_errors:
            print(f"  - {err}")
        print("=" * 60)
        return 1

    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
