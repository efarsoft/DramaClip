"""system 命名空间：ping / health / shutdown（W1 全量）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from dramaclip.infra import gpu
from dramaclip.transport.rpc import Router

_STARTED_AT = time.monotonic()


def register(
    router: Router,
    *,
    service_version: str,
    protocol_version: int,
    shutdown: Callable[[], None],
) -> None:
    """注册 system.* 方法。"""

    def ping(_params: dict[str, Any]) -> dict[str, Any]:
        return {"service_version": service_version, "protocol_version": protocol_version}

    def health(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "uptime_s": round(time.monotonic() - _STARTED_AT, 1),
            "gpu_info": gpu.snapshot(),
        }

    def _shutdown(_params: dict[str, Any]) -> dict[str, Any]:
        shutdown()
        return {"ok": True}

    router.register("system.ping", ping)
    router.register("system.health", health)
    router.register("system.shutdown", _shutdown)
