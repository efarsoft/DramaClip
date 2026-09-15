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
    "error",
    "duration_s",
    "size_bytes",
    "created_at",
    "completed_at",
    "cover_path",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


# export_jobs 状态词表的唯一拼写源（docs/04 §5.2）。此前同一谓词分写两处：
# api/export.py::retry 用 Python 比 status != "failed"，本模块 reset_for_retry 又用
# SQL 的 WHERE status = 'failed' 做 CAS——两边不一致时并发保护形同虚设，两个重试会
# 渲染进同一产物路径。写入侧一并命名，否则改了常量就是标记函数写进没人比较的孤立值。
# 注意这是 export_jobs 自己的词表，与 jobs 表（infra.jobs.is_terminal）不是同一概念。
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"
STATUS_COMPLETED = "completed"


def create(
    conn: sqlite3.Connection,
    project_id: str,
    plan_id: str,
    narration_mode: str,
) -> str:
    export_id = uuid4().hex
    conn.execute(
        "INSERT INTO export_jobs (id, project_id, narration_plan_id, narration_mode, status,"
        " progress, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (export_id, project_id, plan_id, narration_mode, STATUS_PENDING, _now_ms()),
    )
    conn.commit()
    return export_id


def set_progress(conn: sqlite3.Connection, export_id: str, percent: float) -> None:
    conn.execute("UPDATE export_jobs SET progress = ? WHERE id = ?", (percent, export_id))
    conn.commit()


def mark_completed(conn: sqlite3.Connection, export_id: str, output_path: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET status = ?, progress = 100, output_path = ?,"
        " completed_at = ? WHERE id = ?",
        (STATUS_COMPLETED, output_path, _now_ms(), export_id),
    )
    conn.commit()


def set_meta(
    conn: sqlite3.Connection,
    export_id: str,
    *,
    duration_s: float,
    size_bytes: int,
) -> None:
    conn.execute(
        "UPDATE export_jobs SET duration_s = ?, size_bytes = ? WHERE id = ?",
        (duration_s, size_bytes, export_id),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, export_id: str, error: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET status = ?, error = ? WHERE id = ?",
        (STATUS_FAILED, error, export_id),
    )
    conn.commit()


def reset_stale_pending(conn: sqlite3.Connection) -> int:
    """启动清扫：崩溃残留的 pending 导出记为失败。
    """
    cursor = conn.execute(
        "UPDATE export_jobs SET status = ?, error = '服务中断' WHERE status = ?",
        (STATUS_FAILED, STATUS_PENDING),
    )
    conn.commit()
    return cursor.rowcount or 0


def reset_for_retry(conn: sqlite3.Connection, export_id: str) -> bool:
    """重试前复位（CAS）：仅当仍为 failed 才清 error/产物路径、进度归零、回 pending。
    """
    cursor = conn.execute(
        "UPDATE export_jobs SET status = ?, error = NULL, output_path = NULL,"
        " progress = 0, completed_at = NULL WHERE id = ? AND status = ?",
        (STATUS_PENDING, export_id, STATUS_FAILED),
    )
    conn.commit()
    return (cursor.rowcount or 0) > 0


def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE project_id = ?"
        " ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]


def list_completed_works(conn: sqlite3.Connection, limit: int = 60) -> list[dict[str, Any]]:
    """跨项目已完成成片（作品库），按完成时间倒序并附带项目名。"""
    rows = conn.execute(
        "SELECT e.id, e.project_id, p.name AS project_name, e.narration_mode, e.output_path,"
        " e.duration_s, e.size_bytes, e.completed_at, e.cover_path"
        " FROM export_jobs e JOIN projects p ON p.id = e.project_id"
        " WHERE e.status = ? AND e.output_path IS NOT NULL"
        " ORDER BY COALESCE(e.completed_at, e.created_at) DESC LIMIT ?",
        (STATUS_COMPLETED, limit),
    ).fetchall()
    keys = (
        "id",
        "project_id",
        "project_name",
        "narration_mode",
        "output_path",
        "duration_s",
        "size_bytes",
        "completed_at",
        "cover_path",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def set_cover(conn: sqlite3.Connection, export_id: str, cover_path: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET cover_path = ? WHERE id = ?", (cover_path, export_id)
    )
    conn.commit()


def list_missing_covers(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    """已完成但封面缺失的成片：ensure_covers 的补拍队列。"""
    rows = conn.execute(
        "SELECT id, output_path FROM export_jobs"
        " WHERE status = ? AND output_path IS NOT NULL"
        " AND (cover_path IS NULL OR cover_path = '')"
        " ORDER BY COALESCE(completed_at, created_at) DESC LIMIT ?",
        (STATUS_COMPLETED, limit),
    ).fetchall()
    return [dict(zip(("id", "output_path"), row, strict=True)) for row in rows]


def get(conn: sqlite3.Connection, export_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE id = ?", (export_id,)
    ).fetchone()
    return dict(zip(_COLUMNS, row, strict=True)) if row else None
