"""知识库交互 Bot 模块。

提供基于规则意图识别的交互式知识库查询与订阅服务。
整合搜索引擎、订阅管理和权限控制三大子模块，通过统一的
``handle_message`` 入口处理用户命令与自然语言输入。

核心组件：
    - :class:`KnowledgeSearchEngine` -- 知识库搜索引擎（关键词/标签/日期过滤）
    - :class:`SubscriptionManager` -- 用户订阅管理（增删查）
    - :class:`PermissionManager` -- 三级权限控制（READ/WRITE/DELETE）
    - :class:`KnowledgeBot` -- 整合以上模块的主入口

数据来源：从 ``knowledge/articles/`` 目录读取 JSON 知识条目文件
（与 :mod:`src.distributors.formatter` 保持一致的读取方式）。

意图识别采用纯规则匹配（命令前缀 + 自然语言关键词），不依赖 LLM。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEFAULT_KNOWLEDGE_DIR = "knowledge/articles"
_DEFAULT_LIMIT = 10
_DEFAULT_TOP_N = 5
_MAX_LIMIT = 50
_SUB_ID_PREFIX = "sub-"

# ---------------------------------------------------------------------------
# 意图 -> 所需权限映射
# ---------------------------------------------------------------------------

_INTENT_PERMISSIONS: dict[BotIntent, PermissionLevel | None] = {}  # 延迟填充，见文件末尾


# ---------------------------------------------------------------------------
# 枚举定义
# ---------------------------------------------------------------------------


class BotIntent(Enum):
    """Bot 意图类型。

    由 :meth:`KnowledgeBot.recognize_intent` 返回，用于驱动后续处理器分发。

    Attributes:
        SEARCH: 搜索知识条目（关键词/标签/日期）。
        TODAY: 查看今日新增条目。
        TOP: 查看热门条目（按评分排序）。
        SUBSCRIBE: 订阅管理（新增/查看/取消订阅）。
        HELP: 查看帮助信息。
        UNKNOWN: 未识别意图。
    """

    SEARCH = "search"
    TODAY = "today"
    TOP = "top"
    SUBSCRIBE = "subscribe"
    HELP = "help"
    UNKNOWN = "unknown"


class PermissionLevel(IntEnum):
    """用户权限级别（三级权限控制）。

    数值越大权限越高，高级别自动包含低级别权限
    （如拥有 ``WRITE`` 的用户自动满足 ``READ`` 要求）。

    Attributes:
        READ: 只读权限（搜索、查看今日/热门）。
        WRITE: 写入权限（订阅管理），包含 READ。
        DELETE: 删除权限，包含 READ 和 WRITE。
    """

    READ = 1
    WRITE = 2
    DELETE = 3

    def includes(self, other: PermissionLevel) -> bool:
        """判断当前权限级别是否包含指定权限。

        Args:
            other: 需要检查的权限级别。

        Returns:
            当前级别 >= 指定级别时返回 ``True``。
        """
        return self.value >= other.value


# ---------------------------------------------------------------------------
# 命令前缀与自然语言关键词映射
# ---------------------------------------------------------------------------

_COMMAND_MAP: dict[str, BotIntent] = {
    "/search": BotIntent.SEARCH,
    "/today": BotIntent.TODAY,
    "/top": BotIntent.TOP,
    "/subscribe": BotIntent.SUBSCRIBE,
    "/help": BotIntent.HELP,
}

# 自然语言关键词映射（按优先级排序，先匹配先返回）
_NL_KEYWORDS: list[tuple[str, BotIntent]] = [
    ("取消订阅", BotIntent.SUBSCRIBE),
    ("退订", BotIntent.SUBSCRIBE),
    ("搜索", BotIntent.SEARCH),
    ("查询", BotIntent.SEARCH),
    ("查找", BotIntent.SEARCH),
    ("查一下", BotIntent.SEARCH),
    ("搜一下", BotIntent.SEARCH),
    ("找一下", BotIntent.SEARCH),
    ("简报", BotIntent.TOP),
    ("今天", BotIntent.TODAY),
    ("今日", BotIntent.TODAY),
    ("热门", BotIntent.TOP),
    ("排行", BotIntent.TOP),
    ("订阅", BotIntent.SUBSCRIBE),
    ("关注", BotIntent.SUBSCRIBE),
    ("帮助", BotIntent.HELP),
    ("菜单", BotIntent.HELP),
    ("help", BotIntent.HELP),
]


# ---------------------------------------------------------------------------
# KnowledgeSearchEngine
# ---------------------------------------------------------------------------


class KnowledgeSearchEngine:
    """知识库搜索引擎。

    从 ``knowledge/articles/`` 目录读取 JSON 知识条目文件，
    支持按关键词、标签、日期范围过滤，以及今日条目和热门排序。

    数据来源与 :func:`src.distributors.formatter.generate_daily_digest` 一致，
    均读取 ``kb-*.json`` 文件（跳过 ``index.json``）。

    线程安全：本类无共享可变状态，``_load_articles`` 每次调用独立读取文件，
    可在多线程环境下安全使用。

    Args:
        knowledge_dir: 知识条目目录路径，默认 ``knowledge/articles``。
    """

    def __init__(self, knowledge_dir: str = _DEFAULT_KNOWLEDGE_DIR) -> None:
        self._knowledge_dir = Path(knowledge_dir)

    def _load_articles(self) -> list[dict[str, Any]]:
        """加载目录下所有知识条目 JSON 文件。

        扫描 ``kb-*.json`` 文件（跳过 ``index.json``），解析为 dict 列表。
        单个文件解析失败时跳过并记录警告，不中断整体加载。

        Returns:
            知识条目 dict 列表，目录不存在时返回空列表。
        """
        if not self._knowledge_dir.is_dir():
            logger.warning("知识条目目录不存在: %s", self._knowledge_dir)
            return []

        articles: list[dict[str, Any]] = []
        for json_file in sorted(self._knowledge_dir.glob("kb-*.json")):
            try:
                with open(json_file, encoding="utf-8") as f:
                    article: dict[str, Any] = json.load(f)
                articles.append(article)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("读取文件失败 %s: %s", json_file, exc)
                continue

        logger.debug("加载知识条目: %d 篇 (dir=%s)", len(articles), self._knowledge_dir)
        return articles

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """解析 ISO 8601 时间字符串。

        解析失败或输入为空时返回 ``None``。naive datetime 统一补充 UTC 时区。

        Args:
            date_str: ISO 8601 格式时间字符串。

        Returns:
            timezone-aware datetime 对象，解析失败返回 ``None``。
        """
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    @staticmethod
    def _ensure_aware(dt: datetime) -> datetime:
        """确保 datetime 为 timezone-aware，naive 时补充 UTC。

        Args:
            dt: 待检查的 datetime。

        Returns:
            timezone-aware datetime。
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    def search(
        self,
        *,
        keyword: str | None = None,
        tags: list[str] | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """多条件搜索知识条目。

        过滤逻辑（AND 语义）：同时满足关键词、标签、日期范围条件。
        关键词在标题和摘要中做大小写不敏感子串匹配；
        标签为 OR 语义（任一标签匹配即通过）；
        日期范围按 ``collected_at`` 字段过滤（闭区间）。

        Args:
            keyword: 搜索关键词，``None`` 时不按关键词过滤。
            tags: 标签列表，``None`` 时不按标签过滤。
            date_start: 起始时间（含），``None`` 时不限制下界。
            date_end: 结束时间（含），``None`` 时不限制上界。
            limit: 返回条数上限，最大 50。

        Returns:
            匹配的知识条目列表，按 ``collected_at`` 降序排列。
        """
        limit = min(limit, _MAX_LIMIT)
        articles = self._load_articles()
        results: list[dict[str, Any]] = []

        kw_lower = keyword.lower() if keyword else None
        tag_set = set(tags) if tags else None

        for article in articles:
            # 关键词过滤（标题 + 摘要）
            if kw_lower is not None:
                title = article.get("title", "").lower()
                summary = article.get("summary", "").lower()
                if kw_lower not in title and kw_lower not in summary:
                    continue

            # 标签过滤（OR 语义）
            if tag_set is not None:
                article_tags = set(article.get("tags", []))
                if not article_tags.intersection(tag_set):
                    continue

            # 日期范围过滤
            collected = self._parse_date(article.get("collected_at", ""))
            if collected is None:
                continue
            if date_start is not None:
                ds = self._ensure_aware(date_start)
                if collected < ds:
                    continue
            if date_end is not None:
                de = self._ensure_aware(date_end)
                if collected > de:
                    continue

            results.append(article)

        # 按 collected_at 降序排列
        def _sort_key(article: dict[str, Any]) -> datetime:
            return (
                self._parse_date(article.get("collected_at", ""))
                or datetime.min.replace(tzinfo=UTC)
            )

        results.sort(key=_sort_key, reverse=True)
        return results[:limit]

    def get_today(self, *, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """获取今日新增的知识条目。

        按 UTC 日期匹配 ``collected_at`` 的日期部分，按评分降序排列。

        Args:
            limit: 返回条数上限，最大 50。

        Returns:
            今日知识条目列表。
        """
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        articles = self._load_articles()
        filtered = [
            a for a in articles
            if (a.get("collected_at", "")[:10] == today_str)
        ]
        filtered.sort(key=lambda a: a.get("score", 0) or 0, reverse=True)
        return filtered[:min(limit, _MAX_LIMIT)]

    def get_top(
        self,
        *,
        n: int = _DEFAULT_TOP_N,
        date: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取热门知识条目（按评分排序）。

        Args:
            n: 返回条数，最大 50。
            date: 日期字符串 ``YYYY-MM-DD``，``None`` 时不限日期。

        Returns:
            评分最高的 N 篇知识条目列表。
        """
        n = min(n, _MAX_LIMIT)
        articles = self._load_articles()

        if date is not None:
            articles = [
                a for a in articles
                if (a.get("collected_at", "")[:10] == date)
            ]

        articles.sort(key=lambda a: a.get("score", 0) or 0, reverse=True)
        return articles[:n]


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------


class SubscriptionManager:
    """用户订阅管理器（增删查）。

    使用内存字典存储用户订阅，适用于单实例 Bot 场景。
    多实例部署时需替换为数据库持久化实现。

    订阅数据结构::

        {
            "sub_id": "sub-001",
            "user_id": "user123",
            "tags": ["llm", "agent"],
            "keywords": ["GPT"],
            "created_at": "2026-07-31T12:00:00Z",
        }

    线程安全：本类使用实例级 dict，未加锁保护。单线程事件循环下安全使用；
    多线程场景需调用方自行加锁。
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[dict[str, Any]]] = {}
        self._next_id: int = 1

    def subscribe(
        self,
        user_id: str,
        *,
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """创建用户订阅。

        Args:
            user_id: 用户 ID。
            tags: 订阅标签列表，``None`` 或空列表表示不限标签。
            keywords: 订阅关键词列表，``None`` 或空列表表示不限关键词。

        Returns:
            新建的订阅记录 dict，包含分配的 ``sub_id``。

        Raises:
            ValueError: tags 和 keywords 同时为空时抛出。
        """
        if not tags and not keywords:
            raise ValueError("订阅须至少指定一个标签或关键词")

        sub_id = f"{_SUB_ID_PREFIX}{self._next_id:03d}"
        self._next_id += 1

        subscription: dict[str, Any] = {
            "sub_id": sub_id,
            "user_id": user_id,
            "tags": list(tags) if tags else [],
            "keywords": list(keywords) if keywords else [],
            "created_at": datetime.now(UTC).isoformat(),
        }

        if user_id not in self._subscriptions:
            self._subscriptions[user_id] = []
        self._subscriptions[user_id].append(subscription)

        logger.info("用户 %s 创建订阅 %s: tags=%s keywords=%s", user_id, sub_id, tags, keywords)
        return subscription

    def unsubscribe(self, user_id: str, sub_id: str) -> bool:
        """取消用户订阅。

        Args:
            user_id: 用户 ID。
            sub_id: 订阅 ID。

        Returns:
            取消成功返回 ``True``，订阅不存在返回 ``False``。
        """
        user_subs = self._subscriptions.get(user_id, [])
        for i, sub in enumerate(user_subs):
            if sub["sub_id"] == sub_id:
                user_subs.pop(i)
                logger.info("用户 %s 取消订阅 %s", user_id, sub_id)
                return True
        logger.warning("用户 %s 订阅 %s 不存在", user_id, sub_id)
        return False

    def list_subscriptions(self, user_id: str) -> list[dict[str, Any]]:
        """列出用户的所有订阅。

        Args:
            user_id: 用户 ID。

        Returns:
            订阅记录列表（按创建时间顺序），无订阅时返回空列表。
        """
        return list(self._subscriptions.get(user_id, []))


# ---------------------------------------------------------------------------
# PermissionManager
# ---------------------------------------------------------------------------


class PermissionManager:
    """三级权限管理器（READ / WRITE / DELETE）。

    使用内存字典存储用户权限，未注册用户默认拥有 READ 权限。
    高级别权限自动包含低级别（详见 :class:`PermissionLevel.includes`）。

    线程安全：与 :class:`SubscriptionManager` 相同，单线程下安全使用。
    """

    def __init__(self) -> None:
        self._user_permissions: dict[str, PermissionLevel] = {}

    def get_level(self, user_id: str) -> PermissionLevel:
        """获取用户权限级别。

        未注册用户返回默认权限 :attr:`PermissionLevel.READ`。

        Args:
            user_id: 用户 ID。

        Returns:
            用户当前的权限级别。
        """
        return self._user_permissions.get(user_id, PermissionLevel.READ)

    def check_permission(self, user_id: str, required: PermissionLevel) -> bool:
        """检查用户是否拥有指定权限。

        Args:
            user_id: 用户 ID。
            required: 需要的权限级别。

        Returns:
            用户权限级别 >= required 时返回 ``True``。
        """
        return self.get_level(user_id).includes(required)

    def grant(self, user_id: str, level: PermissionLevel) -> None:
        """授予用户权限。

        若用户已有更高权限，则保留更高权限（取最大值）。

        Args:
            user_id: 用户 ID。
            level: 要授予的权限级别。
        """
        current = self.get_level(user_id)
        self._user_permissions[user_id] = (
            level if level.value > current.value else current
        )
        logger.info("用户 %s 权限设置: %s (当前最高: %s)", user_id, level, self.get_level(user_id))

    def revoke(self, user_id: str) -> None:
        """撤销用户所有自定义权限，恢复为默认 READ。

        Args:
            user_id: 用户 ID。
        """
        self._user_permissions.pop(user_id, None)
        logger.info("用户 %s 权限已撤销，恢复为 READ", user_id)


# ---------------------------------------------------------------------------
# KnowledgeBot
# ---------------------------------------------------------------------------


class KnowledgeBot:
    """知识库交互 Bot 主入口。

    整合 :class:`KnowledgeSearchEngine`、:class:`SubscriptionManager`、
    :class:`PermissionManager`，通过 :meth:`handle_message` 统一处理用户消息。

    消息处理流程::

        handle_message(user_id, text)
            -> recognize_intent(text) -> (BotIntent, params)
            -> 权限检查
            -> 分发到 _handle_xxx 处理器
            -> 返回 Markdown 格式响应字符串

    Args:
        search_engine: 搜索引擎实例，``None`` 时使用默认配置创建。
        subscription_manager: 订阅管理器实例，``None`` 时新建。
        permission_manager: 权限管理器实例，``None`` 时新建。
    """

    def __init__(
        self,
        search_engine: KnowledgeSearchEngine | None = None,
        subscription_manager: SubscriptionManager | None = None,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        self._search: KnowledgeSearchEngine = search_engine or KnowledgeSearchEngine()
        self._subscription: SubscriptionManager = subscription_manager or SubscriptionManager()
        self._permission: PermissionManager = permission_manager or PermissionManager()

    # -- 意图识别 -----------------------------------------------------------

    @staticmethod
    def recognize_intent(text: str) -> tuple[BotIntent, str]:
        """识别用户消息意图（纯规则匹配，不使用 LLM）。

        匹配优先级：
            1. 命令前缀（``/search`` / ``/today`` / ``/top`` / ``/subscribe`` / ``/help``）
            2. 自然语言关键词（搜索、查询、今天、简报、订阅等）
            3. 未匹配时返回 ``UNKNOWN``

        命令前缀模式下，参数为命令后的剩余文本（去除前后空白）。
        自然语言模式下，参数为关键词后的剩余文本。

        Args:
            text: 用户输入文本。

        Returns:
            ``(BotIntent, 参数字符串)`` 元组。无参数时参数为空字符串。
        """
        if not text or not text.strip():
            return (BotIntent.UNKNOWN, "")

        text = text.strip()

        # 1. 命令前缀匹配
        for cmd, intent in _COMMAND_MAP.items():
            if text == cmd:
                return (intent, "")
            if text.startswith(cmd + " "):
                params = text[len(cmd):].strip()
                return (intent, params)

        # 2. 自然语言关键词匹配
        for keyword, intent in _NL_KEYWORDS:
            idx = text.find(keyword)
            if idx != -1:
                params = text[idx + len(keyword):].strip()
                return (intent, params)

        return (BotIntent.UNKNOWN, text)

    # -- 统一入口 -----------------------------------------------------------

    def handle_message(self, user_id: str, text: str) -> str:
        """处理用户消息的统一入口。

        根据意图识别结果分发到对应处理器，自动进行权限检查。

        Args:
            user_id: 用户 ID。
            text: 用户消息文本。

        Returns:
            Bot 响应字符串（Markdown 格式）。
        """
        intent, params = self.recognize_intent(text)
        logger.info("用户 %s 消息: intent=%s params=%s", user_id, intent.value, params)

        # 权限检查
        required = _INTENT_PERMISSIONS.get(intent)
        if required is not None and not self._permission.check_permission(user_id, required):
            logger.warning("用户 %s 权限不足，需要 %s", user_id, required)
            return (
                f"⛔ 权限不足：此操作需要 {required.name} 权限。\n\n"
                "可输入 `/help` 查看可用命令。"
            )

        # 分发到处理器
        handler_map: dict[BotIntent, Callable[[str, str], str]] = {
            BotIntent.SEARCH: self._handle_search,
            BotIntent.TODAY: self._handle_today,
            BotIntent.TOP: self._handle_top,
            BotIntent.SUBSCRIBE: self._handle_subscribe,
            BotIntent.HELP: self._handle_help,
        }

        handler = handler_map.get(intent)
        if handler is None:
            return self._handle_help(user_id, params)

        return handler(user_id, params)

    # -- 处理器 -------------------------------------------------------------

    def _handle_search(self, user_id: str, params: str) -> str:
        """处理搜索意图。

        Args:
            user_id: 用户 ID。
            params: 搜索关键词。

        Returns:
            搜索结果 Markdown 字符串。
        """
        keyword = params.strip() if params else ""
        if not keyword:
            return "请提供搜索关键词。\n\n用法: `/search <关键词>` 或 `搜索 <关键词>`"

        results = self._search.search(keyword=keyword, limit=_DEFAULT_LIMIT)

        if not results:
            return f"🔍 未找到与「{keyword}」相关的知识条目。"

        header = f"🔍 搜索「{keyword}」（共 {len(results)} 条）"
        return self._format_results(results, header)

    def _handle_today(self, user_id: str, params: str) -> str:
        """处理今日条目意图。

        Args:
            user_id: 用户 ID。
            params: 未使用。

        Returns:
            今日条目 Markdown 字符串。
        """
        results = self._search.get_today(limit=_DEFAULT_LIMIT)

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        if not results:
            return f"📅 {today_str} 暂无新增知识条目。"

        header = f"📅 {today_str} 新增知识条目（共 {len(results)} 条）"
        return self._format_results(results, header)

    def _handle_top(self, user_id: str, params: str) -> str:
        """处理热门条目意图。

        Args:
            user_id: 用户 ID。
            params: 可选数字，指定返回条数。

        Returns:
            热门条目 Markdown 字符串。
        """
        n = _DEFAULT_TOP_N
        if params:
            match = re.search(r"\d+", params)
            if match:
                n = int(match.group())

        results = self._search.get_top(n=n)

        if not results:
            return "🏆 暂无知识条目。"

        header = f"🏆 热门知识条目 Top {len(results)}"
        return self._format_results(results, header)

    def _handle_subscribe(self, user_id: str, params: str) -> str:
        """处理订阅管理意图。

        支持以下用法：
            - 无参数：列出当前订阅
            - ``tag:llm keyword:agent``：按标签和关键词订阅
            - ``remove <sub_id>``：取消指定订阅

        Args:
            user_id: 用户 ID。
            params: 订阅参数。

        Returns:
            操作结果 Markdown 字符串。
        """
        params = params.strip() if params else ""

        # 取消订阅
        if params.startswith("remove ") or params.startswith("cancel "):
            sub_id = params.split(maxsplit=1)[1].strip() if " " in params else ""
            if not sub_id:
                return "请提供订阅 ID。\n\n用法: `/subscribe remove <sub_id>`"
            if self._subscription.unsubscribe(user_id, sub_id):
                return f"✅ 已取消订阅 {sub_id}。"
            return f"❌ 订阅 {sub_id} 不存在。"

        # 列出订阅
        if not params or params in ("list", "查看"):
            subs = self._subscription.list_subscriptions(user_id)
            if not subs:
                return "📋 您当前无订阅。\n\n用法: `/subscribe tag:llm keyword:agent`"
            lines = [f"📋 您的订阅（共 {len(subs)} 条）", ""]
            for sub in subs:
                tags_str = ", ".join(sub["tags"]) if sub["tags"] else "无"
                kw_str = ", ".join(sub["keywords"]) if sub["keywords"] else "无"
                lines.append(f"- **{sub['sub_id']}** | 标签: {tags_str} | 关键词: {kw_str}")
            return "\n".join(lines)

        # 解析订阅参数
        tags: list[str] = []
        keywords: list[str] = []
        for part in params.split():
            if part.startswith("tag:"):
                tag_val = part[4:]
                if tag_val:
                    tags.append(tag_val)
            elif part.startswith("keyword:"):
                kw_val = part[8:]
                if kw_val:
                    keywords.append(kw_val)
            else:
                keywords.append(part)

        if not tags and not keywords:
            return "订阅参数无效。\n\n用法: `/subscribe tag:llm keyword:agent`"

        try:
            sub = self._subscription.subscribe(
                user_id, tags=tags or None, keywords=keywords or None
            )
        except ValueError as exc:
            return f"❌ {exc}"

        tags_str = ", ".join(sub["tags"]) if sub["tags"] else "无"
        kw_str = ", ".join(sub["keywords"]) if sub["keywords"] else "无"
        return (
            f"✅ 订阅成功！\n\n"
            f"- 订阅 ID: **{sub['sub_id']}**\n"
            f"- 标签: {tags_str}\n"
            f"- 关键词: {kw_str}"
        )

    def _handle_help(self, user_id: str, params: str) -> str:
        """处理帮助意图。

        Args:
            user_id: 用户 ID。
            params: 未使用。

        Returns:
            帮助信息 Markdown 字符串。
        """
        current_perm = self._permission.get_level(user_id)
        lines = [
            "🤖 知识库 Bot 使用指南",
            "",
            "**命令列表**：",
            "- `/search <关键词>` — 搜索知识条目",
            "- `/today` — 查看今日新增条目",
            "- `/top [N]` — 查看热门条目（默认 5 条）",
            "- `/subscribe [tag:xxx] [keyword:xxx]` — 订阅管理",
            "- `/help` — 查看本帮助",
            "",
            "**自然语言示例**：",
            '- "搜索 LLM"',
            '- "今天有什么"',
            '- "热门文章"',
            '- "订阅 tag:llm"',
            "",
            f"**当前权限**: {current_perm.name}",
        ]

        required_write = _INTENT_PERMISSIONS.get(BotIntent.SUBSCRIBE)
        if required_write is not None and not self._permission.check_permission(
            user_id, required_write
        ):
            lines.append("")
            lines.append("⚠️ 订阅功能需要 WRITE 权限，您当前权限不足。")

        return "\n".join(lines)

    # -- 格式化辅助 ---------------------------------------------------------

    @staticmethod
    def _format_results(articles: list[dict[str, Any]], header: str) -> str:
        """将知识条目列表格式化为 Markdown 字符串。

        Args:
            articles: 知识条目 dict 列表。
            header: 标题行。

        Returns:
            Markdown 格式字符串。
        """
        if not articles:
            return f"{header}\n\n暂无结果。"

        lines = [header, ""]
        for i, article in enumerate(articles, 1):
            title: str = article.get("title", "")
            source_url: str = article.get("source_url", "")
            score = article.get("score", 0) or 0
            if not isinstance(score, int):
                score = int(score)
            summary: str = article.get("summary", "")
            tags: list[Any] = article.get("tags", [])
            tags_str = " ".join(f"#{t}" for t in tags[:3]) if tags else ""
            collected: str = article.get("collected_at", "")[:10] or "未知"

            lines.append(f"{i}. **[{title}]({source_url})**")
            score_line = f"   日期: {collected} | 评分: {score}/10"
            if tags_str:
                score_line += f" | {tags_str}"
            lines.append(score_line)
            lines.append(f"   摘要: {summary}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 填充意图 -> 权限映射
# ---------------------------------------------------------------------------

_INTENT_PERMISSIONS.update({
    BotIntent.SEARCH: PermissionLevel.READ,
    BotIntent.TODAY: PermissionLevel.READ,
    BotIntent.TOP: PermissionLevel.READ,
    BotIntent.SUBSCRIBE: PermissionLevel.WRITE,
    BotIntent.HELP: None,
    BotIntent.UNKNOWN: None,
})


__all__ = [
    "BotIntent",
    "KnowledgeBot",
    "KnowledgeSearchEngine",
    "PermissionLevel",
    "PermissionManager",
    "SubscriptionManager",
]
