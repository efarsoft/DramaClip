"""episodes repo：状态清扫（崩溃残留 analyzing 回退）。"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import episodes as episodes_repo


def _make_episode(conn: sqlite3.Connection, project_id: str = "p1", episode_id: str = "e1") -> str:
    conn.execute(
        "INSERT INTO projects (id, name, source_path, status, created_at, updated_at)"
        " VALUES (?, 'n', ?, 'created', 1, 1)",
        (project_id, f"/tmp/{project_id}"),
    )
    conn.execute(
        "INSERT INTO episodes (id, project_id, episode_number, source_path, duration,"
        " status, created_at) VALUES (?, ?, 1, '/tmp/a.mp4', 1.0, 'pending', 1)",
        (episode_id, project_id),
    )
    conn.commit()
    return episode_id


def test_reset_stale_analyzing_resets_only_analyzing(memory_db: sqlite3.Connection) -> None:
    keep = _make_episode(memory_db, "p1", "e-done")
    stale = _make_episode(memory_db, "p2", "e-stale")
    memory_db.execute("UPDATE episodes SET status = 'done' WHERE id = ?", (keep,))
    memory_db.execute("UPDATE episodes SET status = 'analyzing' WHERE id = ?", (stale,))
    memory_db.commit()

    reset = episodes_repo.reset_stale_analyzing(memory_db)

    assert reset == 1
    statuses = dict(
        memory_db.execute("SELECT id, status FROM episodes").fetchall()
    )
    assert statuses == {keep: "done", stale: "prescreened"}


def test_reset_stale_analyzing_noop_when_none(memory_db: sqlite3.Connection) -> None:
    _make_episode(memory_db, "p1", "e1")
    assert episodes_repo.reset_stale_analyzing(memory_db) == 0
