"""episodes 表仓储。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = ("id", "project_id", "episode_number", "source_path", "duration", "status", "created_at")


def _now_ms() -> int:
    return int(time.time() * 1000)


def replace_all(
    conn: sqlite3.Connection,
    project_id: str,
    episodes: list[dict[str, Any]],
) -> int:
    """全量替换项目集列表（导入=重新扫描语义；id 重建，分析结果随旧 id 级联删除）。"""
    now = _now_ms()
    conn.execute("DELETE FROM episodes WHERE project_id = ?", (project_id,))
    for episode in episodes:
        conn.execute(
            "INSERT INTO episodes (id, project_id, episode_number, source_path, duration,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (
                uuid4().hex,
                project_id,
                int(episode["episode_number"]),
                str(episode["source_path"]),
                float(episode["duration"]),
                now,
            ),
        )
    conn.commit()
    return len(episodes)


def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM episodes WHERE project_id = ?"
        " ORDER BY episode_number",
        (project_id,),
    ).fetchall()
    return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]


def get(conn: sqlite3.Connection, episode_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_COLUMNS, row, strict=True))


def list_by_ids(conn: sqlite3.Connection, episode_ids: list[str]) -> list[dict[str, Any]]:
    if not episode_ids:
        return []
    placeholders = ", ".join("?" for _ in episode_ids)
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM episodes WHERE id IN ({placeholders})"
        " ORDER BY episode_number",
        episode_ids,
    ).fetchall()
    return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]


def set_status(conn: sqlite3.Connection, episode_id: str, status: str) -> None:
    conn.execute("UPDATE episodes SET status = ? WHERE id = ?", (status, episode_id))
    conn.commit()
