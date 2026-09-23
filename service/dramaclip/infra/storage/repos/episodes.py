"""episodes 表仓储。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = (
    "id",
    "project_id",
    "episode_number",
    "source_path",
    "duration",
    "status",
    "created_at",
    "name",
    "cover_path",
    "source_signature",
    "has_audio",
)


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
        has_audio = episode.get("has_audio")
        conn.execute(
            "INSERT INTO episodes (id, project_id, episode_number, source_path, duration,"
            " status, created_at, name, has_audio) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (
                uuid4().hex,
                project_id,
                int(episode["episode_number"]),
                str(episode["source_path"]),
                float(episode["duration"]),
                now,
                str(episode.get("name", "")),
                None if has_audio is None else int(bool(has_audio)),
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


def set_cover(conn: sqlite3.Connection, episode_id: str, cover_path: str) -> None:
    conn.execute("UPDATE episodes SET cover_path = ? WHERE id = ?", (cover_path, episode_id))
    conn.commit()


def set_source_signature(conn: sqlite3.Connection, episode_id: str, signature: str) -> None:
    """记录「当前分析/预筛产物对应哪份源」（B8 失效判据）。逐集 WHERE id 写，
    共享连接上与 set_status 同形，多集作业互不覆盖。"""
    conn.execute(
        "UPDATE episodes SET source_signature = ? WHERE id = ?", (signature, episode_id)
    )
    conn.commit()


def reorder(
    conn: sqlite3.Connection,
    project_id: str,
    ordered_ids: list[str],
) -> bool:
    """手动排序：按给定 id 顺序重编 episode_number（1..N）。"""
    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM episodes WHERE project_id = ?", (project_id,)
        ).fetchall()
    }
    if len(ordered_ids) != len(existing) or set(ordered_ids) != existing:
        return False
    # UNIQUE(project_id, episode_number)：先落负数暂存位，再写最终 1..N
    for index, episode_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE episodes SET episode_number = ? WHERE id = ?",
            (-index - 1, episode_id),
        )
    for index, episode_id in enumerate(ordered_ids, start=1):
        conn.execute(
            "UPDATE episodes SET episode_number = ? WHERE id = ?", (index, episode_id)
        )
    conn.commit()
    return True


def reset_stale_analyzing(conn: sqlite3.Connection) -> int:
    """启动清扫：崩溃残留的 analyzing 集回退 prescreened（无服务运行=无分析在跑，恒安全）。"""
    cursor = conn.execute("UPDATE episodes SET status = 'prescreened' WHERE status = 'analyzing'")
    conn.commit()
    return cursor.rowcount or 0
