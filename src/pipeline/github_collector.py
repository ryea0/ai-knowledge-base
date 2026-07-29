"""GitHub Search API 采集器。

通过 GitHub Search API（``/search/repositories``）搜索 AI/LLM/Agent 相关仓库，
按 star 数排序，提取标题/链接/热度/摘要。

限流与重试遵守 docs/specs/content-spec.md §6.1：
    - 带 Token 请求间隔 >= 0.5s，匿名 >= 2s
    - 429/5xx 指数退避重试，最多 3 次
    - 单次超时 30s
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from src.collectors.base import (
    HTTP_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    RETRY_BACKOFF_MAX,
)
from src.config.settings import get_settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com/search/repositories"

AI_KEYWORDS = [
    "llm",
    "gpt",
    "transformer",
    "fine-tuning",
    "rag",
    "agent",
    "multimodal",
    "embedding",
    "vllm",
    "langchain",
    "llama",
    "diffusion",
    "chatbot",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "mistral",
    "deepseek",
    "qwen",
]

_MIN_INTERVAL_WITH_TOKEN = 0.5
_MIN_INTERVAL_NO_TOKEN = 2.0


class GitHubCollector:
    """GitHub Search API 采集器。

    通过 GitHub Search API 搜索 AI 相关仓库，按 star 数降序排列，
    返回结构化候选列表。

    Attributes:
        limit: 最大采集条数。
        github_token: GitHub API Token（可选，提升限速）。
    """

    def __init__(
        self,
        limit: int = 20,
        *,
        github_token: str | None = None,
    ) -> None:
        """初始化 GitHub 采集器。

        Args:
            limit: 最大采集条数。
            github_token: GitHub API Token，未传入时从 Settings 读取。
        """
        self.limit = limit
        if github_token is None:
            settings = get_settings()
            github_token = settings.github_token
        self.github_token = github_token
        self._last_request_time: float = 0.0

    def collect(self) -> list[dict[str, Any]]:
        """执行采集，返回候选条目列表。

        构建 GitHub Search API 查询（AI 关键词 OR 拼接），按 star 数降序，
        截取 top N 条目。

        Returns:
            候选条目列表，每条包含:
                - ``title`` (str): 仓库名称（owner/repo）。
                - ``url`` (str): 仓库 HTML URL。
                - ``source`` (str): ``"github"``。
                - ``popularity`` (int): star 数。
                - ``summary`` (str): 仓库描述。
                - ``collected_at`` (str): 采集时间 ISO 8601 UTC。

        Raises:
            RuntimeError: 所有重试耗尽后仍失败。
        """
        query = "llm OR rag OR agent stars:>1000"
        params: dict[str, str | int] = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(self.limit, 100),
        }
        headers = self._build_headers()

        data = self._request_with_retry(GITHUB_API_BASE, params, headers)
        items = data.get("items", [])
        results: list[dict[str, Any]] = []

        for item in items[: self.limit]:
            title = item.get("full_name", "")
            url = item.get("html_url", "")
            stars = item.get("stargazers_count", 0)
            description = item.get("description") or ""

            if not title or not url:
                continue

            results.append({
                "title": title,
                "url": url,
                "source": "github",
                "popularity": stars,
                "summary": description,
                "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

        logger.info("GitHub 采集完成: %d 条候选", len(results))
        return results

    def _build_headers(self) -> dict[str, str]:
        """构建 GitHub API 请求头。

        Returns:
            包含 Accept 和可选 Authorization 的请求头字典。
        """
        headers = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        return headers

    def _request_with_retry(
        self,
        url: str,
        params: dict[str, str | int],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """带指数退避重试的 HTTP GET 请求。

        对 429/5xx 指数退避重试（初始 1s、倍增、上限 60s），最多 3 次；
        4xx（非 429）不重试。

        Args:
            url: 请求 URL。
            params: 查询参数。
            headers: 请求头。

        Returns:
            解析后的 JSON 响应字典。

        Raises:
            RuntimeError: 所有重试耗尽后仍失败。
        """
        self._rate_limit_wait()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = httpx.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=HTTP_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    self._last_request_time = time.monotonic()
                    return dict(resp.json())

                if resp.status_code == 429 or resp.status_code >= 500:
                    backoff = min(
                        RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "GitHub API %d，第 %d 次重试，等待 %.1fs",
                        resp.status_code,
                        attempt,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue

                raise RuntimeError(
                    f"GitHub API 请求失败 {resp.status_code}: {resp.text[:200]}"
                )

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    backoff = min(
                        RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "GitHub API 超时，第 %d 次重试，等待 %.1fs", attempt, backoff
                    )
                    time.sleep(backoff)
                    continue
                raise RuntimeError("GitHub API 请求超时，重试耗尽") from None

            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    backoff = min(
                        RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "GitHub API 网络错误: %s，第 %d 次重试，等待 %.1fs",
                        exc,
                        attempt,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise RuntimeError(f"GitHub API 网络错误: {exc}") from exc

        raise RuntimeError(f"GitHub API 重试 {MAX_RETRIES} 次后仍失败")

    def _rate_limit_wait(self) -> None:
        """按 GitHub API 限速策略等待。

        带 Token 间隔 >= 0.5s，匿名 >= 2s。
        """
        interval = _MIN_INTERVAL_WITH_TOKEN if self.github_token else _MIN_INTERVAL_NO_TOKEN
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed)
