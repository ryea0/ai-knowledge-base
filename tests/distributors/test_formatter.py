"""src.distributors.formatter 的单元测试。

测试覆盖：
- json_to_markdown: 单篇 Markdown 格式化
- json_to_telegram: 单篇 Telegram MarkdownV2 格式化（含转义）
- json_to_feishu: 单篇飞书 interactive 卡片
- generate_daily_digest: 当日简报（正常 / 空目录 / 无文章 / top_n）
- 工具函数: _score_indicator / _score_color / _collected_date / _escape_telegram
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.distributors.formatter import (
    _collected_date,
    _escape_telegram,
    _score_color,
    _score_indicator,
    generate_daily_digest,
    json_to_feishu,
    json_to_markdown,
    json_to_telegram,
)

_SAMPLE_ARTICLE: dict[str, Any] = {
    "article_id": "kb-20260729-0002",
    "title": "Superpowers：Agentic 技能框架与软件开发方法论",
    "source_url": "https://github.com/obra/superpowers",
    "source_platform": "github_trending",
    "source_score": 263223,
    "summary": "该仓库提出了一个实用的智能体技能框架与软件开发方法论。",
    "content_path": "",
    "tags": ["agent", "framework", "software-development", "methodology"],
    "category": "tool",
    "status": "pending",
    "language": "en",
    "collected_at": "2026-07-29T21:54:01.474672+00:00",
    "analyzed_at": "2026-07-29T21:54:01.474672+00:00",
    "published_at": None,
    "published_channels": None,
    "score": 8,
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


class TestScoreIndicator:
    """_score_indicator 测试。"""

    def test_high_score_green(self) -> None:
        assert _score_indicator(8) == "🟢"
        assert _score_indicator(10) == "🟢"

    def test_mid_score_orange(self) -> None:
        assert _score_indicator(6) == "🟟"
        assert _score_indicator(7) == "🟟"

    def test_low_score_red(self) -> None:
        assert _score_indicator(5) == "🔴"
        assert _score_indicator(1) == "🔴"


class TestScoreColor:
    """_score_color 测试。"""

    def test_high_score_green(self) -> None:
        assert _score_color(8) == "green"
        assert _score_color(10) == "green"

    def test_mid_score_yellow(self) -> None:
        assert _score_color(6) == "yellow"
        assert _score_color(7) == "yellow"

    def test_low_score_red(self) -> None:
        assert _score_color(5) == "red"
        assert _score_color(1) == "red"


class TestCollectedDate:
    """_collected_date 测试。"""

    def test_normal_iso(self) -> None:
        assert _collected_date("2026-07-29T21:54:01.474672+00:00") == "2026-07-29"

    def test_short_string(self) -> None:
        assert _collected_date("2026-07-29") == "2026-07-29"

    def test_none(self) -> None:
        assert _collected_date(None) == "未知"

    def test_empty(self) -> None:
        assert _collected_date("") == "未知"

    def test_too_short(self) -> None:
        assert _collected_date("2026") == "未知"


class TestEscapeTelegram:
    """_escape_telegram 测试。"""

    def test_escape_special_chars(self) -> None:
        assert _escape_telegram("a_b*c") == "a\\_b\\*c"

    def test_escape_all_chars(self) -> None:
        text = "_*[]()~`>#+-=|{}.!"
        expected = "".join(f"\\{c}" for c in text)
        assert _escape_telegram(text) == expected

    def test_no_escape_needed(self) -> None:
        assert _escape_telegram("hello world 123") == "hello world 123"

    def test_empty(self) -> None:
        assert _escape_telegram("") == ""


# ---------------------------------------------------------------------------
# json_to_markdown
# ---------------------------------------------------------------------------


class TestJsonToMarkdown:
    """json_to_markdown 测试。"""

    def test_basic_structure(self) -> None:
        md = json_to_markdown(_SAMPLE_ARTICLE)
        assert "## Superpowers" in md
        assert "GitHub Trending" in md
        assert "2026-07-29" in md
        assert "🟢" in md
        assert "8/10" in md
        assert "`agent`" in md
        assert "`framework`" in md
        assert "该仓库提出了一个实用的智能体技能框架与软件开发方法论。" in md
        assert "https://github.com/obra/superpowers" in md

    def test_score_indicators(self) -> None:
        article = {**_SAMPLE_ARTICLE, "score": 7}
        assert "🟟" in json_to_markdown(article)

        article = {**_SAMPLE_ARTICLE, "score": 3}
        assert "🔴" in json_to_markdown(article)

    def test_missing_fields(self) -> None:
        md = json_to_markdown({})
        assert "## " in md
        assert "未知" in md
        assert "无" in md

    def test_no_tags(self) -> None:
        article = {**_SAMPLE_ARTICLE, "tags": []}
        md = json_to_markdown(article)
        assert "无" in md

    def test_hackernews_platform(self) -> None:
        article = {**_SAMPLE_ARTICLE, "source_platform": "hackernews"}
        md = json_to_markdown(article)
        assert "Hacker News" in md


# ---------------------------------------------------------------------------
# json_to_telegram
# ---------------------------------------------------------------------------


class TestJsonToTelegram:
    """json_to_telegram 测试。"""

    def test_basic_structure(self) -> None:
        tg = json_to_telegram(_SAMPLE_ARTICLE)
        assert "Superpowers" in tg
        assert "GitHub Trending" in tg or "GitHub Trending" in tg.replace("\\", "")
        assert "2026\\-07\\-29" in tg
        assert "8/10" in tg
        assert "#agent" in tg
        assert "#framework" in tg

    def test_special_chars_escaped(self) -> None:
        article = {
            **_SAMPLE_ARTICLE,
            "title": "Test_Title[With]Special*Chars",
            "summary": "Summary (with) `backticks`",
        }
        tg = json_to_telegram(article)
        assert "Test\\_Title\\[With\\]Special\\*Chars" in tg
        assert "Summary \\(with\\) \\`backticks\\`" in tg

    def test_tags_spaces_replaced_with_underscore(self) -> None:
        article = {**_SAMPLE_ARTICLE, "tags": ["machine learning", "deep learning"]}
        tg = json_to_telegram(article)
        assert "#machine\\_learning" in tg
        assert "#deep\\_learning" in tg

    def test_url_escaped(self) -> None:
        tg = json_to_telegram(_SAMPLE_ARTICLE)
        assert "github\\.com" in tg
        assert "obra/superpowers" in tg

    def test_no_tags(self) -> None:
        article = {**_SAMPLE_ARTICLE, "tags": []}
        tg = json_to_telegram(article)
        assert "无" in tg


# ---------------------------------------------------------------------------
# json_to_feishu
# ---------------------------------------------------------------------------


class TestJsonToFeishu:
    """json_to_feishu 测试。"""

    def test_msg_type_interactive(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        assert card["msg_type"] == "interactive"

    def test_header_template_by_score(self) -> None:
        card_green = json_to_feishu({**_SAMPLE_ARTICLE, "score": 9})
        assert card_green["card"]["header"]["template"] == "green"

        card_yellow = json_to_feishu({**_SAMPLE_ARTICLE, "score": 6})
        assert card_yellow["card"]["header"]["template"] == "yellow"

        card_red = json_to_feishu({**_SAMPLE_ARTICLE, "score": 3})
        assert card_red["card"]["header"]["template"] == "red"

    def test_header_title(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        title = "Superpowers：Agentic 技能框架与软件开发方法论"
        assert card["card"]["header"]["title"]["content"] == title

    def test_elements_contain_summary(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        elements = card["card"]["elements"]
        div_texts = [
            el.get("text", {}).get("content", "") for el in elements if el.get("tag") == "div"
        ]
        assert any("该仓库提出了一个实用的智能体技能框架与软件开发方法论。" in t for t in div_texts)

    def test_elements_contain_source_and_date(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        elements = card["card"]["elements"]
        all_content = json.dumps(elements, ensure_ascii=False)
        assert "GitHub Trending" in all_content
        assert "2026-07-29" in all_content

    def test_elements_contain_tags(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        elements = card["card"]["elements"]
        all_content = json.dumps(elements, ensure_ascii=False)
        assert "#agent" in all_content
        assert "#framework" in all_content

    def test_action_button_url(self) -> None:
        card = json_to_feishu(_SAMPLE_ARTICLE)
        elements = card["card"]["elements"]
        action_els = [el for el in elements if el.get("tag") == "action"]
        assert len(action_els) == 1
        button = action_els[0]["actions"][0]
        assert button["url"] == "https://github.com/obra/superpowers"

    def test_tags_spaces_replaced(self) -> None:
        article = {**_SAMPLE_ARTICLE, "tags": ["machine learning"]}
        card = json_to_feishu(article)
        all_content = json.dumps(card, ensure_ascii=False)
        assert "#machine_learning" in all_content

    def test_missing_fields(self) -> None:
        card = json_to_feishu({})
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["template"] == "red"


# ---------------------------------------------------------------------------
# generate_daily_digest
# ---------------------------------------------------------------------------


class TestGenerateDailyDigest:
    """generate_daily_digest 测试。"""

    def test_empty_dir_returns_empty_message(self, tmp_path: Path) -> None:
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        assert result["markdown"] == "📭 2026-07-29 暂无新增知识条目"
        assert result["telegram"] == "📭 2026-07-29 暂无新增知识条目"
        assert result["feishu"] == "📭 2026-07-29 暂无新增知识条目"

    def test_dir_not_exist_returns_empty_message(self) -> None:
        result = generate_daily_digest(
            knowledge_dir="/nonexistent/path", date="2026-07-29"
        )
        assert "暂无新增知识条目" in result["markdown"]

    def test_no_matching_files_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "2026-07-28-0001.json").write_text("{}", encoding="utf-8")
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        assert "暂无新增知识条目" in result["markdown"]

    def test_single_article(self, tmp_path: Path) -> None:
        (tmp_path / "2026-07-29-0001.json").write_text(
            json.dumps(_SAMPLE_ARTICLE, ensure_ascii=False), encoding="utf-8"
        )
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        assert "AI 知识库日报" in result["markdown"]
        assert "Superpowers" in result["markdown"]
        assert "Superpowers" in result["telegram"]
        assert result["feishu"]["msg_type"] == "interactive"

    def test_top_n_sorting(self, tmp_path: Path) -> None:
        for i, score in enumerate([5, 9, 7, 10, 3]):
            article = {**_SAMPLE_ARTICLE, "article_id": f"kb-20260729-{i:04d}", "score": score}
            (tmp_path / f"2026-07-29-{i:04d}.json").write_text(
                json.dumps(article, ensure_ascii=False), encoding="utf-8"
            )
        result = generate_daily_digest(
            knowledge_dir=str(tmp_path), date="2026-07-29", top_n=3
        )
        md = result["markdown"]
        first_pos = md.find("10/10")
        second_pos = md.find("9/10")
        third_pos = md.find("7/10")
        assert first_pos < second_pos < third_pos
        assert "5/10" not in md
        assert "3/10" not in md

    def test_top_n_default_is_5(self, tmp_path: Path) -> None:
        for i in range(7):
            article = {
                **_SAMPLE_ARTICLE,
                "article_id": f"kb-20260729-{i:04d}",
                "score": 8 - i,
                "title": f"Article {i}",
            }
            (tmp_path / f"2026-07-29-{i:04d}.json").write_text(
                json.dumps(article, ensure_ascii=False), encoding="utf-8"
            )
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        md = result["markdown"]
        assert "Article 0" in md
        assert "Article 4" in md
        assert "Article 5" not in md

    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "2026-07-29-0001.json").write_text("{invalid json", encoding="utf-8")
        (tmp_path / "2026-07-29-0002.json").write_text(
            json.dumps(_SAMPLE_ARTICLE, ensure_ascii=False), encoding="utf-8"
        )
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        assert "Superpowers" in result["markdown"]

    def test_feishu_digest_has_hr_between_articles(self, tmp_path: Path) -> None:
        for i in range(3):
            article = {
                **_SAMPLE_ARTICLE,
                "article_id": f"kb-20260729-{i:04d}",
                "score": 8 - i,
                "title": f"Article {i}",
            }
            (tmp_path / f"2026-07-29-{i:04d}.json").write_text(
                json.dumps(article, ensure_ascii=False), encoding="utf-8"
            )
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        elements = result["feishu"]["card"]["elements"]
        hr_count = sum(1 for el in elements if el.get("tag") == "hr")
        assert hr_count == 2

    def test_date_none_uses_today(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        article = {**_SAMPLE_ARTICLE, "collected_at": f"{today}T00:00:00+00:00"}
        (tmp_path / f"{today}-0001.json").write_text(
            json.dumps(article, ensure_ascii=False), encoding="utf-8"
        )
        result = generate_daily_digest(knowledge_dir=str(tmp_path))
        assert "暂无" not in result["markdown"]

    def test_return_types(self, tmp_path: Path) -> None:
        (tmp_path / "2026-07-29-0001.json").write_text(
            json.dumps(_SAMPLE_ARTICLE, ensure_ascii=False), encoding="utf-8"
        )
        result = generate_daily_digest(knowledge_dir=str(tmp_path), date="2026-07-29")
        assert isinstance(result["markdown"], str)
        assert isinstance(result["telegram"], str)
        assert isinstance(result["feishu"], dict)
