"""JobStore：标签写入与跨类型列表（队列页数据源）。"""

from __future__ import annotations

import sqlite3
import time

from dramaclip.infra import jobs as jobs_mod


def test_set_progress_updates_label(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.set_progress(job_id, 42.0, label="切割 5/8")
    assert store.get(job_id)["label"] == "切割 5/8"


def test_list_recent_spans_types_and_is_newest_first(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    first = store.create("analysis", ref_id="p1")
    time.sleep(0.005)  # updated_at 是毫秒精度；不留间隔则同毫秒内顺序不确定
    second = store.create("prescreen", ref_id="p1")
    store.mark_running(first)
    time.sleep(0.005)
    store.set_progress(first, 10.0, label="第1集 转写中")
    time.sleep(0.005)  # 同上：完成 second 必须严格晚于 first 的最后一次进度写入
    store.mark_completed(second)
    rows = store.list_recent(limit=10)
    ids = [row["id"] for row in rows]
    assert ids[0] == second                      # 最新变更在前
    assert set(ids) == {first, second}
    assert rows[0]["type"] == "prescreen"
    assert any(row["label"] == "第1集 转写中" for row in rows)


def test_list_recent_filters_out_terminal_when_asked(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    live = store.create("export", ref_id="e1")
    done = store.create("export", ref_id="e2")
    store.mark_running(done)
    store.mark_completed(done)
    active = store.list_recent(limit=10, active_only=True)
    assert [row["id"] for row in active] == [live]
