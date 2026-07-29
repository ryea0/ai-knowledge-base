"""供应商联通性定时扫描调度器。

使用轻量级后台线程每 5 分钟扫描一次所有供应商的联通性，
将结果持久化到 ``kb_llm_provider_connectivity`` 表。

设计要点：
    - 不依赖 APScheduler 等第三方库，使用 ``threading.Timer`` 实现。
    - 在 FastAPI ``lifespan`` 中启动和停止。
    - 扫描失败时记录日志但不中断后续调度。
    - 前端通过 ``GET /llm/providers/connectivity`` 轮询读取 DB 中的最新状态。

Usage::

    from src.llm.scheduler import start_connectivity_scheduler, stop_connectivity_scheduler

    # FastAPI lifespan
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start_connectivity_scheduler()
        yield
        stop_connectivity_scheduler()
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from src.config.database import session_scope
from src.llm.connectivity_service import scan_all_providers

logger = logging.getLogger(__name__)

_SCAN_INTERVAL_SECONDS = 300  # 5 分钟


class ConnectivityScheduler:
    """供应商联通性定时扫描调度器（封装全局状态，线程安全）。

    使用 ``threading.Timer`` 实现周期扫描，幂等启动/停止。
    替代原模块级全局变量，便于测试隔离。

    Attributes:
        _timer: 当前活跃的定时器实例。
        _stop_event: 停止信号事件。
    """

    def __init__(self, interval: int = _SCAN_INTERVAL_SECONDS) -> None:
        """初始化调度器。

        Args:
            interval: 扫描间隔秒数，默认 300（5 分钟）。
        """
        self._interval = interval
        self._timer: threading.Timer | None = None
        self._stop_event = threading.Event()

    def _scan_once(self) -> None:
        """执行一次供应商联通性扫描。"""
        if self._stop_event.is_set():
            return
        try:
            with session_scope() as session:
                scan_all_providers(session)
            logger.info(
                "定时联通性扫描完成: %s",
                datetime.now(UTC).strftime("%H:%M:%S"),
            )
        except Exception:
            logger.exception("定时联通性扫描失败")
        finally:
            if not self._stop_event.is_set():
                self._timer = threading.Timer(self._interval, self._scan_once)
                self._timer.daemon = True
                self._timer.start()

    def start(self) -> None:
        """启动供应商联通性定时扫描。

        幂等：重复调用不会启动多个定时器。
        """
        if self._timer is not None:
            logger.warning("联通性定时扫描已在运行，跳过重复启动")
            return

        self._stop_event.clear()
        logger.info("启动供应商联通性定时扫描，间隔 %d 秒", self._interval)
        self._timer = threading.Timer(0, self._scan_once)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        """停止供应商联通性定时扫描。"""
        self._stop_event.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("供应商联通性定时扫描已停止")


# 模块级单例，保持 start_connectivity_scheduler / stop_connectivity_scheduler
# 的向后兼容
_scheduler = ConnectivityScheduler()


def start_connectivity_scheduler() -> None:
    """启动供应商联通性定时扫描（每 5 分钟一次）。

    幂等：重复调用不会启动多个定时器。
    """
    _scheduler.start()


def stop_connectivity_scheduler() -> None:
    """停止供应商联通性定时扫描。"""
    _scheduler.stop()


__all__ = [
    "ConnectivityScheduler",
    "start_connectivity_scheduler",
    "stop_connectivity_scheduler",
]
