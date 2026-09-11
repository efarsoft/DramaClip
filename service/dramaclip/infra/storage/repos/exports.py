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


def set_output(conn: sqlite3.Connection, export_id: str, output_path: str) -> None:
    conn.execute("UPDATE export_jobs SET output_path = ? WHERE id = ?", (output_path, export_id))
    conn.commit()


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

    无服务运行即无导出在跑，故恒安全；已完成/已失败记录不动。
    进度保留原值——与 JobStore.sweep_interrupted 对 jobs 的处理一致，两表不得互相矛盾。
    认残留的依据就是 STATUS_PENDING：凡新建/复位重试都写回该值，故这里无需再认 'running'。
    """
    cursor = conn.execute(
        "UPDATE export_jobs SET status = ?, error = '服务中断' WHERE status = ?",
        (STATUS_FAILED, STATUS_PENDING),
    )
    conn.commit()
    return cursor.rowcount or 0


def reset_for_retry(conn: sqlite3.Connection, export_id: str) -> bool:
    """重试前复位（CAS）：仅当仍为 failed 才清 error/产物路径、进度归零、回 pending。

    复位到 STATUS_PENDING 而非引入 'running'：启动清扫 reset_stale_pending 正是按
    该值认崩溃残留，重试中途再次崩溃时该记录仍会被正确复位。
    WHERE 带 STATUS_FAILED 是为并发重试：两个 export.retry 同时通过"是否 failed"的
    Python 检查时，只有一个能复位成功，另一个据返回值被判为不可重试，避免双双渲染进
    同一文件。该 SQL 条件与 api/export.py 的比较读的是同一个常量，不会再各说各话。
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
        " e.duration_s, e.size_bytes, e.completed_at"
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
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def get(conn: sqlite3.Connection, export_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE id = ?", (export_id,)
    ).fetchone()
    return dict(zip(_COLUMNS, row, strict=True)) if row else None
