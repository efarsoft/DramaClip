"""服务端通知：progress.update / log.append / models.download_progress。

通知层节流（长跑稳定性②）：progress.update 在分析/导出期间每秒多次，
每次一条 TCP 写——50 集批量分析时 IPC 开销放大。改为按 job_id 缓冲
最新值，500ms 窗口合并发送（跳过的中间值取最新，UI 不丢帧感）。
非 progress 类通知不受节流（log.append / download_progress 即时发）。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any, TypeVar

from dramaclip.transport.rpc import RpcNotification

Sender = Callable[[dict[str, Any]], None]
_T = TypeVar("_T")

_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}

# 当前作业 id：并发任务下每条业务日志都要能能归到一条任务上。
# 线程池会复用工作线程，所以绑定必须随任务体开始/结束成对发生（见 tracked）。
_JOB_ID: ContextVar[str | None] = ContextVar("dramaclip_job_id", default=None)

logger = logging.getLogger("dramaclip.job")

#: progress 类通知的合并窗口：窗口内的多次更新只发最后一条
_PROGRESS_FLUSH_INTERVAL_S = 0.5


def current_job_id() -> str | None:
    """当前线程绑定的作业 id（无作业上下文为 None）：降级账等库面写入靠它解析作业引用。"""
    return _JOB_ID.get()


class Notifier:
    """把业务事件包装为 JSON-RPC 通知并发送。engines 不直接持有本类——api 层注入。"""

    def __init__(self, send: Sender) -> None:
        self._send = send
        # progress 节流缓存：job_id → (上次发送时刻, 最新 params)
        self._progress_buffer: dict[str, tuple[float, dict[str, Any]]] = {}
        self._progress_lock = threading.Lock()

    def progress(
        self,
        job_id: str,
        percent: float,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        params: dict[str, Any] = {"job_id": job_id, "percent": percent, "message": message}
        if detail is not None:
            params["detail"] = detail
        # 节流：同 job 500ms 内多次更新只发最后一条——TCP 写次数降一个量级
        now = time.monotonic()
        with self._progress_lock:
            cached = self._progress_buffer.get(job_id)
            if cached is not None and now - cached[0] < _PROGRESS_FLUSH_INTERVAL_S:
                self._progress_buffer[job_id] = (cached[0], params)  # 只更新值不重置时钟
                return
            self._progress_buffer[job_id] = (now, params)
        self._emit("progress.update", params)

    def tracked(self, job_id: str, fn: Callable[..., _T], *args: Any) -> Callable[[], _T]:
        """把任务体包成"作业作用域内执行"：投给线程池时用一次，日志即自动带上 job_id。"""

        def run() -> _T:
            token: Token[str | None] = _JOB_ID.set(job_id)
            try:
                return fn(*args)
            finally:
                _JOB_ID.reset(token)
                # 任务结束：把节流缓存里的尾值立即发出去（不等下个窗口）
                with self._progress_lock:
                    cached = self._progress_buffer.pop(job_id, None)
                if cached is not None:
                    self._emit("progress.update", cached[1])

        return run

    def log(self, level: str, message: str, *, job_id: str | None = None) -> None:
        bound = job_id if job_id is not None else _JOB_ID.get()
        # 双写：通知面渲染层没订上的话业务日志就当场蒸发，落盘面才是事后可查的账
        logger.log(
            _LEVELS.get(level, logging.INFO),
            "%s%s",
            f"[{bound}] " if bound is not None else "",
            message,
        )
        params: dict[str, Any] = {"level": level, "message": message}
        if bound is not None:
            params["job_id"] = bound
        self._emit("log.append", params)

    def model_download(self, model_id: str, percent: float, **extra: Any) -> None:
        self._emit("models.download_progress", {"model_id": model_id, "percent": percent, **extra})

    def sizes_ready(self) -> None:
        """模型磁盘实占后台补算完成：资产列表页据此重拉 models.list 补上体积列。"""
        self._emit("models.sizes_ready", {})

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        self._send(RpcNotification(method=method, params=params).model_dump())
