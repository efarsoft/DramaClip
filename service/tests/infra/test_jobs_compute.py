"""jobs/export_jobs 的 compute 列：JSON 数组落库、读取解析、重试清空。"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.jobs import JobStore
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def test_job_compute_roundtrip(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    job_id = store.create("analysis")
    report = {"component": "asr.whisper", "requested": "auto", "resolved": "cuda",
              "actual": "cpu", "fallback": True, "reason": "cublas", "device": "cpu"}
    store.set_compute(job_id, [report])
    assert store.get(job_id)["compute"] == [report]
    assert store.list_recent()[0]["compute"] == [report]


def test_export_compute_roundtrip_and_retry_clears(memory_db: sqlite3.Connection) -> None:
    project_id = str(projects_repo.create(memory_db, "回执剧", "D:/absent")["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "raw_clip", [], {"timeline": []}
        )["id"]
    )
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    report = {"component": "video.encode", "requested": "auto", "resolved": "libx264",
              "actual": "libx264", "fallback": False, "reason": "", "device": "libx264"}
    exports_repo.set_compute(memory_db, export_id, [report])
    assert exports_repo.get(memory_db, export_id)["compute"] == [report]
    exports_repo.mark_failed(memory_db, export_id, "boom")
    assert exports_repo.reset_for_retry(memory_db, export_id) is True
    assert exports_repo.get(memory_db, export_id)["compute"] is None
