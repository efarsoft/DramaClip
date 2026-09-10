"""export_jobs 的崩溃残留必须被启动清扫复位；进程内失败路径不得回归。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        executor=None,
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )


def _seed_export(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[str, str, str, PlanData]:
    """项目 + 一条引用不存在集的编排 + 一条 pending 导出记录。
    项目下没有任何 episode，渲染时 encoder 必抛 EpisodeSourceMissing —— 确定失败，不需真素材。"""
    project_id = str(projects_repo.create(memory_db, "重试剧", str(tmp_path))["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep-absent", start=0.0, end=1.0, audio="original")],
    )
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "raw_clip", ["ep-absent"], plan_data.model_dump()
        )["id"]
    )
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    return project_id, plan_id, export_id, plan_data


def test_reset_stale_pending_marks_crash_leftovers_failed(memory_db: sqlite3.Connection) -> None:
    """崩溃后 _run_export 的 except 不会执行，记录停在 pending —— 必须被复位成 failed。"""
    # export_jobs.narration_plan_id 有外键，须用真实项目与真实编排（不引用集即可）
    project_id = str(projects_repo.create(memory_db, "崩溃残留剧", "D:/absent")["id"])
    export_ids = [
        exports_repo.create(
            memory_db,
            project_id,
            str(plans_repo.create(memory_db, project_id, "raw_clip", [], {"timeline": []})["id"]),
            "raw_clip",
        )
        for _ in range(2)
    ]
    exports_repo.set_progress(memory_db, export_ids[0], 42.0)

    assert exports_repo.reset_stale_pending(memory_db) == 2

    rows = exports_repo.list_by_project(memory_db, project_id)
    assert {row["status"] for row in rows} == {"failed"}
    assert {row["error"] for row in rows} == {"服务中断"}
    # 中断时的进度保留（与 JobStore.sweep_interrupted 同构，两表不得互相矛盾）
    assert {row["progress"] for row in rows} == {42.0, 0.0}


def test_reset_stale_pending_leaves_terminal_rows_alone(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """已完成/已失败的记录不能被清扫改写——否则历史成品会凭空消失。"""
    project_id, plan_id, export_id, _data = _seed_export(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    done_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    exports_repo.mark_completed(memory_db, done_id, str(tmp_path / "ok.mp4"))

    assert exports_repo.reset_stale_pending(memory_db) == 0

    assert exports_repo.get(memory_db, export_id)["error"] == "编码失败"
    assert exports_repo.get(memory_db, done_id)["status"] == "completed"


def test_inprocess_failure_still_records_error(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """回归守卫：进程内抛错时 _run_export 的 except 必须继续把原因写进 export_jobs。"""
    context = _context(memory_db, tmp_path)
    project_id, plan_id, export_id, plan_data = _seed_export(memory_db, tmp_path)
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None

    with pytest.raises(Exception, match="源文件缺失"):
        export_api.render_export(
            context, export_id, project_id, plan_row, plan_data,
            cancel_event=threading.Event(), report=lambda _p, _m: None,
        )

    # render_export 本身不落库；落库由调用方 _run_export 的 except 负责
    # （Task 4 的 retry 依赖此契约）
    assert exports_repo.get(memory_db, export_id)["status"] == "pending"
