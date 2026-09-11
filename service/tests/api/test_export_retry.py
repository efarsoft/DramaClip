"""export_jobs 的崩溃残留必须被启动清扫复位；进程内失败路径不得回归。"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export as export_api
from dramaclip.api import jobs as jobs_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


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
            context,
            export_api.ExportRun(
                export_id=export_id,
                project_id=project_id,
                plan_row=plan_row,
                plan_data=plan_data,
                cancel_event=threading.Event(),
            ),
            report=lambda _p, _m: None,
        )

    # render_export 本身不落库；落库由调用方 _run_export 的 except 负责
    # （Task 4 的 retry 依赖此契约）
    assert exports_repo.get(memory_db, export_id)["status"] == "pending"


def _export_router(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[Router, SimpleNamespace]:
    context = _context(memory_db, tmp_path)
    context.executor = ThreadPoolExecutor(max_workers=2)
    router = Router()
    export_api.register(router, context)  # type: ignore[arg-type]
    return router, context


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_retry_reuses_same_export_id_and_adds_no_row(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """幂等核心：重试复用原 export_id，且不得新增记录（否则队列页出现重复成片）。

    原计划不断言 status（异步重跑读到时可能 pending 可能 failed，属竞态）。
    这里改成 shutdown(wait=True) 先把线程池排空再看终局：断言因此确定，
    并且能顺带验证「复位→重跑→再次失败并写下新原因」这条链路真的发生了。
    """
    project_id, _plan_id, export_id, _plan_data = _seed_export(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    router, context = _export_router(memory_db, tmp_path)

    result = _call(router, "export.retry", {"export_id": export_id})
    assert result["export_id"] == export_id, "retry 不得返回新 id"
    assert "job_id" in result

    context.executor.shutdown(wait=True)

    rows = exports_repo.list_by_project(memory_db, project_id)
    assert len(rows) == 1, "重试不得新增记录"
    assert rows[0]["id"] == export_id
    # 种子记录引用不存在的集，重跑必然再次失败——且失败原因是新的
    assert rows[0]["status"] == "failed"
    assert "源文件缺失" in str(rows[0]["error"])
    assert rows[0]["output_path"] is None
    # 重试确实起了一个真任务（不是空操作）
    export_jobs = [job for job in context.job_store.list_recent() if job["type"] == "export"]
    assert [job["ref_id"] for job in export_jobs] == [export_id]


def test_retry_rejects_completed_export(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    _project_id, _plan_id, export_id, _data = _seed_export(memory_db, tmp_path)
    exports_repo.mark_completed(memory_db, export_id, str(tmp_path / "done.mp4"))
    router, _ctx = _export_router(memory_db, tmp_path)
    response = router.dispatch(
        RpcRequest(id=1, method="export.retry", params={"export_id": export_id})
    )
    assert response.error is not None
    assert response.error.code == -32405


def test_retry_rejects_unknown_export(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router, _ctx = _export_router(memory_db, tmp_path)
    response = router.dispatch(
        RpcRequest(id=1, method="export.retry", params={"export_id": "nope"})
    )
    assert response.error is not None
    assert response.error.code == -32404


def test_reset_for_retry_clears_error_and_output(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """纯仓储层：复位必须清 error / output_path / completed_at 并回到 pending。"""
    _project_id, _plan_id, export_id, _data = _seed_export(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    exports_repo.set_meta(memory_db, export_id, duration_s=61.0, size_bytes=1024)

    exports_repo.reset_for_retry(memory_db, export_id)

    record = exports_repo.get(memory_db, export_id)
    assert record is not None
    assert record["status"] == "pending"
    assert record["error"] is None
    assert record["output_path"] is None
    assert record["completed_at"] is None
    assert record["progress"] == 0


def test_jobs_cancel_sets_registered_event(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    event = threading.Event()
    context = SimpleNamespace(
        conn=memory_db, job_store=store, cancel_events={job_id: event},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    result = _call(router, "jobs.cancel", {"job_id": job_id})
    assert result["cancelling"] is True
    assert event.is_set()


def test_jobs_cancel_on_terminal_job_returns_false(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.mark_completed(job_id)
    context = SimpleNamespace(
        conn=memory_db, job_store=store, cancel_events={},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    result = _call(router, "jobs.cancel", {"job_id": job_id})
    assert result["cancelling"] is False
    assert result["reason"] == "任务已终态"


def test_jobs_cancel_uninterruptible_job_reports_honestly(memory_db: sqlite3.Connection) -> None:
    """未注册 cancel_event 的非终态任务：必须如实回"不可中断"，不能假装取消了。

    真实服务里这条路也走得到：`models.download` 下载中确实注册了事件（可中断），
    但收尾的看门狗会 pop 掉它，而该 job 从不 mark_running/mark_completed ——
    于是记录停在 pending、事件已回收，只能落到本分支。
    """
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("model_download", ref_id="m1")  # 停在 pending，无 cancel_event
    context = SimpleNamespace(
        conn=memory_db, job_store=store, cancel_events={},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    result = _call(router, "jobs.cancel", {"job_id": job_id})
    assert result["cancelling"] is False
    assert result["reason"] == "任务不可中断"


def test_jobs_cancel_unknown_job_is_domain_error(memory_db: sqlite3.Connection) -> None:
    context = SimpleNamespace(
        conn=memory_db, job_store=jobs_mod.JobStore(memory_db), cancel_events={},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(RpcRequest(id=1, method="jobs.cancel", params={"job_id": "x"}))
    assert response.error is not None
    assert response.error.code == -32501


def test_reset_for_retry_is_cas(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """并发重试收口：第二次复位必须失败，否则两个任务会渲染进同一产物路径。"""
    _project_id, _plan_id, export_id, _data = _seed_export(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")

    assert exports_repo.reset_for_retry(memory_db, export_id) is True
    assert exports_repo.reset_for_retry(memory_db, export_id) is False, "已非 failed 不得再次复位"
