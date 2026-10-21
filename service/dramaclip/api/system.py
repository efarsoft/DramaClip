"""system 命名空间：ping / health / shutdown（W1 全量）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from dramaclip.infra import device_profile, gpu, machine
from dramaclip.infra.ffmpeg import binaries
from dramaclip.infra.model_manager import cuda_runtime, tts_runtime
from dramaclip.transport.rpc import Router

_STARTED_AT = time.monotonic()


def health(params: dict[str, Any], data_dir: Any) -> dict[str, Any]:
    """system.health：GPU 快照 + 三处安装态 marker → 设备档位与各引擎能力结论。

    安装态一律按调用方传入的 data_dir 读——档位表若与解析入口各读一份真相，
    界面上就会和实际执行结论打架。
    """
    force_refresh = bool(params.get("refresh"))
    gpu_snapshot = gpu.snapshot(force=force_refresh)
    return {
        "status": "ok",
        "uptime_s": round(time.monotonic() - _STARTED_AT, 1),
        "gpu_info": gpu_snapshot,
        "device_profile": device_profile.profile(
            gpu_snapshot,
            cuda_runtime.status(data_dir)["installed"] if data_dir is not None else False,
            separation_ort=tts_runtime.ort_state(data_dir) if data_dir is not None else None,
            torch_variant=tts_runtime.torch_variant(data_dir) if data_dir is not None else None,
        ),
        "ram_total_gb": machine.specs(force=force_refresh).get("ram_total_gb"),
        "ram_free_gb": machine.specs().get("ram_free_gb"),
        "disk_free_gb": machine.specs().get("disk_free_gb"),
        "ffmpeg_version": binaries.version(force=force_refresh),
    }


def register(
    router: Router,
    *,
    service_version: str,
    protocol_version: int,
    shutdown: Callable[[], None],
    data_dir: Any = None,
) -> None:
    """注册 system.* 方法。data_dir 供设备档位读 CUDA 运行库安装态。"""

    def ping(_params: dict[str, Any]) -> dict[str, Any]:
        return {"service_version": service_version, "protocol_version": protocol_version}

    def _shutdown(_params: dict[str, Any]) -> dict[str, Any]:
        shutdown()
        return {"ok": True}

    router.register("system.ping", ping)
    router.register("system.health", lambda params: health(params, data_dir))
    router.register("system.shutdown", _shutdown)
