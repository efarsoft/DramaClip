"""export_jobs 表仓储。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = (
    "id",
    "project_id",
    "narration_plan_id",
    "narration_mode",
    "output_path",
    "status",
    "progress",
    "duration_s",
    "size_bytes",
    "created_at",
    "completed_at",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def create(
    conn: sqlite3.Connection,
    project_id: str,
    plan_id: str,
    narration_mode: str,
) -> str:
    export_id = uuid4().hex
    conn.execute(
        "INSERT INTO export_jobs (id, project_id, narration_plan_id, narration_mode, status,"
        " progress, created_at) VALUES (?, ?, ?, ?, 'pending', 0, ?)",
        (export_id, project_id, plan_id, narration_mode, _now_ms()),
    )
    conn.commit()
    return export_id


def set_output(conn: sqlite3.Connection, export_id: str, output_path: str) -> None:
    conn.execute("UPDATE export_jobs SET output_path = ? WHERE id = ?", (output_path, export_id))
    conn.commit()


def set_progress(conn: sqlite3.Connection, export_id: str, percent: float) -> None:
    conn.execute("UPDATE export_jobs SET progress = ? WHERE id = ?", (percent, export_id))
    conn.commit()


def mark_completed(conn: sqlite3.Connection, export_id: str, output_path: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET status = 'completed', progress = 100, output_path = ?,"
        " completed_at = ? WHERE id = ?",
        (output_path, _now_ms(), export_id),
    )
    conn.commit()


def set_meta(conn: sqlite3.Connection, export_id: str, *, duration_s: float, size_bytes: int) -> None:
    conn.execute(
        "UPDATE export_jobs SET duration_s = ?, size_bytes = ? WHERE id = ?",
        (duration_s, size_bytes, export_id),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, export_id: str, error: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET status = 'failed', error = ? WHERE id = ?", (error, export_id)
    )
    conn.commit()


def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE project_id = ?"
        " ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]


def get(conn: sqlite3.Connection, export_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE id = ?", (export_id,)
    ).fetchone()
    return dict(zip(_COLUMNS, row, strict=True)) if row else None
