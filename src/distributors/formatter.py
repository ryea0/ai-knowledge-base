"""知识条目多渠道格式化模块。

将标准知识条目（dict）格式化为各渠道所需的消息格式：
    - Markdown（通用 / Web 展示）
    - Telegram（MarkdownV2）
    - 飞书 Interactive 卡片（dict，msg_type=interactive）

同时提供 ``generate_daily_digest`` 生成当日多渠道简报。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEFAULT_KNOWLEDGE_DIR = "knowledge/articles"
_DEFAULT_TOP_N = 5

_SOURCE_PLATFORM_LABELS: dict[str, str] = {
    "github_trending": "GitHub Trending",
    "hackernews": "Hacker News",
}

# Telegram MarkdownV2 需转义的字符
_TELEGRAM_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _score_indicator(score: int) -> str:
    """根据相关性评分返回 emoji 指示灯。

    Args:
        score: 1-10 的整数评分。

    Returns:
        ``>=8`` 返回 🟢，``>=6`` 返回 🟟，否则 🔴。
    """
    if score >= 8:
        return "🟢"
    if score >= 6:
        return "🟟"
    return "🔴"


def _score_color(score: int) -> str:
    """根据相关性评分返回飞书卡片 header template 颜色。

    Args:
        score: 1-10 的整数评分。

    Returns:
        ``>=8`` 返回 ``green``，``>=6`` 返回 ``yellow``，否则 ``red``。
    """
    if score >= 8:
        return "green"
    if score >= 6:
        return "yellow"
    return "red"


def _platform_label(platform: str) -> str:
    """将 source_platform 枚举值转为可读标签。"""
    return _SOURCE_PLATFORM_LABELS.get(platform, platform)


def _collected_date(collected_at: str | None) -> str:
    """从 collected_at ISO 8601 字符串截取前 10 位日期部分。

    Args:
        collected_at: ISO 8601 时间字符串，如 ``2026-07-29T21:54:01.474672+00:00``。

    Returns:
        日期部分 ``YYYY-MM-DD``，无法解析时返回 ``"未知"``。
    """
    if not collected_at or len(collected_at) < 10:
        return "未知"
    return collected_at[:10]


def _escape_telegram(text: str) -> str:
    """转义 Telegram MarkdownV2 特殊字符。

    Args:
        text: 原始文本。

    Returns:
        转义后的文本。
    """
    result: list[str] = []
    for ch in text:
        if ch in _TELEGRAM_ESCAPE_CHARS:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


# ---------------------------------------------------------------------------
# 单篇格式化
# ---------------------------------------------------------------------------


def json_to_markdown(article: dict[str, Any]) -> str:
    """将单篇知识条目格式化为 Markdown。

    Args:
        article: 标准知识条目 dict。

    Returns:
        Markdown 格式字符串，包含标题、来源、日期、相关性评分、标签、摘要、原文链接。
    """
    title = article.get("title", "")
    source_url = article.get("source_url", "")
    platform = _platform_label(article.get("source_platform", ""))
    date = _collected_date(article.get("collected_at"))
    score = article.get("score", 0) or 0
    if not isinstance(score, int):
        score = int(score)
    indicator = _score_indicator(score)
    tags = article.get("tags", [])
    summary = article.get("summary", "")

    tags_str = " ".join(f"`{tag}`" for tag in tags) if tags else "无"

    lines = [
        f"## {title}",
        "",
        f"**来源**: {platform} | **日期**: {date} | **相关性**: {indicator} {score}/10",
        "",
        f"**标签**: {tags_str}",
        "",
        f"**摘要**: {summary}",
        "",
        f"**原文链接**: [{source_url}]({source_url})",
    ]
    return "\n".join(lines)


def json_to_telegram(article: dict[str, Any]) -> str:
    """将单篇知识条目格式化为 Telegram MarkdownV2 消息。

    转义 ``_*[]()~`>#+-=|{}.!`` 等特殊字符。

    Args:
        article: 标准知识条目 dict。

    Returns:
        Telegram MarkdownV2 格式字符串。
    """
    title = article.get("title", "")
    source_url = article.get("source_url", "")
    platform = _platform_label(article.get("source_platform", ""))
    date = _collected_date(article.get("collected_at"))
    score = article.get("score", 0) or 0
    if not isinstance(score, int):
        score = int(score)
    indicator = _score_indicator(score)
    tags = article.get("tags", [])
    summary = article.get("summary", "")

    tags_str = " ".join(f"#{tag.replace(' ', '_')}" for tag in tags) if tags else "无"

    esc_title = _escape_telegram(title)
    esc_platform = _escape_telegram(platform)
    esc_date = _escape_telegram(date)
    esc_summary = _escape_telegram(summary)
    esc_source_url = _escape_telegram(source_url)
    esc_tags = _escape_telegram(tags_str)

    lines = [
        f"*{esc_title}*",
        "",
        f"来源: {esc_platform} \\| 日期: {esc_date} \\| 相关性: {indicator} {score}/10",
        "",
        f"摘要: {esc_summary}",
        "",
        f"标签: {esc_tags}",
        "",
        f"原文链接: [{esc_source_url}]({esc_source_url})",
    ]
    return "\n".join(lines)


def json_to_feishu(article: dict[str, Any]) -> dict[str, Any]:
    """将单篇知识条目格式化为飞书 Interactive 卡片消息。

    卡片 header 按 score 染色：``>=8`` green / ``>=6`` yellow / 否则 red。

    Args:
        article: 标准知识条目 dict。

    Returns:
        飞书 interactive 卡片消息 dict，结构为::

            {
                "msg_type": "interactive",
                "card": { ... }
            }
    """
    title = article.get("title", "")
    source_url = article.get("source_url", "")
    platform = _platform_label(article.get("source_platform", ""))
    date = _collected_date(article.get("collected_at"))
    score = article.get("score", 0) or 0
    if not isinstance(score, int):
        score = int(score)
    template = _score_color(score)
    tags = article.get("tags", [])
    summary = article.get("summary", "")

    tags_str = " ".join(f"#{tag.replace(' ', '_')}" for tag in tags) if tags else "无"

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": summary,
            },
        },
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**来源**\n{platform}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**日期**\n{date}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**相关性**\n{score}/10",
                    },
                },
            ],
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**标签**\n{tags_str}",
            },
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "lark_md",
                        "content": "📖 查看原文",
                    },
                    "url": source_url,
                    "type": "default",
                }
            ],
        },
    ]

    card: dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": template,
        },
        "elements": elements,
    }

    return {
        "msg_type": "interactive",
        "card": card,
    }


# ---------------------------------------------------------------------------
# 每日简报
# ---------------------------------------------------------------------------


def generate_daily_digest(
    knowledge_dir: str = _DEFAULT_KNOWLEDGE_DIR,
    date: str | None = None,
    top_n: int = _DEFAULT_TOP_N,
) -> dict[str, str | dict[str, Any]]:
    """生成当日知识简报（多渠道格式）。

    扫描 ``knowledge_dir`` 下 ``kb-{date_compact}-*.json`` 文件
    （``date_compact`` 为 ``YYYYMMDD`` 格式），按 ``score`` 降序取 Top N，
    分别生成 Markdown / Telegram / 飞书三种格式的简报。

    Args:
        knowledge_dir: 知识条目目录，默认 ``knowledge/articles``。
        date: 日期字符串 ``YYYY-MM-DD``，``None`` 时默认当天（UTC）。
        top_n: 取前 N 篇，默认 5。

    Returns:
        dict 包含三个键::

            {
                "markdown": "...",       # Markdown 简报
                "telegram": "...",       # Telegram MarkdownV2 简报
                "feishu": {...},         # 飞书 interactive 卡片
            }

        当日无文章时，各渠道均返回 ``"📭 {date} 暂无新增知识条目"``。
    """
    if date is None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")

    dir_path = Path(knowledge_dir)
    if not dir_path.is_dir():
        empty_msg = f"📭 {date} 暂无新增知识条目"
        return {"markdown": empty_msg, "telegram": empty_msg, "feishu": empty_msg}

    articles: list[dict[str, Any]] = []
    date_compact = date.replace("-", "")
    for json_file in sorted(dir_path.glob(f"kb-{date_compact}-*.json")):
        try:
            with open(json_file, encoding="utf-8") as f:
                article = json.load(f)
            articles.append(article)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取文件失败 %s: %s", json_file, exc)
            continue

    if not articles:
        empty_msg = f"📭 {date} 暂无新增知识条目"
        return {"markdown": empty_msg, "telegram": empty_msg, "feishu": empty_msg}

    articles.sort(key=lambda a: a.get("score", 0) or 0, reverse=True)
    top_articles = articles[:top_n]

    md_parts = [f"# 📚 AI 知识库日报 - {date}", ""]
    tg_parts: list[str] = []
    feishu_elements: list[dict[str, Any]] = []

    for idx, article in enumerate(top_articles, 1):
        md_parts.append(json_to_markdown(article))
        md_parts.append("")
        md_parts.append("---")
        md_parts.append("")

        tg_parts.append(json_to_telegram(article))
        tg_parts.append("")
        tg_parts.append("\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-")
        tg_parts.append("")

        feishu_card = json_to_feishu(article)
        card_elements = feishu_card.get("card", {}).get("elements", [])
        feishu_elements.extend(card_elements)
        if idx < len(top_articles):
            feishu_elements.append({"tag": "hr"})

    md_digest = "\n".join(md_parts)
    tg_digest = "\n".join(tg_parts)

    feishu_digest: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📚 AI 知识库日报 - {date}（Top {len(top_articles)}）",
                },
                "template": "blue",
            },
            "elements": feishu_elements,
        },
    }

    return {
        "markdown": md_digest,
        "telegram": tg_digest,
        "feishu": feishu_digest,
    }
