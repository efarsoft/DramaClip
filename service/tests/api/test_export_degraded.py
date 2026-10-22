"""降级留痕「账在库」：_note_degraded 在导出作业上下文内追加 degraded_notes。

规格（2026-10-16 UI 真相 §1.2）：通知流是实时面重启即失，库是真相源；
非导出作业 / 无作业上下文只有通知面，如实不落库。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dramaclip.api import export_audit
from dramaclip.infra.jobs import JobStore
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport import notify as notify_mod


def test_note_degraded_lands_in_export_ledger(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    tmp = tmp_path / "src"
    tmp.mkdir()
    project_id = str(projects_repo.create(memory_db, "留痕剧", str(tmp))["id"])
    export_id = exports_repo.create(memory_db, project_id, "n1", "full_narration")
    store = JobStore(memory_db)
    job_id = store.create("export", ref_id=export_id)
    context = SimpleNamespace(
        conn=memory_db,
        job_store=store,
        notifier=SimpleNamespace(log=lambda *a, **k: None),
    )
    token = notify_mod._JOB_ID.set(job_id)
    try:
        export_audit._note_degraded(  # noqa: SLF001
            context, "封面截帧", "本条成片没有封面（列表用占位图）"
        )
    finally:
        notify_mod._JOB_ID.reset(token)

    record = exports_repo.get(memory_db, export_id)
    notes = record["degraded_notes"]
    assert notes is not None and len(notes) == 1
    assert notes[0]["subject"] == "封面截帧"
    assert "占位图" in notes[0]["outcome"]

    export_audit._note_degraded(  # noqa: SLF001 - 同作业内第二条要追加不是覆盖
        context, "成片时长审计", "本条成片的事后核对没有做"
    )
    assert len(exports_repo.get(memory_db, export_id)["degraded_notes"]) == 2


def test_note_degraded_without_job_context_only_notifies(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """无作业上下文（成片列表重测等旁路调用）只有通知面，如实不落库。"""
    tmp = tmp_path / "src"
    tmp.mkdir()
    project_id = str(projects_repo.create(memory_db, "留痕剧", str(tmp))["id"])
    export_id = exports_repo.create(memory_db, project_id, "n1", "full_narration")
    context = SimpleNamespace(
        conn=memory_db,
        job_store=JobStore(memory_db),
        notifier=SimpleNamespace(log=lambda *a, **k: None),
    )
    export_audit._note_degraded(context, "封面截帧", "本条成片没有封面")
    assert exports_repo.get(memory_db, export_id)["degraded_notes"] is None


def test_note_degraded_non_export_job_not_ledgered(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    tmp = tmp_path / "src"
    tmp.mkdir()
    project_id = str(projects_repo.create(memory_db, "留痕剧", str(tmp))["id"])
    export_id = exports_repo.create(memory_db, project_id, "n1", "full_narration")
    store = JobStore(memory_db)
    job_id = store.create("analysis", ref_id="other-project")
    context = SimpleNamespace(
        conn=memory_db,
        job_store=store,
        notifier=SimpleNamespace(log=lambda *a, **k: None),
    )
    token = notify_mod._JOB_ID.set(job_id)
    try:
        export_audit._note_degraded(context, "封面截帧", "占位图")
    finally:
        notify_mod._JOB_ID.reset(token)
    assert exports_repo.get(memory_db, export_id)["degraded_notes"] is None


def test_reset_for_retry_clears_degraded_notes(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """重试 = 覆盖写新导出：上一轮的降级账随旧产物一并作废，新一轮重新记账。"""
    project_id = str(projects_repo.create(memory_db, "留痕剧", str(tmp_path))["id"])
    export_id = exports_repo.create(memory_db, project_id, "n1", "full_narration")
    exports_repo.append_degraded(memory_db, export_id, "封面截帧", "占位图")
    exports_repo.mark_failed(memory_db, export_id, "boom")

    assert exports_repo.reset_for_retry(memory_db, export_id) is True
    assert exports_repo.get(memory_db, export_id)["degraded_notes"] is None
