"""infra.jobs：状态机全迁移路径与启动清扫。"""

from __future__ import annotations

import sqlite3

import pytest

from dramaclip.infra.jobs import JobStore


def test_full_lifecycle(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    job_id = store.create("analysis", ref_id="p1")
    store.mark_running(job_id)
    store.set_progress(job_id, 45.5)
    store.mark_completed(job_id)
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == "completed"
    assert job["progress"] == 45.5


def test_terminal_state_rejects_transition(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    job_id = store.create("export")
    store.mark_failed(job_id, "boom")
    with pytest.raises(ValueError, match="已终态"):
        store.mark_running(job_id)


def test_sweep_interrupted_marks_running_failed(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    running_id = store.create("analysis")
    store.mark_running(running_id)
    pending_id = store.create("analysis")

    swept = store.sweep_interrupted()
    assert swept == 1

    running = store.get(running_id)
    pending = store.get(pending_id)
    assert running is not None and running["status"] == "failed"
    assert running["error"] == "服务中断"
    assert pending is not None and pending["status"] == "pending"
    assert store.sweep_interrupted() == 0  # 幂等


def test_get_missing_returns_none(memory_db: sqlite3.Connection) -> None:
    assert JobStore(memory_db).get("nope") is None
