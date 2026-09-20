"""服务端通知：progress.update / log.append / models.download_progress。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any, TypeVar

from dramaclip.transport.rpc import RpcNotification

Sender = Callable[[dict[str, Any]], None]
_T = TypeVar("_T")

_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}

# 当前作业 id：并发任务下每条业务日志都要能归到一条任务上。
# 线程池会复用工作线程，所以绑定必须随任务体开始/结束成对发生（见 tracked）。
_JOB_ID: ContextVar[str | None] = ContextVar("dramaclip_job_id", default=None)

logger = logging.getLogger("dramaclip.job")


class Notifier:
    """把业务事件包装为 JSON-RPC 通知并发送。engines 不直接持有本类——api 层注入。"""

    def __init__(self, send: Sender) -> None:
        self._send = send

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
        self._emit("progress.update", params)

    def tracked(self, job_id: str, fn: Callable[..., _T], *args: Any) -> Callable[[], _T]:
        """把任务体包成"作业作用域内执行"：投给线程池时用一次，日志即自动带上 job_id。"""

        def run() -> _T:
            token: Token[str | None] = _JOB_ID.set(job_id)
            try:
                return fn(*args)
            finally:
                _JOB_ID.reset(token)

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

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        self._send(RpcNotification(method=method, params=params).model_dump())
