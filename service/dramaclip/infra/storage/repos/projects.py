"""projects 表仓储。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = ("id", "name", "source_path", "status", "created_at", "updated_at", "cover_path",
            "settings")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_settings(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw if raw is not None else "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decoded(data: dict[str, Any]) -> dict[str, Any]:
    """settings 列在库内是 JSON 文本，对外统一返回对象（同 plans.plan_data 套路）。"""
    data["settings"] = _parse_settings(data["settings"])
    return data


def _row_to_dict(row: tuple, episode_count: int = 0) -> dict[str, Any]:  # type: ignore[type-arg]
    return _decoded(dict(zip(_COLUMNS, row, strict=True))) | {"episode_count": episode_count}


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
        "settings": {},
    }


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.id, p.name, p.source_path, p.status, p.created_at, p.updated_at,"
        " p.cover_path, p.settings, COUNT(e.id) AS episode_count"
        " FROM projects p LEFT JOIN episodes e ON e.project_id = p.id"
        " GROUP BY p.id ORDER BY p.created_at DESC"
    ).fetchall()
    return [_decoded(dict(zip((*_COLUMNS, "episode_count"), row, strict=True))) for row in rows]


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


def get_settings(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """项目级覆盖参数；项目不存在或值损坏时回退空字典（空=全部用全局默认）。"""
    row = conn.execute("SELECT settings FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return {}
    return _parse_settings(row[0])


def update_settings(
    conn: sqlite3.Connection, project_id: str, changes: dict[str, Any]
) -> dict[str, Any] | None:
    """合并写入；值为 None 表示清除该键（恢复默认）。项目不存在返回 None。"""
    row = conn.execute("SELECT settings FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    merged = _parse_settings(row[0])
    for key, value in changes.items():
        if value is None:
            merged.pop(str(key), None)
        else:
            merged[str(key)] = value
    conn.execute(
        "UPDATE projects SET settings = ?, updated_at = ? WHERE id = ?",
        (json.dumps(merged, ensure_ascii=False), _now_ms(), project_id),
    )
    conn.commit()
    return merged


def set_status(conn: sqlite3.Connection, project_id: str, status: str) -> None:
    conn.execute(
        "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now_ms(), project_id),
    )
    conn.commit()


def rename(conn: sqlite3.Connection, project_id: str, name: str) -> bool:
    cursor = conn.execute(
        "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now_ms(), project_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def duplicate(conn: sqlite3.Connection, project_id: str, new_name: str) -> dict[str, Any] | None:
    """复制项目元数据与集列表（分析结果不复制，副本需重新分析）。

    settings 覆盖值要复制：复制剧的典型动机是"换素材、按同一套调好的参数再产一批"，
    丢掉 K/档位/风格/字幕预设会逼用户重配一遍。
    """
    source = get(conn, project_id)
    if source is None:
        return None
    created = create(conn, new_name, f"{source['source_path']}#copy-{_now_ms()}")
    if source["settings"]:
        conn.execute(
            "UPDATE projects SET settings = ? WHERE id = ?",
            (json.dumps(source["settings"], ensure_ascii=False), created["id"]),
        )
    conn.execute(
        "INSERT INTO episodes"
        " (id, project_id, episode_number, source_path, duration, status, created_at)"
        " SELECT hex(randomblob(16)), ?, episode_number, source_path, duration, 'pending', ?"
        " FROM episodes WHERE project_id = ?",
        (created["id"], _now_ms(), project_id),
    )
    conn.commit()
    return get(conn, str(created["id"]))


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    """工作台统计卡数据。"""
    project_count = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
    episode_count = int(conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])
    analyzed = int(
        conn.execute("SELECT COUNT(*) FROM episodes WHERE status = 'done'").fetchone()[0]
    )
    exports = int(conn.execute("SELECT COUNT(*) FROM export_jobs").fetchone()[0])
    return {
        "project_count": project_count,
        "episode_count": episode_count,
        "analyzed_episodes": analyzed,
        "export_count": exports,
    }


def delete(conn: sqlite3.Connection, project_id: str) -> bool:
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return cursor.rowcount > 0


def set_cover(conn: sqlite3.Connection, project_id: str, cover_path: str) -> None:
    conn.execute("UPDATE projects SET cover_path = ? WHERE id = ?", (cover_path, project_id))
    conn.commit()
