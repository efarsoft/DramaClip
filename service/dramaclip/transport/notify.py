"""服务端通知：progress.update / log.append / models.download_progress。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dramaclip.transport.rpc import RpcNotification

Sender = Callable[[dict[str, Any]], None]


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

    def log(self, level: str, message: str) -> None:
        self._emit("log.append", {"level": level, "message": message})

    def model_download(self, model_id: str, percent: float, **extra: Any) -> None:
        self._emit("models.download_progress", {"model_id": model_id, "percent": percent, **extra})

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        self._send(RpcNotification(method=method, params=params).model_dump())
