"""jobs.clear_finished：清空全部终态记录，在跑与排队中的原样保留。"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from dramaclip.api import jobs as jobs_api
from dramaclip.infra.jobs import JobStore
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _router(conn: sqlite3.Connection) -> Router:
    router = Router()
    context = SimpleNamespace(
        conn=conn, job_store=JobStore(conn), cancel_events={}, notifier=Notifier(lambda _m: None)
    )
    jobs_api.register(router, context)  # type: ignore[arg-type]
    return router


def _call(conn: sqlite3.Connection, method: str, params: dict | None = None) -> dict:
    response = _router(conn).dispatch(RpcRequest(id=method, method=method, params=params or {}))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_clear_finished_deletes_terminal_only(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    run_id = store.create("analysis", ref_id="p1")
    store.mark_running(run_id)
    done_id = store.create("export", ref_id="e1")
    store.mark_completed(done_id)
    fail_id = store.create("export", ref_id="e2")
    store.mark_failed(fail_id, "boom")

    deleted = _call(memory_db, "jobs.clear_finished")["deleted"]

    assert deleted == 2
    assert store.get(run_id) is not None, "在跑任务不许被清掉"
    assert store.get(done_id) is None
    assert store.get(fail_id) is None


def test_clear_finished_on_empty_returns_zero(memory_db: sqlite3.Connection) -> None:
    assert _call(memory_db, "jobs.clear_finished") == {"deleted": 0}
