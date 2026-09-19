"""api.system：health 返回本机内存/磁盘/GPU 快照（探测失败不阻塞）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from dramaclip.api import system as system_api
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.context = SimpleNamespace()
        self.router = Router()
        system_api.register(
            self.router,
            service_version="test",
            protocol_version=1,
            shutdown=lambda: None,
        )

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result


def test_health_reports_machine_specs() -> None:
    payload = Harness().rpc("system.health", {})
    assert payload["status"] == "ok"
    assert isinstance(payload["uptime_s"], (int, float))
    assert "gpu_info" in payload
    # machine.specs 探测成功时给数值（Windows 真机必然成功）；失败时为 None 而非缺键
    for key in ("ram_total_gb", "ram_free_gb", "disk_free_gb"):
        assert key in payload
        assert payload[key] is None or isinstance(payload[key], float)


def test_machine_specs_values_are_sane() -> None:
    from dramaclip.infra import machine

    specs = machine.specs(force=True)
    if specs:  # Windows 真机：非空即合理
        assert specs["ram_total_gb"] >= 1
        assert 0 <= specs["ram_free_gb"] <= specs["ram_total_gb"]
        assert specs["disk_free_gb"] >= 0
    # 缓存路径：第二次调用与第一次一致（无 force 不重测）
    assert machine.specs() == specs
