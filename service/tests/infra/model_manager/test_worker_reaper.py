"""进程收割登记契约：自管子进程的桥在退出钩子里一并被收，回调幂等随便重入。"""

from __future__ import annotations

import pytest

from dramaclip.infra.model_manager import worker_bridge


def test_register_process_reaper_fires_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    monkeypatch.setattr(worker_bridge, "_PROCESS_REAPERS", [])
    worker_bridge.register_process_reaper(lambda: fired.append("a"))

    worker_bridge.shutdown_venv_workers()
    assert fired == ["a"], "登记的收尸回调随退出钩子一并执行"


def test_reaper_deduplicates_bound_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一实例的绑定方法重复登记只留一份（绑定方法按 func+instance 判等）。"""
    fired: list[str] = []
    monkeypatch.setattr(worker_bridge, "_PROCESS_REAPERS", [])

    class _Bridge:
        def shutdown(self) -> None:
            fired.append("x")

    bridge = _Bridge()
    worker_bridge.register_process_reaper(bridge.shutdown)
    worker_bridge.register_process_reaper(bridge.shutdown)  # 首次 spawn 幂等登记

    worker_bridge.shutdown_venv_workers()
    assert fired == ["x"], "同桥重复登记不重复执行"


def test_venv_workers_still_reaped_before_reapers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原有 VenvWorker 回收语义不变：close 先于收割回调执行（合成收尾优先）。"""
    order: list[str] = []
    monkeypatch.setattr(worker_bridge, "_PROCESS_REAPERS", [])
    worker_bridge.register_process_reaper(lambda: order.append("reaper"))

    class _Worker:
        def close(self) -> None:
            order.append("worker")

    monkeypatch.setattr(worker_bridge, "_ACTIVE_WORKERS", [_Worker()])
    worker_bridge.shutdown_venv_workers()
    assert order == ["worker", "reaper"]
