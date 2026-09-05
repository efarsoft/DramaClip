"""projects 表仓储。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = ("id", "name", "source_path", "status", "created_at", "updated_at")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_dict(row: tuple, episode_count: int = 0) -> dict[str, Any]:  # type: ignore[type-arg]
    return dict(zip(_COLUMNS, row, strict=True)) | {"episode_count": episode_count}


def create(conn: sqlite3.Connection, name: str, source_path: str) -> dict[str, Any]:
    project_id = uuid4().hex
    now = _now_ms()
    conn.execute(
        "INSERT INTO projects (id, name, source_path, status, created_at, updated_at)"
        " VALUES (?, ?, ?, 'created', ?, ?)",
        (project_id, name, source_path, now, now),
    )
    conn.commit()
    return {
        "id": project_id,
        "name": name,
        "source_path": source_path,
        "status": "created",
        "created_at": now,
        "episode_count": 0,
    }


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.id, p.name, p.source_path, p.status, p.created_at, p.updated_at,"
        " COUNT(e.id) AS episode_count"
        " FROM projects p LEFT JOIN episodes e ON e.project_id = p.id"
        " GROUP BY p.id ORDER BY p.created_at DESC"
    ).fetchall()
    return [dict(zip((*_COLUMNS, "episode_count"), row, strict=True)) for row in rows]


def get(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return None
    count = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    return _row_to_dict(row, int(count))


def set_status(conn: sqlite3.Connection, project_id: str, status: str) -> None:
    conn.execute(
        "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now_ms(), project_id),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, project_id: str) -> bool:
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return cursor.rowcount > 0
