"""多 Agent 预算守卫 -- 工作流层成本追踪与预算防护。

本模块为 LangGraph 工作流提供独立的成本守卫机制，与 ``src/llm/budget.py``
的 LLM 客户端层预算控制互补：

- ``src/llm.budget.BudgetGuard``: 在 ``chat_completion`` 调用前后检查，
  基于 DB 持久化的 ``kb_llm_call_log`` 表，防止单日总消耗超标。
- 本模块 ``CostGuard``: 在工作流节点层检查，基于内存中的 ``CostRecord``
  列表，精确追踪每次 LLM 调用的 token 用量与费用，支持按节点分组报告。

三重保护机制：
    1. **record()** -- 记录每次 LLM 调用，实时累计 token 与费用
    2. **check()** -- 检查预算状态，超限抛 :class:`BudgetExceededError`，
       接近阈值返回 ``"warning"``
    3. **get_report() / save_report()** -- 按节点分组统计，持久化报告

通过 :data:`cost_guard_var` ContextVar 实现线程安全的守卫实例传递，
工作流入口调用 :func:`set_cost_guard` 注入，节点内通过 :func:`get_cost_guard`
获取并调用 :meth:`CostGuard.record` / :meth:`CostGuard.check`。

Usage::

    from src.common.cost_guard import CostGuard, set_cost_guard, get_cost_guard

    # 工作流入口
    guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
    set_cost_guard(guard)

    # 节点内（_call_llm 集成）
    guard = get_cost_guard()
    if guard is not None:
        guard.check()  # 超限抛 BudgetExceededError
    # ... LLM 调用 ...
    if guard is not None:
        guard.record("analyze", {"prompt_tokens": 1000, "completion_tokens": 500},
                     model="doubao-pro")

    # 工作流结束
    report = guard.get_report()
    guard.save_report("cost_report.json")
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ContextVar 用于线程安全地传递 CostGuard 实例。
# ThreadPoolExecutor 的子线程会继承父线程的 ContextVar 快照，
# 因此 analyze_node 中的并发 _analyze_one 也能访问到同一个 guard。
cost_guard_var: contextvars.ContextVar[CostGuard | None] = contextvars.ContextVar(
    "cost_guard", default=None
)


class BudgetExceededError(Exception):
    """预算超限异常。

    当 :meth:`CostGuard.check` 检测到累计成本超出预算时抛出。
    节点捕获此异常后将 LLM 调用失败记入 ``errors`` 并提前返回。

    Attributes:
        total_cost: 当前累计成本（元）。
        budget: 预算上限（元）。
        message: 异常描述。
    """

    def __init__(self, total_cost: float, budget: float, message: str = "") -> None:
        """初始化预算超限异常。

        Args:
            total_cost: 当前累计成本。
            budget: 预算上限。
            message: 自定义异常消息，为空时自动生成。
        """
        self.total_cost = total_cost
        self.budget = budget
        self.message = message or (
            f"预算超限: 累计成本 {total_cost:.6f} 元 > 预算 {budget:.6f} 元"
        )
        super().__init__(self.message)

    def __str__(self) -> str:
        """返回异常描述。"""
        return self.message


@dataclass
class CostRecord:
    """单次 LLM 调用成本记录。

    Attributes:
        timestamp: 调用时间戳（ISO 8601 字符串）。
        node_name: 发起调用的节点名称（如 "analyze" / "review" / "revise"）。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        cost_yuan: 本次调用成本（元）。
        model: 调用的模型名称。
    """

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


@dataclass
class CostGuard:
    """多 Agent 预算守卫。

    在工作流层追踪每次 LLM 调用的 token 用量与费用，提供三重保护：
    记录 (record) / 检查 (check) / 报告 (get_report, save_report)。

    线程安全：内部使用 :class:`threading.Lock` 保护 ``record`` 和 ``check``
    的读写操作，支持 ``analyze_node`` 的 ``ThreadPoolExecutor`` 并发调用。

    Attributes:
        budget_yuan: 预算上限（元）。
        alert_threshold: 预警阈值（0~1），累计成本达到 ``budget * threshold`` 时预警。
        input_price_per_million: 输入 token 每百万价格（元）。
        output_price_per_million: 输出 token 每百万价格（元）。
        records: 所有成本记录列表。
        total_prompt_tokens: 累计输入 token 数。
        total_completion_tokens: 累计输出 token 数。
        total_cost_yuan: 累计成本（元）。
    """

    budget_yuan: float = 1.0
    alert_threshold: float = 0.8
    input_price_per_million: float = 1.0
    output_price_per_million: float = 2.0
    records: list[CostRecord] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_yuan: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self,
        node_name: str,
        usage: dict[str, int],
        model: str = "",
    ) -> CostRecord:
        """记录一次 LLM 调用的 token 用量并计算成本。

        线程安全：内部加锁保护累加操作。

        Args:
            node_name: 发起调用的节点名称。
            usage: token 用量字典，格式 ``{"prompt_tokens": int, "completion_tokens": int}``。
            model: 调用的模型名称。

        Returns:
            本次调用对应的 :class:`CostRecord` 实例。
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        cost_yuan = self._compute_cost(prompt_tokens, completion_tokens)

        record = CostRecord(
            timestamp=datetime.now().isoformat(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost_yuan,
            model=model,
        )
        with self._lock:
            self.records.append(record)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_cost_yuan += cost_yuan

        logger.debug(
            "CostGuard.record: node=%s model=%s prompt=%d completion=%d cost=%.6f "
            "total_cost=%.6f / budget=%.6f",
            node_name,
            model,
            prompt_tokens,
            completion_tokens,
            cost_yuan,
            self.total_cost_yuan,
            self.budget_yuan,
        )
        return record

    def check(self) -> dict[str, Any]:
        """检查预算状态。

        - 累计成本 >= 预算上限时，抛出 :class:`BudgetExceededError`。
        - 累计成本 >= 预算 * ``alert_threshold`` 时，返回 ``status="warning"``。
        - 否则返回 ``status="ok"``。

        线程安全：内部加锁读取累计值。

        Returns:
            预算状态字典::

                {
                    "status": "ok" | "warning",
                    "total_cost": float,
                    "budget": float,
                    "usage_ratio": float,
                    "message": str,
                }

        Raises:
            BudgetExceededError: 累计成本超出预算上限。
        """
        with self._lock:
            total_cost = self.total_cost_yuan
            budget = self.budget_yuan

        usage_ratio = total_cost / budget if budget > 0 else 0.0

        if total_cost >= budget:
            raise BudgetExceededError(
                total_cost=total_cost,
                budget=budget,
            )

        if usage_ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": total_cost,
                "budget": budget,
                "usage_ratio": usage_ratio,
                "message": (
                    f"预算预警: 已用 {usage_ratio:.1%} "
                    f"({total_cost:.6f}/{budget:.6f} 元)"
                ),
            }

        return {
            "status": "ok",
            "total_cost": total_cost,
            "budget": budget,
            "usage_ratio": usage_ratio,
            "message": (
                f"预算正常: 已用 {usage_ratio:.1%} "
                f"({total_cost:.6f}/{budget:.6f} 元)"
            ),
        }

    def get_report(self) -> dict[str, Any]:
        """生成成本报告（按节点分组统计）。

        Returns:
            成本报告字典::

                {
                    "summary": {
                        "total_prompt_tokens": int,
                        "total_completion_tokens": int,
                        "total_cost_yuan": float,
                        "budget_yuan": float,
                        "usage_ratio": float,
                        "call_count": int,
                    },
                    "by_node": {
                        "<node_name>": {
                            "call_count": int,
                            "prompt_tokens": int,
                            "completion_tokens": int,
                            "cost_yuan": float,
                        },
                        ...
                    },
                    "records": [CostRecord.asdict(), ...],
                }
        """
        with self._lock:
            records_snapshot = list(self.records)
            total_prompt = self.total_prompt_tokens
            total_completion = self.total_completion_tokens
            total_cost = self.total_cost_yuan

        by_node: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_yuan": 0.0,
            }
        )

        for rec in records_snapshot:
            slot = by_node[rec.node_name]
            slot["call_count"] += 1
            slot["prompt_tokens"] += rec.prompt_tokens
            slot["completion_tokens"] += rec.completion_tokens
            slot["cost_yuan"] += rec.cost_yuan

        usage_ratio = total_cost / self.budget_yuan if self.budget_yuan > 0 else 0.0

        return {
            "summary": {
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_cost_yuan": round(total_cost, 6),
                "budget_yuan": self.budget_yuan,
                "usage_ratio": round(usage_ratio, 4),
                "call_count": len(records_snapshot),
            },
            "by_node": {
                node: {
                    "call_count": v["call_count"],
                    "prompt_tokens": v["prompt_tokens"],
                    "completion_tokens": v["completion_tokens"],
                    "cost_yuan": round(v["cost_yuan"], 6),
                }
                for node, v in sorted(by_node.items())
            },
            "records": [asdict(r) for r in records_snapshot],
        }

    def save_report(self, path: str | Path | None = None) -> Path:
        """保存成本报告到 JSON 文件。

        Args:
            path: 目标文件路径。为 ``None`` 时默认保存到
                ``knowledge/cost_report_{timestamp}.json``。

        Returns:
            实际写入的文件路径。
        """
        if path is None:
            default_dir = Path("knowledge")
            default_dir.mkdir(parents=True, exist_ok=True)
            path = default_dir / (
                f"cost_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        else:
            path = Path(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        report = self.get_report()
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("成本报告已保存: %s", path)
        return path

    def _compute_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """根据 token 用量和定价计算单次调用成本。

        Args:
            prompt_tokens: 输入 token 数。
            completion_tokens: 输出 token 数。

        Returns:
            成本（元），保留 6 位小数。
        """
        input_cost = (prompt_tokens / 1_000_000) * self.input_price_per_million
        output_cost = (completion_tokens / 1_000_000) * self.output_price_per_million
        return round(input_cost + output_cost, 6)


def set_cost_guard(guard: CostGuard | None) -> contextvars.Token[CostGuard | None]:
    """设置当前上下文的 CostGuard 实例。

    在工作流入口调用，各节点通过 :func:`get_cost_guard` 获取。
    ``ThreadPoolExecutor`` 子线程继承父线程的 ContextVar 快照。

    Args:
        guard: CostGuard 实例，传 ``None`` 可清除。

    Returns:
        ContextVar Token，可用于恢复原值。
    """
    return cost_guard_var.set(guard)


def get_cost_guard() -> CostGuard | None:
    """获取当前上下文的 CostGuard 实例。

    Returns:
        当前 CostGuard 实例，未设置时返回 ``None``。
    """
    return cost_guard_var.get()


__all__ = [
    "BudgetExceededError",
    "CostGuard",
    "CostRecord",
    "cost_guard_var",
    "get_cost_guard",
    "set_cost_guard",
]
