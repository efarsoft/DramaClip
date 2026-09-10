"""jobs.list / jobs.get：队列页与"任务掉线后可查"的最小面。"""

from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

from dramaclip.api import jobs as jobs_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _router(conn: sqlite3.Connection, store: jobs_mod.JobStore) -> Router:
    router = Router()
    context = SimpleNamespace(
        conn=conn, job_store=store, cancel_events={}, notifier=Notifier(lambda _m: None)
    )
    jobs_api.register(router, context)  # type: ignore[arg-type]
    return router


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_list_returns_jobs_newest_first(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    first = store.create("prescreen", ref_id="p1")
    time.sleep(0.01)  # 毫秒精度时间戳：不留间隔则同毫秒，末位兜底是随机 id 而非插入序
    second = store.create("export", ref_id="e1")
    # 进度写入会把 updated_at 推到最新（list_recent 按 updated_at DESC 排序），
    # 所以必须改「期望排在首位」的那条：若改 first，实测约半数翻序。
    store.set_progress(second, 30.0, label="切割 3/8")
    router = _router(memory_db, store)
    result = _call(router, "jobs.list", {})
    assert [item["id"] for item in result["jobs"]][0] == second
    assert [item["id"] for item in result["jobs"]][1] == first
    assert result["jobs"][0]["label"] == "切割 3/8"
    assert {"id", "type", "ref_id", "status", "progress", "label"} <= set(result["jobs"][0])


def test_list_active_only_filter(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    live = store.create("export", ref_id="e1")
    done = store.create("export", ref_id="e2")
    store.mark_completed(done)
    router = _router(memory_db, store)
    result = _call(router, "jobs.list", {"active_only": True})
    assert [item["id"] for item in result["jobs"]] == [live]


def test_list_limit_clamped_to_at_least_one(memory_db: sqlite3.Connection) -> None:
    """limit 下钳：0 会返回空列表，负数更糟——SQLite 负 LIMIT 语义是不限量。"""
    store = jobs_mod.JobStore(memory_db)
    for index in range(3):
        store.create("export", ref_id=f"e{index}")
    router = _router(memory_db, store)
    assert len(_call(router, "jobs.list", {"limit": 0})["jobs"]) == 1
    assert len(_call(router, "jobs.list", {"limit": -1})["jobs"]) == 1


def test_get_returns_single_job_with_error(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.mark_failed(job_id, "编码失败")
    router = _router(memory_db, store)
    result = _call(router, "jobs.get", {"job_id": job_id})
    assert result["job"]["status"] == "failed"
    assert result["job"]["error"] == "编码失败"


def test_get_missing_job_is_domain_error(memory_db: sqlite3.Connection) -> None:
    router = _router(memory_db, jobs_mod.JobStore(memory_db))
    response = router.dispatch(RpcRequest(id=1, method="jobs.get", params={"job_id": "nope"}))
    assert response.error is not None
    assert response.error.code == -32501
