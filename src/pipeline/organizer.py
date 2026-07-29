"""知识整理器。

对采集+分析产出执行去重检查、格式标准化、字段校验，
并将原始内容写入 ``knowledge/raw/``，最终条目写入 ``knowledge/articles/``。

去重策略：检查 ``knowledge/articles/`` 中是否已有相同 ``source_url`` 的条目。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"


class Organizer:
    """知识整理器。

    负责去重检查、格式标准化、原始内容存盘和结构化条目存盘。

    Attributes:
        raw_dir: 原始内容目录。
        articles_dir: 结构化条目目录。
    """

    def __init__(
        self,
        *,
        raw_dir: Path | None = None,
        articles_dir: Path | None = None,
    ) -> None:
        """初始化整理器。

        Args:
            raw_dir: 原始内容目录，默认 ``knowledge/raw/``。
            articles_dir: 条目目录，默认 ``knowledge/articles/``。
        """
        self.raw_dir = raw_dir or RAW_DIR
        self.articles_dir = articles_dir or ARTICLES_DIR
        self._ensure_dirs()

    def organize(
        self,
        collected_meta: dict[str, Any],
        analysis_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """整理单条知识条目。

        流程：
            1. 去重检查（按 source_url 查已存条目）。
            2. 生成 article_id。
            3. 写原始内容到 ``knowledge/raw/<article_id>.md``。
            4. 格式化标准条目 JSON。
            5. 写入 ``knowledge/articles/<article_id>.json``。

        Args:
            collected_meta: 采集元信息（title/url/source/popularity/summary/collected_at）。
            analysis_result: 分析产出（summary/highlights/score/tags/category/language）。

        Returns:
            格式化后的标准知识条目 dict；重复则返回 None。
        """
        source_url = collected_meta.get("url", "")
        if self._is_duplicate(source_url):
            logger.info("跳过重复条目: %s", source_url)
            return None

        article_id = self._generate_article_id()
        collected_at = collected_meta.get(
            "collected_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        analyzed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        content_path = self._write_raw_content(article_id, collected_meta)
        relative_content_path = self._relative_to_project(content_path)

        article = {
            "article_id": article_id,
            "title": collected_meta.get("title", ""),
            "source_url": source_url,
            "source_platform": collected_meta.get("source", ""),
            "source_score": collected_meta.get("popularity", 0),
            "summary": analysis_result.get("summary", ""),
            "content_path": relative_content_path,
            "tags": analysis_result.get("tags", []),
            "category": analysis_result.get("category", "news"),
            "status": "pending",
            "language": analysis_result.get("language", "en"),
            "collected_at": collected_at,
            "analyzed_at": analyzed_at,
            "published_at": None,
            "published_channels": None,
            "highlights": analysis_result.get("highlights", []),
            "score": analysis_result.get("score", 0),
        }

        self._write_article_json(article_id, article)
        logger.info("条目已保存: %s -> %s", article_id, article["title"])
        return article

    def _is_duplicate(self, source_url: str) -> bool:
        """检查 source_url 是否已存在于 articles 目录。

        扫描所有已存条目 JSON，匹配 ``source_url`` 字段。

        Args:
            source_url: 待检查的 URL。

        Returns:
            True 表示已存在（重复）。
        """
        if not source_url:
            return False

        for json_file in self.articles_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if data.get("source_url") == source_url:
                    return True
            except (json.JSONDecodeError, OSError):
                continue

        return False

    @staticmethod
    def _generate_article_id() -> str:
        """生成 article_id。

        格式: ``kb-YYYYMMDD-<8位hex>``。
        不依赖 DB 自增主键（pipeline 独立运行场景），
        使用 UUID 前 8 位 hex 保证唯一性。

        Returns:
            article_id 字符串。
        """
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        unique = uuid.uuid4().hex[:8]
        return f"kb-{date_str}-{unique}"

    def _write_raw_content(
        self,
        article_id: str,
        collected_meta: dict[str, Any],
    ) -> Path:
        """将原始内容写入 ``knowledge/raw/<article_id>.md``。

        Markdown 格式：包含来源标题、URL、描述、采集时间。

        Args:
            article_id: 条目 ID。
            collected_meta: 采集元信息。

        Returns:
            写入的文件路径（绝对路径）。
        """
        content = f"""# {collected_meta.get("title", "")}

- **Source**: {collected_meta.get("source", "")}
- **URL**: {collected_meta.get("url", "")}
- **Popularity**: {collected_meta.get("popularity", 0)}
- **Collected At**: {collected_meta.get("collected_at", "")}

---

{collected_meta.get("summary", "")}

## Raw Content

{collected_meta.get("summary", "")}

> This raw content was collected by the pipeline and may contain the original
> description from the source platform. For the full article, visit the URL above.
"""
        file_path = self.raw_dir / f"{article_id}.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _write_article_json(
        self,
        article_id: str,
        article: dict[str, Any],
    ) -> None:
        """将结构化条目写入 ``knowledge/articles/<article_id>.json``。

        Args:
            article_id: 条目 ID。
            article: 完整的条目 dict。
        """
        file_path = self.articles_dir / f"{article_id}.json"
        file_path.write_text(
            json.dumps(article, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_dirs(self) -> None:
        """确保 raw 和 articles 目录存在。"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.articles_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _relative_to_project(path: Path) -> str:
        """将路径转为相对项目根目录的字符串。

        若路径不在项目根目录下（如测试中的 tmp_path），返回绝对路径。

        Args:
            path: 文件路径。

        Returns:
            相对路径字符串或绝对路径字符串。
        """
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)
