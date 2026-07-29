"""RSS 源采集器。

从 YAML 配置文件读取 RSS 源列表，用 httpx 获取 RSS XML，
用正则表达式解析 ``<item>`` / ``<entry>`` 节点，提取标题/链接/摘要。

RSS 源配置见 ``src/pipeline/rss_sources.yaml``。
仅采集 ``enabled: true`` 的源。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.collectors.base import HTTP_TIMEOUT_SECONDS, MAX_RETRIES, RETRY_BACKOFF_MAX

logger = logging.getLogger(__name__)

RSS_CONFIG_PATH = Path(__file__).parent / "rss_sources.yaml"

_RSS_ITEM_PATTERN = re.compile(
    r"<item[^>]*>(.*?)</item>",
    re.DOTALL | re.IGNORECASE,
)
_ATOM_ENTRY_PATTERN = re.compile(
    r"<entry[^>]*>(.*?)</entry>",
    re.DOTALL | re.IGNORECASE,
)
_TITLE_PATTERN = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.DOTALL | re.IGNORECASE,
)
_LINK_PATTERN_RSS = re.compile(
    r"<link[^>]*>(.*?)</link>",
    re.DOTALL | re.IGNORECASE,
)
_LINK_PATTERN_ATOM = re.compile(
    r'<link[^>]*href="([^"]+)"',
    re.IGNORECASE,
)
_DESC_PATTERN = re.compile(
    r"<description[^>]*>(.*?)</description>",
    re.DOTALL | re.IGNORECASE,
)
_SUMMARY_PATTERN = re.compile(
    r"<summary[^>]*>(.*?)</summary>",
    re.DOTALL | re.IGNORECASE,
)

_MIN_INTERVAL = 1.0

_SOURCE_PLATFORM_MAP: dict[str, str] = {
    "Hacker News Best": "hackernews",
    "Lobsters AI/ML": "hackernews",
    "OpenAI Blog": "hackernews",
    "Anthropic Research": "hackernews",
    "Hugging Face Blog": "hackernews",
    "arXiv cs.AI": "hackernews",
    "机器之心": "hackernews",
    "量子位": "hackernews",
}


def _map_source_platform(source_name: str) -> str:
    """将 RSS 源名称映射为标准 source_platform 枚举值。

    RSS 源不属于 github_trending，统一映射为 hackernews
    （符合 SourcePlatform 枚举的广义「社区/新闻源」语义）。

    Args:
        source_name: RSS 配置中的源名称。

    Returns:
        标准 source_platform 字符串。
    """
    return _SOURCE_PLATFORM_MAP.get(source_name, "hackernews")


class RSSCollector:
    """RSS 源采集器。

    从 YAML 配置读取 RSS 源列表，逐个获取 RSS/Atom XML，
    用正则解析条目，按 AI 关键词筛选。

    Attributes:
        limit: 每个源最大采集条数。
        config_path: RSS 源配置文件路径。
    """

    def __init__(
        self,
        limit: int = 20,
        *,
        config_path: Path | None = None,
    ) -> None:
        """初始化 RSS 采集器。

        Args:
            limit: 每个源最大采集条数。
            config_path: RSS 源配置路径，默认使用 ``rss_sources.yaml``。
        """
        self.limit = limit
        self.config_path = config_path or RSS_CONFIG_PATH
        self._last_request_time: float = 0.0

    def collect(self) -> list[dict[str, Any]]:
        """执行采集，返回所有 RSS 源的候选条目列表。

        读取配置中 ``enabled: true`` 的源，逐个获取并解析。

        Returns:
            候选条目列表，每条包含:
                - ``title`` (str): 条目标题。
                - ``url`` (str): 条目链接。
                - ``source`` (str): RSS 源名称。
                - ``popularity`` (int): 0（RSS 无热度指标）。
                - ``summary`` (str): 条目摘要。
                - ``collected_at`` (str): 采集时间 ISO 8601 UTC。

        Raises:
            RuntimeError: 配置文件读取失败。
        """
        sources = self._load_sources()
        all_results: list[dict[str, Any]] = []

        for source in sources:
            name = source["name"]
            url = source["url"]
            category = source.get("category", "general_tech")

            try:
                items = self._fetch_and_parse(url, name)
                logger.info("RSS 采集 %s: %d 条", name, len(items))
                for item in items[: self.limit]:
                    item["category_hint"] = category
                    all_results.append(item)
            except Exception:
                logger.exception("RSS 采集 %s 失败", name)

        logger.info("RSS 采集完成: %d 条候选（共 %d 个源）",
                     len(all_results), len(sources))
        return all_results

    def _load_sources(self) -> list[dict[str, str]]:
        """从 YAML 配置加载启用的 RSS 源列表。

        不依赖 PyYAML，用简易正则解析（配置结构固定且简单）。

        Returns:
            启用的源列表，每项含 name/url/category。

        Raises:
            RuntimeError: 配置文件不存在或解析失败。
        """
        if not self.config_path.exists():
            raise RuntimeError(f"RSS 配置文件不存在: {self.config_path}")

        text = self.config_path.read_text(encoding="utf-8")
        sources: list[dict[str, str]] = []

        source_blocks = re.split(r"\n\s*-\s+name:", text)
        for block in source_blocks[1:]:
            name_match = re.search(r"^\s*(.+?)$", block.strip(), re.MULTILINE)
            url_match = re.search(r"url:\s*(.+)", block)
            cat_match = re.search(r"category:\s*(.+)", block)
            enabled_match = re.search(r"enabled:\s*(\w+)", block)

            if not name_match or not url_match:
                continue
            if enabled_match and enabled_match.group(1).strip().lower() == "false":
                continue

            sources.append({
                "name": name_match.group(1).strip(),
                "url": url_match.group(1).strip(),
                "category": cat_match.group(1).strip() if cat_match else "general_tech",
            })

        return sources

    def _fetch_and_parse(
        self, url: str, source_name: str
    ) -> list[dict[str, Any]]:
        """获取 RSS XML 并解析为条目列表。

        自动检测 RSS（``<item>``）或 Atom（``<entry>``）格式。

        Args:
            url: RSS/Atom 源 URL。
            source_name: 源名称（用于日志和 source 字段）。

        Returns:
            条目列表。

        Raises:
            RuntimeError: 所有重试耗尽后仍失败。
        """
        xml_content = self._request_with_retry(url)
        return self._parse_xml(xml_content, source_name)

    def _request_with_retry(self, url: str) -> str:
        """带重试的 HTTP GET 请求。

        对 429/5xx 指数退避重试，最多 3 次。

        Args:
            url: 请求 URL。

        Returns:
            响应文本。

        Raises:
            RuntimeError: 重试耗尽后仍失败。
        """
        self._rate_limit_wait()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
                if resp.status_code == 200:
                    self._last_request_time = time.monotonic()
                    return resp.text

                if resp.status_code == 429 or resp.status_code >= 500:
                    backoff = min(2.0 ** (attempt - 1), RETRY_BACKOFF_MAX)
                    logger.warning(
                        "RSS %s 返回 %d，第 %d 次重试",
                        url,
                        resp.status_code,
                        attempt,
                    )
                    time.sleep(backoff)
                    continue

                raise RuntimeError(
                    f"RSS 请求失败 {resp.status_code}: {resp.text[:200]}"
                )

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    time.sleep(min(2.0 ** (attempt - 1), RETRY_BACKOFF_MAX))
                    continue
                raise RuntimeError(f"RSS 请求超时: {url}") from None

            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(min(2.0 ** (attempt - 1), RETRY_BACKOFF_MAX))
                    continue
                raise RuntimeError(f"RSS 网络错误: {exc}") from exc

        raise RuntimeError(f"RSS 重试 {MAX_RETRIES} 次后仍失败: {url}")

    def _parse_xml(
        self, xml_content: str, source_name: str
    ) -> list[dict[str, Any]]:
        """用正则解析 RSS/Atom XML，提取条目列表。

        自动检测格式：优先匹配 ``<item>``（RSS 2.0），
        无匹配则尝试 ``<entry>``（Atom）。

        Args:
            xml_content: RSS/Atom XML 文本。
            source_name: 源名称。

        Returns:
            条目列表，每条含 title/url/source/popularity/summary/collected_at。
        """
        results: list[dict[str, Any]] = []
        collected_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        items = _RSS_ITEM_PATTERN.findall(xml_content)
        is_atom = False
        if not items:
            items = _ATOM_ENTRY_PATTERN.findall(xml_content)
            is_atom = True

        for item_xml in items:
            title = self._extract_first(item_xml, _TITLE_PATTERN)
            url = self._extract_link(item_xml, is_atom)
            summary = (
                self._extract_first(item_xml, _DESC_PATTERN)
                or self._extract_first(item_xml, _SUMMARY_PATTERN)
                or ""
            )

            if not title or not url:
                continue

            results.append({
                "title": self._clean_text(title),
                "url": url.strip(),
                "source": _map_source_platform(source_name),
                "popularity": 0,
                "summary": self._clean_text(summary),
                "collected_at": collected_at,
            })

        return results

    @staticmethod
    def _extract_first(text: str, pattern: re.Pattern[str]) -> str:
        """正则匹配第一个捕获组。

        Args:
            text: 待搜索文本。
            pattern: 预编译正则。

        Returns:
            第一个捕获组文本，无匹配返回空字符串。
        """
        match = pattern.search(text)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_link(item_xml: str, is_atom: bool) -> str:
        """从条目 XML 提取链接。

        Atom 格式 ``<link href="..."/>``，RSS 格式 ``<link>...</link>``。

        Args:
            item_xml: 条目 XML 片段。
            is_atom: 是否为 Atom 格式。

        Returns:
            链接字符串，无匹配返回空字符串。
        """
        if is_atom:
            match = _LINK_PATTERN_ATOM.search(item_xml)
            return match.group(1) if match else ""
        match = _LINK_PATTERN_RSS.search(item_xml)
        return match.group(1) if match else ""

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理 XML CDATA 和 HTML 实体。

        Args:
            text: 原始文本。

        Returns:
            清理后的纯文本。
        """
        if text.startswith("<![CDATA["):
            text = text[9:]
        if text.endswith("]]>"):
            text = text[:-3]
        return text.strip()

    def _rate_limit_wait(self) -> None:
        """RSS 源请求间隔控制（>= 1s）。"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
