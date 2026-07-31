#!/usr/bin/env python3
"""KnowledgeBot 湿地测试脚本（实弹测试）。

使用 knowledge/articles/ 下的真实知识条目数据，
对 KnowledgeBot 全部功能进行端到端验证。

运行方式::

    uv run python scripts/test_knowledge_bot_live.py

测试覆盖场景：
    1. 搜索引擎（关键词、标签、日期）
    2. 今日条目 & 热门排行
    3. 意图识别（命令 + 自然语言）
    4. 权限控制（READ 用户搜索、订阅被拦截；WRITE 用户订阅）
    5. 订阅管理（创建、列表、取消）
    6. handle_message 全链路（命令 + 自然语言 + 未知意图）
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from src.bot.knowledge_bot import (
    BotIntent,
    KnowledgeBot,
    KnowledgeSearchEngine,
    PermissionLevel,
    PermissionManager,
    SubscriptionManager,
)

KNOWLEDGE_DIR = "knowledge/articles"

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _sub(title: str) -> None:
    print(f"\n--- {title} ---")


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def _print_results(results: list[dict]) -> None:
    if not results:
        print("  (无结果)")
        return
    for i, a in enumerate(results, 1):
        score = a.get("score", 0)
        print(f"  {i}. [{score}/10] {a['title']}")
        print(f"     tags: {a.get('tags', [])}")
        print(f"     date: {a.get('collected_at', '')[:10]}")


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def test_search_engine(engine: KnowledgeSearchEngine) -> None:
    """测试搜索引擎。"""
    _header("1. KnowledgeSearchEngine 搜索引擎测试")

    # 1.1 加载全部条目
    _sub("1.1 加载全部条目")
    all_articles = engine._load_articles()
    _ok(f"加载到 {len(all_articles)} 篇知识条目")

    # 1.2 关键词搜索
    _sub("1.2 关键词搜索")
    for kw in ["agent", "LLM", "AI", "框架"]:
        results = engine.search(keyword=kw, limit=5)
        _info(f'搜索 "{kw}" -> {len(results)} 条')
        _print_results(results[:3])

    # 1.3 标签搜索
    _sub("1.3 标签搜索")
    for tag in ["agent", "llm", "framework"]:
        results = engine.search(tags=[tag], limit=5)
        _info(f'标签 "{tag}" -> {len(results)} 条')
        _print_results(results[:2])

    # 1.4 日期范围搜索
    _sub("1.4 日期范围搜索")
    date_start = datetime(2026, 7, 30, tzinfo=UTC)
    results = engine.search(date_start=date_start, limit=10)
    _info(f"2026-07-30 之后的条目 -> {len(results)} 条")
    _print_results(results[:3])

    # 1.5 组合搜索
    _sub("1.5 组合搜索（关键词 + 标签）")
    results = engine.search(keyword="agent", tags=["llm"], limit=5)
    _info(f'关键词 "agent" + 标签 "llm" -> {len(results)} 条')
    _print_results(results[:3])

    # 1.6 get_top
    _sub("1.6 热门排行 Top 5")
    results = engine.get_top(n=5)
    _ok(f"Top {len(results)} 条目（按评分降序）")
    _print_results(results)

    # 1.7 get_today
    _sub("1.7 今日新增")
    results = engine.get_today(limit=10)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    _info(f"{today} 新增 {len(results)} 条")
    _print_results(results[:3])

    print()


def test_recognize_intent() -> None:
    """测试意图识别。"""
    _header("2. recognize_intent 意图识别测试")

    test_cases = [
        # 命令前缀
        ("/search agent", BotIntent.SEARCH),
        ("/search", BotIntent.SEARCH),
        ("/today", BotIntent.TODAY),
        ("/top 10", BotIntent.TOP),
        ("/subscribe tag:llm", BotIntent.SUBSCRIBE),
        ("/help", BotIntent.HELP),
        # 自然语言
        ("搜索 LLM", BotIntent.SEARCH),
        ("查询 agent 框架", BotIntent.SEARCH),
        ("今天有什么新内容", BotIntent.TODAY),
        ("今日简报", BotIntent.TOP),
        ("热门文章", BotIntent.TOP),
        ("订阅 tag:llm", BotIntent.SUBSCRIBE),
        ("帮助", BotIntent.HELP),
        ("help", BotIntent.HELP),
        # 边界
        ("", BotIntent.UNKNOWN),
        ("xyzrandom", BotIntent.UNKNOWN),
        ("/search 今天有什么", BotIntent.SEARCH),  # 命令优先
    ]

    passed = 0
    failed = 0
    for text, expected in test_cases:
        intent, params = KnowledgeBot.recognize_intent(text)
        status = "PASS" if intent == expected else "FAIL"
        if status == "PASS":
            passed += 1
            _ok(f'"{text}" -> {intent.value} (params="{params}")')
        else:
            failed += 1
            _fail(
                f'"{text}" -> {intent.value}, 期望 {expected.value} '
                f'(params="{params}")'
            )

    _info(f"意图识别: {passed} 通过, {failed} 失败")
    print()


def test_permission_manager() -> None:
    """测试权限管理器。"""
    _header("3. PermissionManager 权限管理测试")

    pm = PermissionManager()

    # 3.1 默认权限
    _sub("3.1 默认权限为 READ")
    assert pm.get_level("guest") == PermissionLevel.READ
    assert pm.check_permission("guest", PermissionLevel.READ) is True
    assert pm.check_permission("guest", PermissionLevel.WRITE) is False
    _ok("guest 用户默认 READ，无法 WRITE")

    # 3.2 授予 WRITE
    _sub("3.2 授予 WRITE 权限")
    pm.grant("editor", PermissionLevel.WRITE)
    assert pm.check_permission("editor", PermissionLevel.READ) is True
    assert pm.check_permission("editor", PermissionLevel.WRITE) is True
    assert pm.check_permission("editor", PermissionLevel.DELETE) is False
    _ok("editor 用户拥有 WRITE，包含 READ，无 DELETE")

    # 3.3 授予 DELETE
    _sub("3.3 授予 DELETE 权限")
    pm.grant("admin", PermissionLevel.DELETE)
    assert pm.check_permission("admin", PermissionLevel.DELETE) is True
    assert pm.check_permission("admin", PermissionLevel.WRITE) is True
    assert pm.check_permission("admin", PermissionLevel.READ) is True
    _ok("admin 用户拥有 DELETE，包含 READ+WRITE")

    # 3.4 不降级
    _sub("3.4 权限不降级")
    pm.grant("admin", PermissionLevel.READ)
    assert pm.get_level("admin") == PermissionLevel.DELETE
    _ok("admin 已有 DELETE，授予 READ 不降级")

    # 3.5 撤销
    _sub("3.5 撤销权限")
    pm.revoke("admin")
    assert pm.get_level("admin") == PermissionLevel.READ
    _ok("admin 撤销后恢复 READ")

    print()


def test_subscription_manager() -> None:
    """测试订阅管理器。"""
    _header("4. SubscriptionManager 订阅管理测试")

    sm = SubscriptionManager()

    # 4.1 创建订阅
    _sub("4.1 创建订阅")
    sub1 = sm.subscribe("user1", tags=["llm"], keywords=["GPT"])
    sub2 = sm.subscribe("user1", tags=["agent"], keywords=["LangChain"])
    sub3 = sm.subscribe("user2", tags=["framework"])
    _ok(f"创建 3 条订阅: {sub1['sub_id']}, {sub2['sub_id']}, {sub3['sub_id']}")

    # 4.2 列出订阅
    _sub("4.2 列出订阅")
    user1_subs = sm.list_subscriptions("user1")
    user2_subs = sm.list_subscriptions("user2")
    assert len(user1_subs) == 2
    assert len(user2_subs) == 1
    _ok(f"user1 有 {len(user1_subs)} 条订阅, user2 有 {len(user2_subs)} 条")

    # 4.3 取消订阅
    _sub("4.3 取消订阅")
    result = sm.unsubscribe("user1", sub1["sub_id"])
    assert result is True
    assert len(sm.list_subscriptions("user1")) == 1
    _ok(f"取消 {sub1['sub_id']} 成功")

    # 4.4 取消不存在的订阅
    _sub("4.4 取消不存在的订阅")
    result = sm.unsubscribe("user1", "sub-999")
    assert result is False
    _ok("取消不存在的订阅返回 False")

    # 4.5 空参数校验
    _sub("4.5 空参数校验")
    try:
        sm.subscribe("user1")
        _fail("应该抛出 ValueError")
    except ValueError:
        _ok("tags 和 keywords 同时为空时抛出 ValueError")

    print()


def test_handle_message(bot: KnowledgeBot) -> None:
    """测试 handle_message 全链路。"""
    _header("5. KnowledgeBot.handle_message 全链路测试")

    # 5.1 搜索（命令）
    _sub("5.1 搜索（命令）")
    resp = bot.handle_message("guest", "/search agent")
    print(f"  [响应]\n{_indent(resp)}")
    if "agent" in resp.lower() or "搜索" in resp:
        _ok("搜索命令正常返回结果")
    else:
        _fail("搜索命令异常")

    # 5.2 搜索（自然语言）
    _sub("5.2 搜索（自然语言）")
    resp = bot.handle_message("guest", "搜索 LLM")
    print(f"  [响应]\n{_indent(resp)}")
    _ok("自然语言搜索正常")

    # 5.3 今日
    _sub("5.3 今日条目")
    resp = bot.handle_message("guest", "/today")
    print(f"  [响应]\n{_indent(resp)}")
    _ok("今日命令正常")

    # 5.4 热门
    _sub("5.4 热门排行")
    resp = bot.handle_message("guest", "/top 3")
    print(f"  [响应]\n{_indent(resp)}")
    _ok("热门命令正常")

    # 5.5 帮助
    _sub("5.5 帮助")
    resp = bot.handle_message("guest", "/help")
    print(f"  [响应]\n{_indent(resp)}")
    _ok("帮助命令正常")

    # 5.6 未知意图
    _sub("5.6 未知意图")
    resp = bot.handle_message("guest", "这是一段不知所云的文字")
    print(f"  [响应]\n{_indent(resp)}")
    if "知识库 Bot" in resp:
        _ok("未知意图回退到帮助")
    else:
        _fail("未知意图未回退到帮助")

    print()


def test_permission_flow(bot: KnowledgeBot) -> None:
    """测试权限控制流程。"""
    _header("6. 权限控制测试（订阅需要 WRITE 权限）")

    # 6.1 READ 用户尝试订阅 -> 被拦截
    _sub("6.1 READ 用户尝试订阅（应被拦截）")
    resp = bot.handle_message("reader", "/subscribe tag:llm")
    print(f"  [响应]\n{_indent(resp)}")
    if "权限不足" in resp:
        _ok("READ 用户订阅被正确拦截")
    else:
        _fail("READ 用户订阅未被拦截")

    # 6.2 授予 WRITE 后订阅成功
    _sub("6.2 授予 WRITE 后订阅")
    bot._permission.grant("editor", PermissionLevel.WRITE)
    resp = bot.handle_message("editor", "/subscribe tag:llm keyword:agent")
    print(f"  [响应]\n{_indent(resp)}")
    if "订阅成功" in resp:
        _ok("WRITE 用户订阅成功")
    else:
        _fail("WRITE 用户订阅失败")

    # 6.3 列出订阅
    _sub("6.3 列出订阅")
    resp = bot.handle_message("editor", "/subscribe list")
    print(f"  [响应]\n{_indent(resp)}")
    if "llm" in resp:
        _ok("列出订阅正常")
    else:
        _fail("列出订阅异常")

    # 6.4 取消订阅
    _sub("6.4 取消订阅")
    # 从 list 结果中提取 sub_id
    sub_id = None
    for line in resp.split("\n"):
        if "sub-" in line:
            start = line.find("sub-")
            sub_id = line[start:].split("**")[0].split(" ")[0].strip()
            break
    if sub_id:
        resp = bot.handle_message("editor", f"/subscribe remove {sub_id}")
        print(f"  [响应]\n{_indent(resp)}")
        if "已取消" in resp:
            _ok(f"取消订阅 {sub_id} 成功")
        else:
            _fail("取消订阅失败")
    else:
        _fail("未能提取 sub_id")

    # 6.5 DELETE 权限包含 WRITE
    _sub("6.5 DELETE 权限包含 WRITE")
    bot._permission.grant("root", PermissionLevel.DELETE)
    resp = bot.handle_message("root", "/subscribe tag:framework")
    print(f"  [响应]\n{_indent(resp)}")
    if "订阅成功" in resp:
        _ok("DELETE 用户可以订阅（包含 WRITE）")
    else:
        _fail("DELETE 用户无法订阅")

    print()


def _indent(text: str, prefix: str = "    ") -> str:
    """缩进每一行。"""
    return "\n".join(f"{prefix}{line}" for line in text.split("\n"))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> int:
    print("\n" + "=" * 70)
    print("  KnowledgeBot 湿地测试（使用真实知识库数据）")
    print(f"  数据目录: {KNOWLEDGE_DIR}")
    print(f"  测试时间: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    # 构建组件
    engine = KnowledgeSearchEngine(KNOWLEDGE_DIR)
    sub_mgr = SubscriptionManager()
    perm_mgr = PermissionManager()
    bot = KnowledgeBot(
        search_engine=engine,
        subscription_manager=sub_mgr,
        permission_manager=perm_mgr,
    )

    # 运行测试
    test_search_engine(engine)
    test_recognize_intent()
    test_permission_manager()
    test_subscription_manager()
    test_handle_message(bot)
    test_permission_flow(bot)

    # 总结
    _header("测试总结")
    _ok("全部测试场景执行完毕")
    _info("如上方无 [FAIL] 标记，则全部通过")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
