"""src.pipeline.organizer 的单元测试。

测试覆盖：
- 去重检查（source_url 匹配）
- article_id 生成
- 原始内容写入
- 条目 JSON 写入
- organize 完整流程
"""

from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.organizer import Organizer


class TestOrganizerDedup:
    """去重检查测试。"""

    def test_no_duplicate(self, tmp_path: Path) -> None:
        """无已有条目时返回 False。"""
        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=tmp_path / "articles")
        assert not organizer._is_duplicate("https://github.com/new/repo")

    def test_duplicate_exists(self, tmp_path: Path) -> None:
        """已存在相同 source_url 返回 True。"""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir(parents=True)
        existing = {
            "article_id": "kb-20260101-aabbccdd",
            "source_url": "https://github.com/dup/repo",
        }
        (articles_dir / "kb-20260101-aabbccdd.json").write_text(
            json.dumps(existing), encoding="utf-8"
        )

        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=articles_dir)
        assert organizer._is_duplicate("https://github.com/dup/repo")

    def test_different_url_not_duplicate(self, tmp_path: Path) -> None:
        """不同 URL 不算重复。"""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir(parents=True)
        existing = {
            "article_id": "kb-20260101-aabbccdd",
            "source_url": "https://github.com/other/repo",
        }
        (articles_dir / "kb-20260101-aabbccdd.json").write_text(
            json.dumps(existing), encoding="utf-8"
        )

        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=articles_dir)
        assert not organizer._is_duplicate("https://github.com/new/repo")

    def test_empty_url_not_duplicate(self, tmp_path: Path) -> None:
        """空 URL 不进行去重检查。"""
        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=tmp_path / "articles")
        assert not organizer._is_duplicate("")

    def test_corrupt_json_ignored(self, tmp_path: Path) -> None:
        """损坏的 JSON 文件被忽略。"""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir(parents=True)
        (articles_dir / "corrupt.json").write_text("not json", encoding="utf-8")

        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=articles_dir)
        assert not organizer._is_duplicate("https://github.com/any/repo")


class TestOrganizerArticleId:
    """article_id 生成测试。"""

    def test_id_format(self) -> None:
        """article_id 格式为 kb-YYYYMMDD-8位hex。"""
        aid = Organizer._generate_article_id()
        assert aid.startswith("kb-")
        parts = aid.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8
        assert len(parts[2]) == 8
        int(parts[2], 16)

    def test_id_unique(self) -> None:
        """连续生成的 article_id 不同。"""
        ids = {Organizer._generate_article_id() for _ in range(100)}
        assert len(ids) == 100


class TestOrganizerWriteRaw:
    """原始内容写入测试。"""

    def test_write_raw_content(self, tmp_path: Path) -> None:
        """原始内容写入 Markdown 文件。"""
        raw_dir = tmp_path / "raw"
        organizer = Organizer(raw_dir=raw_dir, articles_dir=tmp_path / "articles")
        meta = {
            "title": "Test Repo",
            "url": "https://github.com/test/repo",
            "source": "github",
            "popularity": 100,
            "summary": "A test repository",
            "collected_at": "2026-07-29T00:00:00Z",
        }

        path = organizer._write_raw_content("kb-20260729-aabbccdd", meta)

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Test Repo" in content
        assert "https://github.com/test/repo" in content
        assert "A test repository" in content

    def test_write_raw_creates_dir(self, tmp_path: Path) -> None:
        """raw 目录不存在时自动创建。"""
        raw_dir = tmp_path / "raw" / "nested"
        organizer = Organizer(raw_dir=raw_dir, articles_dir=tmp_path / "articles")
        meta = {"title": "T", "url": "U", "source": "s", "summary": "d"}

        path = organizer._write_raw_content("kb-20260729-aabbccdd", meta)

        assert path.exists()
        assert raw_dir.exists()


class TestOrganizerWriteArticle:
    """条目 JSON 写入测试。"""

    def test_write_article_json(self, tmp_path: Path) -> None:
        """条目 JSON 正确写入。"""
        articles_dir = tmp_path / "articles"
        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=articles_dir)
        article = {
            "article_id": "kb-20260729-aabbccdd",
            "title": "Test",
            "source_url": "https://example.com",
        }

        organizer._write_article_json("kb-20260729-aabbccdd", article)

        path = articles_dir / "kb-20260729-aabbccdd.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["article_id"] == "kb-20260729-aabbccdd"
        assert data["title"] == "Test"


class TestOrganizerOrganize:
    """organize 完整流程测试。"""

    def test_organize_success(self, tmp_path: Path) -> None:
        """完整整理流程：去重 -> 生成ID -> 写raw -> 写article。"""
        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=tmp_path / "articles")
        meta = {
            "title": "LangChain",
            "url": "https://github.com/langchain-ai/langchain",
            "source": "github",
            "popularity": 99000,
            "summary": "Build context-aware reasoning applications",
            "collected_at": "2026-07-29T08:00:00Z",
        }
        analysis = {
            "summary": "LangChain 是一个用于构建 LLM 应用的框架",
            "highlights": ["支持多种 LLM", "链式调用"],
            "score": 8,
            "tags": ["llm", "langchain", "framework"],
            "category": "tool",
            "language": "en",
        }

        result = organizer.organize(meta, analysis)

        assert result is not None
        assert result["title"] == "LangChain"
        assert result["source_url"] == "https://github.com/langchain-ai/langchain"
        assert result["status"] == "pending"
        assert result["score"] == 8
        assert result["category"] == "tool"
        assert result["tags"] == ["llm", "langchain", "framework"]

        raw_file = tmp_path / "raw" / f"{result['article_id']}.md"
        assert raw_file.exists()

        article_file = tmp_path / "articles" / f"{result['article_id']}.json"
        assert article_file.exists()
        saved = json.loads(article_file.read_text(encoding="utf-8"))
        assert saved["article_id"] == result["article_id"]

    def test_organize_duplicate_returns_none(self, tmp_path: Path) -> None:
        """重复条目返回 None。"""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir(parents=True)
        existing = {
            "article_id": "kb-20260101-aabbccdd",
            "source_url": "https://github.com/dup/repo",
        }
        (articles_dir / "kb-20260101-aabbccdd.json").write_text(
            json.dumps(existing), encoding="utf-8"
        )

        organizer = Organizer(raw_dir=tmp_path / "raw", articles_dir=articles_dir)
        meta = {"url": "https://github.com/dup/repo", "title": "Dup"}
        analysis = {"summary": "test", "tags": ["ai"], "category": "news", "score": 5}

        result = organizer.organize(meta, analysis)

        assert result is None

    def test_organize_content_path_relative(self, tmp_path: Path) -> None:
        """content_path 为相对路径（raw_dir 在项目根目录下时）。"""
        import uuid

        from src.pipeline.organizer import PROJECT_ROOT

        raw_dir = PROJECT_ROOT / "knowledge" / "raw"
        articles_dir = PROJECT_ROOT / "knowledge" / "articles"
        organizer = Organizer(raw_dir=raw_dir, articles_dir=articles_dir)
        unique_url = f"https://test-relative-{uuid.uuid4().hex[:8]}.example.com"
        meta = {
            "title": "T",
            "url": unique_url,
            "source": "github",
            "summary": "d",
        }
        analysis = {
            "summary": "s",
            "tags": ["ai"],
            "category": "news",
            "score": 5,
            "language": "en",
        }

        result = organizer.organize(meta, analysis)

        assert result is not None
        assert not result["content_path"].startswith("/")
        assert result["content_path"].startswith("knowledge/raw/")

        # Cleanup test artifacts
        raw_file = raw_dir / f"{result['article_id']}.md"
        article_file = articles_dir / f"{result['article_id']}.json"
        raw_file.unlink(missing_ok=True)
        article_file.unlink(missing_ok=True)
