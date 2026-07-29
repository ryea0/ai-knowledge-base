"""src.pipeline.github_collector 的单元测试。

测试覆盖：
- GitHubCollector.collect 正常采集
- 请求头构建（含/不含 Token）
- 重试逻辑（429/5xx/超时）
- 限速等待
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.pipeline.github_collector import GitHubCollector


class TestGitHubCollectorHeaders:
    """请求头构建测试。"""

    def test_headers_with_token(self) -> None:
        """有 Token 时包含 Authorization 头。"""
        collector = GitHubCollector(limit=5, github_token="ghp_test_token")
        headers = collector._build_headers()
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["Authorization"] == "Bearer ghp_test_token"

    def test_headers_without_token(self) -> None:
        """无 Token 时不包含 Authorization 头。"""
        with patch("src.pipeline.github_collector.get_settings") as mock_settings:
            mock_settings.return_value.github_token = None
            collector = GitHubCollector(limit=5, github_token=None)
            headers = collector._build_headers()
            assert "Authorization" not in headers
            assert headers["Accept"] == "application/vnd.github+json"


class TestGitHubCollectorCollect:
    """collect 方法测试。"""

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_success(self, mock_settings: MagicMock, mock_get: MagicMock) -> None:
        """正常采集返回候选列表。"""
        mock_settings.return_value.github_token = None
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "full_name": "langchain-ai/langchain",
                    "html_url": "https://github.com/langchain-ai/langchain",
                    "stargazers_count": 99000,
                    "description": "Build context-aware reasoning applications",
                },
                {
                    "full_name": "vllm-project/vllm",
                    "html_url": "https://github.com/vllm-project/vllm",
                    "stargazers_count": 28000,
                    "description": "A high-throughput and memory-efficient LLM engine",
                },
            ]
        }
        mock_get.return_value = mock_resp

        collector = GitHubCollector(limit=10, github_token=None)
        results = collector.collect()

        assert len(results) == 2
        assert results[0]["title"] == "langchain-ai/langchain"
        assert results[0]["url"] == "https://github.com/langchain-ai/langchain"
        assert results[0]["source"] == "github"
        assert results[0]["popularity"] == 99000
        assert "collected_at" in results[0]

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_respects_limit(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """limit 参数限制返回条数。"""
        mock_settings.return_value.github_token = None
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "full_name": f"repo-{i}",
                    "html_url": f"https://github.com/repo-{i}",
                    "stargazers_count": 100 - i,
                    "description": f"Repo {i}",
                }
                for i in range(10)
            ]
        }
        mock_get.return_value = mock_resp

        collector = GitHubCollector(limit=3, github_token=None)
        results = collector.collect()

        assert len(results) == 3

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_skips_items_without_url(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """缺少 url 的条目被跳过。"""
        mock_settings.return_value.github_token = None
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "full_name": "valid/repo",
                    "html_url": "https://github.com/valid/repo",
                    "stargazers_count": 100,
                    "description": "Valid repo",
                },
                {
                    "full_name": "no-url/repo",
                    "html_url": "",
                    "stargazers_count": 50,
                    "description": "No URL",
                },
            ]
        }
        mock_get.return_value = mock_resp

        collector = GitHubCollector(limit=10, github_token=None)
        results = collector.collect()

        assert len(results) == 1
        assert results[0]["title"] == "valid/repo"

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_retries_on_429(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """429 状态码触发重试。"""
        mock_settings.return_value.github_token = None
        retry_resp = MagicMock()
        retry_resp.status_code = 429
        retry_resp.text = "Rate limited"

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"items": []}

        mock_get.side_effect = [retry_resp, success_resp]

        collector = GitHubCollector(limit=5, github_token=None)
        results = collector.collect()

        assert mock_get.call_count == 2
        assert results == []

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_retries_on_500(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """500 状态码触发重试。"""
        mock_settings.return_value.github_token = None
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"items": []}

        mock_get.side_effect = [error_resp, success_resp]

        collector = GitHubCollector(limit=5, github_token=None)
        collector.collect()

        assert mock_get.call_count == 2

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_fails_on_404(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """404 状态码不重试，直接报错。"""
        mock_settings.return_value.github_token = None
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.text = "Not Found"

        mock_get.return_value = error_resp

        collector = GitHubCollector(limit=5, github_token=None)
        with pytest.raises(RuntimeError, match="404"):
            collector.collect()

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_retries_on_timeout(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """超时触发重试。"""
        mock_settings.return_value.github_token = None
        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"items": []}

        mock_get.side_effect = [
            httpx.TimeoutException("timeout"),
            success_resp,
        ]

        collector = GitHubCollector(limit=5, github_token=None)
        results = collector.collect()

        assert mock_get.call_count == 2
        assert results == []

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_retries_on_network_error(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """网络错误触发重试。"""
        mock_settings.return_value.github_token = None
        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"items": []}

        mock_get.side_effect = [
            httpx.RequestError("connection reset"),
            success_resp,
        ]

        collector = GitHubCollector(limit=5, github_token=None)
        collector.collect()

        assert mock_get.call_count == 2

    @patch("src.pipeline.github_collector.httpx.get")
    @patch("src.pipeline.github_collector.get_settings")
    def test_collect_raises_after_max_retries(
        self, mock_settings: MagicMock, mock_get: MagicMock
    ) -> None:
        """重试耗尽后抛出 RuntimeError。"""
        mock_settings.return_value.github_token = None
        mock_get.side_effect = httpx.TimeoutException("timeout")

        collector = GitHubCollector(limit=5, github_token=None)
        with pytest.raises(RuntimeError, match="超时"):
            collector.collect()

        assert mock_get.call_count == 3
