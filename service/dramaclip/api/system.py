"""system 命名空间：ping / health / shutdown（W1 全量）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from dramaclip.infra import gpu, machine
from dramaclip.infra.ffmpeg import binaries
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

    def health(params: dict[str, Any]) -> dict[str, Any]:
        force_refresh = bool(params.get("refresh"))
        return {
            "status": "ok",
            "uptime_s": round(time.monotonic() - _STARTED_AT, 1),
            "gpu_info": gpu.snapshot(force=force_refresh),
            "ram_total_gb": machine.specs(force=force_refresh).get("ram_total_gb"),
            "ram_free_gb": machine.specs().get("ram_free_gb"),
            "disk_free_gb": machine.specs().get("disk_free_gb"),
            "ffmpeg_version": binaries.version(force=force_refresh),
        }

    def _shutdown(_params: dict[str, Any]) -> dict[str, Any]:
        shutdown()
        return {"ok": True}

    router.register("system.ping", ping)
    router.register("system.health", health)
    router.register("system.shutdown", _shutdown)
