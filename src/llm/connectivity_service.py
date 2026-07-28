"""供应商联通性持久化服务。

将 :func:`src.llm.connectivity.test_connectivity` 的探测结果
持久化到 ``kb_llm_provider_connectivity`` 表（upsert 语义）。

定时任务（每 5 分钟）和手动触发批量连通性测试均调用本模块。

事务约定：
    本模块所有函数**不调用** ``session.commit()``，仅执行 ``flush()``。
    事务提交/回滚由调用方控制。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.connectivity import ConnectivityResult, test_connectivity
from src.llm.orm import LlmProvider, LlmProviderConnectivity
from src.llm.schemas import ProviderConnectivityResponse, ProviderConnectivityResult

logger = logging.getLogger(__name__)

_MAX_PARALLEL_PROBES = 6


def save_connectivity_result(
    session: Session,
    provider_id: int,
    result: ConnectivityResult,
) -> None:
    """将单条连通性探测结果 upsert 到 DB。

    若该供应商已有联通性行则更新，否则插入新行。

    Args:
        session: SQLAlchemy Session。
        provider_id: 供应商 ID。
        result: 连通性探测结果。
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    row = session.execute(
        select(LlmProviderConnectivity).where(
            LlmProviderConnectivity.provider_id == provider_id,
            LlmProviderConnectivity.is_deleted == False,  # noqa: E712
        )
    ).scalars().first()

    if row is None:
        row = LlmProviderConnectivity(provider_id=provider_id)
        session.add(row)

    row.is_connected = result.success
    row.latency_ms = result.latency_ms
    row.last_check_at = now
    if result.success:
        row.last_success_at = now
        row.last_error = None
    else:
        row.last_failure_at = now
        row.last_error = (result.error or "")[:500]

    session.flush()


def scan_all_providers(session: Session) -> list[ProviderConnectivityResult]:
    """扫描所有未软删除供应商的联通性并持久化。

    使用线程池并行探测各供应商（最多 ``_MAX_PARALLEL_PROBES`` 个并发），
    探测完成后在主线程统一持久化到 DB，避免多线程共享 Session。

    供定时任务和手动批量测试调用。

    Args:
        session: SQLAlchemy Session。

    Returns:
        各供应商的连通性结果列表（按供应商 priority/id 排序）。
    """
    providers = list(
        session.execute(
            select(LlmProvider).where(
                LlmProvider.is_deleted == False,  # noqa: E712
            ).order_by(LlmProvider.priority, LlmProvider.id)
        ).scalars().all()
    )

    if not providers:
        return []

    # 并行探测（IO-bound），结果按 provider_id 索引
    probe_results: dict[int, ConnectivityResult] = {}
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_PROBES) as pool:
        future_to_provider = {
            pool.submit(test_connectivity, p): p for p in providers
        }
        for future in as_completed(future_to_provider):
            p = future_to_provider[future]
            try:
                probe_results[p.id] = future.result()
            except Exception:
                logger.exception(
                    "供应商 %s (id=%d) 连通性探测异常",
                    p.provider_code,
                    p.id,
                )
                probe_results[p.id] = ConnectivityResult(
                    success=False,
                    latency_ms=None,
                    status_code=None,
                    error="探测过程异常",
                    endpoint="",
                )

    # 在主线程统一持久化
    results: list[ProviderConnectivityResult] = []
    for p in providers:
        r = probe_results.get(
            p.id,
            ConnectivityResult(
                success=False, latency_ms=None, status_code=None,
                error="未知错误", endpoint="",
            ),
        )
        save_connectivity_result(session, p.id, r)
        if not r.success:
            logger.warning(
                "供应商 %s (id=%d) 联通性测试失败: %s",
                p.provider_code,
                p.id,
                r.error,
            )
        results.append(
            ProviderConnectivityResult(
                provider_id=p.id,
                success=r.success,
                latency_ms=r.latency_ms,
                error=r.error,
                last_check_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    logger.info("供应商联通性扫描完成: %d 个供应商", len(providers))
    return results


def get_connectivity_map(
    session: Session,
    provider_ids: list[int],
) -> dict[int, ProviderConnectivityResponse]:
    """批量查询供应商联通性状态。

    Args:
        session: SQLAlchemy Session。
        provider_ids: 供应商 ID 列表。

    Returns:
        ``{provider_id: ProviderConnectivityResponse}`` 映射。
    """
    if not provider_ids:
        return {}

    rows = session.execute(
        select(LlmProviderConnectivity).where(
            LlmProviderConnectivity.provider_id.in_(provider_ids),
            LlmProviderConnectivity.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()

    return {
        r.provider_id: ProviderConnectivityResponse.model_validate(r) for r in rows
    }


__all__ = [
    "get_connectivity_map",
    "save_connectivity_result",
    "scan_all_providers",
]
