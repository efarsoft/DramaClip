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


def test_sweep_interrupted_marks_running_and_pending_failed(
    memory_db: sqlite3.Connection,
) -> None:
    """启动清扫：`running` 与 `pending` 同为崩溃残留，一并记失败；终态行不动。

    `executor.submit` 不挂 done-callback（`api/narration.py` 两处），任务入队而 worker
    始终没跑起来时，行会永远停在 `pending`——队列页挂着一只永不推进的任务。清扫只在
    启动时跑，那一刻没有服务在跑，即没有任何任务真的在飞，所以"复位 running"的那条
    理由原样适用于 pending（与 `exports.reset_stale_pending` 同构，两表不得互相矛盾）。
    """
    store = JobStore(memory_db)
    running_id = store.create("analysis")
    store.mark_running(running_id)
    pending_id = store.create("produce")  # 入队未开跑，就是崩溃残留的形状
    done_id = store.create("export")
    store.mark_running(done_id)
    store.mark_completed(done_id)

    assert store.sweep_interrupted() == 2

    running = store.get(running_id)
    pending = store.get(pending_id)
    done = store.get(done_id)
    assert running is not None and running["status"] == "failed"
    assert running["error"] == "服务中断"
    assert pending is not None and pending["status"] == "failed", "入队未开跑的行清不掉"
    assert pending["error"] == "服务中断"
    assert done is not None and done["status"] == "completed", "终态行不该被清扫改写"
    assert store.sweep_interrupted() == 0  # 幂等


def test_get_missing_returns_none(memory_db: sqlite3.Connection) -> None:
    assert JobStore(memory_db).get("nope") is None
