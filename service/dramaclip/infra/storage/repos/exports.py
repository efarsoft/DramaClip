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
    "selfcheck",
    "selfcheck_state",
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
STATUS_CANCELLED = "cancelled"


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


def mark_cancelled(conn: sqlite3.Connection, export_id: str) -> None:
    """取消不是失败：作品库不收，队列不当出错。"""
    conn.execute(
        "UPDATE export_jobs SET status = ?, error = NULL WHERE id = ?",
        (STATUS_CANCELLED, export_id),
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

    自检成绩单随旧产物一并作废（selfcheck 清 NULL）：重渲染会产出新文件，
    旧成绩单描述的是不存在的东西，留着就是假绿灯。
    """
    cursor = conn.execute(
        "UPDATE export_jobs SET status = ?, error = NULL, output_path = NULL,"
        " progress = 0, completed_at = NULL, selfcheck = NULL, selfcheck_state = NULL"
        " WHERE id = ? AND status = ?",
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


_WORKS_KEYS = (
    "id",
    "project_id",
    "project_name",
    "narration_mode",
    "output_path",
    "duration_s",
    "size_bytes",
    "completed_at",
    "cover_path",
    "narration_plan_id",
    "selfcheck",
    "selfcheck_state",
    "angle",
    "episode_ids",
)

# 「筛选·自检通过」（09-10 #30）的词表：三值等值匹配汇总列，unchecked 匹配
# 「从未自检」。词表外的值由 api 层挡掉（传 None 进来 = 不筛）。
WORKS_STATE_FILTERS = ("passed", "failed", "partial", "unchecked")


def list_completed_works(
    conn: sqlite3.Connection, limit: int = 60, *, state: str | None = None
) -> list[dict[str, Any]]:
    """跨项目已完成成片（作品库），按完成时间倒序，附项目名与方案角度/取材集。

    方案已删的成片仍要列出来（LEFT JOIN，angle/episode_ids 为 NULL）——片子
    还在盘上，不能因为追溯链断了就从作品库消失。
    """
    sql = (
        "SELECT e.id, e.project_id, p.name AS project_name, e.narration_mode, e.output_path,"
        " e.duration_s, e.size_bytes, e.completed_at, e.cover_path,"
        " e.narration_plan_id, e.selfcheck, e.selfcheck_state, np.angle, np.episode_ids"
        " FROM export_jobs e JOIN projects p ON p.id = e.project_id"
        " LEFT JOIN narration_plans np ON np.id = e.narration_plan_id"
        " WHERE e.status = ? AND e.output_path IS NOT NULL"
    )
    args: list[Any] = [STATUS_COMPLETED]
    if state == "unchecked":
        sql += " AND e.selfcheck_state IS NULL"
    elif state is not None:
        sql += " AND e.selfcheck_state = ?"
        args.append(state)
    sql += " ORDER BY COALESCE(e.completed_at, e.created_at) DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return [dict(zip(_WORKS_KEYS, row, strict=True)) for row in rows]


def set_selfcheck(conn: sqlite3.Connection, export_id: str, payload: str, state: str) -> None:
    """落一份自检成绩单（JSON 文本）+ 汇总态；state 词表 = WORKS_STATE_FILTERS 前三值。"""
    conn.execute(
        "UPDATE export_jobs SET selfcheck = ?, selfcheck_state = ? WHERE id = ?",
        (payload, state, export_id),
    )
    conn.commit()


def list_missing_selfcheck(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    """已完成但从未自检的成片：export.selfcheck 的补测队列（形状仿 list_missing_covers）。"""
    rows = conn.execute(
        "SELECT id, output_path, narration_plan_id, narration_mode FROM export_jobs"
        " WHERE status = ? AND output_path IS NOT NULL AND selfcheck IS NULL"
        " ORDER BY COALESCE(completed_at, created_at) DESC LIMIT ?",
        (STATUS_COMPLETED, limit),
    ).fetchall()
    return [
        dict(zip(("id", "output_path", "narration_plan_id", "narration_mode"), row, strict=True))
        for row in rows
    ]


def delete(conn: sqlite3.Connection, export_id: str) -> int:
    """删除导出记录行（文件搬移在 api 层先做，后删行；见 export.delete）。"""
    cursor = conn.execute("DELETE FROM export_jobs WHERE id = ?", (export_id,))
    conn.commit()
    return cursor.rowcount or 0


def set_cover(conn: sqlite3.Connection, export_id: str, cover_path: str) -> None:
    conn.execute(
        "UPDATE export_jobs SET cover_path = ? WHERE id = ?", (cover_path, export_id)
    )
    conn.commit()


def list_missing_covers(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    """已完成但封面缺失的成片：ensure_covers 的补拍队列。"""
    rows = conn.execute(
        "SELECT id, output_path, narration_plan_id FROM export_jobs"
        " WHERE status = ? AND output_path IS NOT NULL"
        " AND (cover_path IS NULL OR cover_path = '')"
        " ORDER BY COALESCE(completed_at, created_at) DESC LIMIT ?",
        (STATUS_COMPLETED, limit),
    ).fetchall()
    return [
        dict(zip(("id", "output_path", "narration_plan_id"), row, strict=True)) for row in rows
    ]


def get(conn: sqlite3.Connection, export_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM export_jobs WHERE id = ?", (export_id,)
    ).fetchone()
    return dict(zip(_COLUMNS, row, strict=True)) if row else None
