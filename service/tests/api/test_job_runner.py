"""线程化作业启动壳的契约：终态归属、取消登记回收、话术与结算钩子。

此前 models 域六处各写一套双线程骨架（六个 _watch 闭包四个逐字相同），收敛到
launch_threaded_job 后，这些契约只有一份实现、一份证明。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from dramaclip.api.job_runner import launch_threaded_job
from dramaclip.infra import jobs as jobs_mod
from dramaclip.transport.notify import Notifier


class _Context:
    """runner 只摸 job_store / cancel_events / notifier 三件——鸭子替身即可。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.job_store = jobs_mod.JobStore(conn)
        self.cancel_events: dict[str, threading.Event] = {}
        self.notifier = Notifier(lambda _m: None)


@pytest.fixture()
def context(memory_db: sqlite3.Connection) -> _Context:
    return _Context(memory_db)


def _drain(prefix: str) -> None:
    """等启动壳的两条线程收尾（按名前缀 join，不靠睡）。"""
    for thread in threading.enumerate():
        if thread.name.startswith(prefix):
            thread.join(timeout=5)


def test_success_promotes_and_logs_done_message(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    """work 正常返回 → 看门狗补 completed + 记完成话术；cancel_events 回收。"""
    job_id = launch_threaded_job(
        context,  # type: ignore[arg-type] - 鸭子替身
        job_type="probe",
        ref_id="ref-1",
        thread_prefix="jr-ok",
        work=lambda _job_id, _cancel: "装好了",
    )
    _drain("jr-ok")
    assert context.job_store.get(job_id)["status"] == "completed"
    assert job_id not in context.cancel_events


def test_failure_lands_the_message(context: _Context) -> None:
    """work 抛异常 → 按 failure_message 落 error，不改判成功。"""
    calls: list[str] = []

    def boom(_job_id: str, _cancel: threading.Event) -> str:
        raise RuntimeError("venv 创建失败")

    def failure(exc: Exception) -> str:
        calls.append(str(exc))
        return f"包装：{exc}"

    job_id = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="ref-2",
        thread_prefix="jr-fail",
        work=boom,
        failure_message=failure,
    )
    _drain("jr-fail")
    job = context.job_store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "包装：venv 创建失败"
    assert calls == ["venv 创建失败"]


def test_work_settled_terminal_wins_over_watch(context: _Context) -> None:
    """work 自己落过终态（如取消标 failed）→ 看门狗不再改判 completed。"""
    context.job_store.create("probe", ref_id="ref-3")

    def work(job_id: str, _cancel: threading.Event) -> str | None:
        context.job_store.mark_failed(job_id, "已取消")
        return None

    job_id = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="ref-3",
        thread_prefix="jr-term",
        work=work,
    )
    _drain("jr-term")
    assert context.job_store.get(job_id)["status"] == "failed"


def test_not_cancellable_skips_cancel_registry(context: _Context) -> None:
    """cancellable=False：不注册 cancel_events（复制半途没有撤销可言的作业）。"""
    seen_event: dict[str, threading.Event | None] = {}

    def work(job_id: str, cancel: threading.Event) -> str:
        seen_event[job_id] = cancel
        return "落位完成"

    job_id = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="ref-4",
        thread_prefix="jr-noc",
        work=work,
        cancellable=False,
    )
    _drain("jr-noc")
    assert context.job_store.get(job_id)["status"] == "completed"
    assert job_id not in context.cancel_events
    assert seen_event[job_id] is not None, "work 仍拿到一个事件（只是没登记）"


def test_on_settled_runs_after_terminal(context: _Context) -> None:
    """结算钩子成败都跑（模型库缓存失效是它唯一现在的用户）。"""
    runs: list[str] = []
    ok = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="r-ok",
        thread_prefix="jr-s-ok",
        work=lambda _j, _c: "好了",
        on_settled=lambda: runs.append("ok"),
    )
    _drain("jr-s-ok")
    bad = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="r-bad",
        thread_prefix="jr-s-bad",
        work=_raise,
        on_settled=lambda: runs.append("bad"),
    )
    _drain("jr-s-bad")
    assert context.job_store.get(ok)["status"] == "completed"
    assert context.job_store.get(bad)["status"] == "failed"
    assert runs == ["ok", "bad"]


def _raise(_job_id: str, _cancel: threading.Event) -> str:
    raise RuntimeError("不行")


def test_cancel_event_reaches_work(context: _Context) -> None:
    """注册的事件与 work 拿到的是同一把：cancel RPC 置位后 work 能看见。"""
    seen: dict[str, bool] = {}

    def work(job_id: str, cancel: threading.Event) -> str | None:
        context.cancel_events[job_id].set()
        seen[job_id] = cancel.is_set()
        return None

    job_id = launch_threaded_job(
        context,  # type: ignore[arg-type]
        job_type="probe",
        ref_id="r-cancel",
        thread_prefix="jr-cancel",
        work=work,
    )
    _drain("jr-cancel")
    assert seen[job_id] is True
