"""src.utils.github_api 的单元测试。

测试覆盖：
- get_repo_info 正常返回
- get_repo_info 空 owner/repo 抛 ValueError
- get_repo_info HTTP 错误抛 RuntimeError
- get_repo_info 连接错误抛 RuntimeError
- get_repo_info JSON 解析错误抛 RuntimeError
- GITHUB_TOKEN 环境变量携带认证
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from src.utils.github_api import get_repo_info


class TestGetRepoInfo:
    """get_repo_info 测试。"""

    def test_success(self) -> None:
        """正常获取仓库信息。"""
        mock_response = {
            "stargazers_count": 942,
            "forks_count": 128,
            "description": "A test repo",
        }
        mock_fp = BytesIO(json.dumps(mock_response).encode("utf-8"))

        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_fp
            result = get_repo_info("owner", "repo")

        assert result["stars"] == 942
        assert result["forks"] == 128
        assert result["description"] == "A test repo"

    def test_empty_owner_raises(self) -> None:
        """空 owner 抛 ValueError。"""
        with pytest.raises(ValueError, match="不能为空"):
            get_repo_info("", "repo")

    def test_empty_repo_raises(self) -> None:
        """空 repo 抛 ValueError。"""
        with pytest.raises(ValueError, match="不能为空"):
            get_repo_info("owner", "")

    def test_http_error_raises_runtime(self) -> None:
        """HTTP 错误抛 RuntimeError。"""
        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="https://api.github.com/repos/owner/repo",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=None,
            )
            with pytest.raises(RuntimeError, match="HTTP 404"):
                get_repo_info("owner", "repo")

    def test_url_error_raises_runtime(self) -> None:
        """连接错误抛 RuntimeError。"""
        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")
            with pytest.raises(RuntimeError, match="无法连接"):
                get_repo_info("owner", "repo")

    def test_json_decode_error_raises_runtime(self) -> None:
        """JSON 解析失败抛 RuntimeError。"""
        mock_fp = BytesIO(b"not valid json")

        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_fp
            with pytest.raises(RuntimeError, match="解析失败"):
                get_repo_info("owner", "repo")

    @patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test_token"})
    def test_token_in_env_adds_auth_header(self) -> None:
        """GITHUB_TOKEN 环境变量设置时携带认证头。"""
        mock_response = {
            "stargazers_count": 0,
            "forks_count": 0,
            "description": None,
        }
        mock_fp = BytesIO(json.dumps(mock_response).encode("utf-8"))

        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_fp
            result = get_repo_info("owner", "repo")

            # 检查 Request 对象的 headers
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.headers["Authorization"] == "Bearer ghp_test_token"

        assert result["stars"] == 0
        assert result["forks"] == 0
        assert result["description"] is None

    def test_no_description_returns_none(self) -> None:
        """无描述时 description 为 None。"""
        mock_response = {
            "stargazers_count": 10,
            "forks_count": 2,
        }
        mock_fp = BytesIO(json.dumps(mock_response).encode("utf-8"))

        with patch("src.utils.github_api.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_fp
            result = get_repo_info("owner", "repo")

        assert result["description"] is None
