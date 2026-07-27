"""GitHub API 工具模块，提供仓库信息查询功能。"""

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def get_repo_info(owner: str, repo: str) -> dict[str, int | str | None]:
    """从 GitHub API 获取指定仓库的基本信息（Star 数、Fork 数、描述）。

    通过 GitHub REST API 的 ``GET /repos/{owner}/{repo}`` 端点获取仓库元数据。
    若环境变量 ``GITHUB_TOKEN`` 已设置，将自动携带认证以提升速率限制。

    Args:
        owner: 仓库所有者用户名或组织名。
        repo: 仓库名称。

    Returns:
        包含以下键的字典：
            - ``stars``: Star 数量。
            - ``forks``: Fork 数量。
            - ``description``: 仓库描述，无描述时为 ``None``。

    Raises:
        ValueError: 当 ``owner`` 或 ``repo`` 为空字符串时。
        RuntimeError: 当 API 请求失败或响应无法解析时。
    """
    if not owner or not repo:
        raise ValueError("owner 和 repo 不能为空")

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github+json"}

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.error("GitHub API 返回 HTTP %d: %s", exc.code, exc.reason)
        raise RuntimeError(
            f"GitHub API 请求失败（HTTP {exc.code}）: {exc.reason}"
        ) from exc
    except URLError as exc:
        logger.error("无法连接 GitHub API: %s", exc.reason)
        raise RuntimeError(f"无法连接 GitHub API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        logger.error("GitHub API 响应 JSON 解析失败: %s", exc)
        raise RuntimeError("GitHub API 响应解析失败") from exc

    info: dict[str, int | str | None] = {
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "description": data.get("description"),
    }

    logger.info(
        "获取仓库 %s/%s 信息成功: stars=%d, forks=%d",
        owner,
        repo,
        info["stars"],
        info["forks"],
    )
    return info
