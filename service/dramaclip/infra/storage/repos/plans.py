"""narration_plans 表仓储。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = (
    "id", "project_id", "narration_mode", "episode_ids", "plan_data", "status", "created_at"
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_dict(row: tuple) -> dict[str, Any]:  # type: ignore[type-arg]
    data = dict(zip(_COLUMNS, row, strict=True))
    data["episode_ids"] = json.loads(data["episode_ids"])
    data["plan_data"] = json.loads(data["plan_data"])
    return data


def create(
    conn: sqlite3.Connection,
    project_id: str,
    narration_mode: str,
    episode_ids: list[str],
    plan_data: dict[str, Any],
    *,
    status: str = "ready",
) -> dict[str, Any]:
    plan_id = uuid4().hex
    conn.execute(
        "INSERT INTO narration_plans (id, project_id, narration_mode, episode_ids, plan_data,"
        " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            project_id,
            narration_mode,
            json.dumps(episode_ids),
            json.dumps(plan_data, ensure_ascii=False),
            status,
            _now_ms(),
        ),
    )
    conn.commit()
    return {"id": plan_id, "project_id": project_id, "narration_mode": narration_mode,
            "episode_ids": episode_ids, "plan_data": plan_data, "status": status,
            "created_at": _now_ms()}


def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans WHERE project_id = ?"
        " ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get(conn: sqlite3.Connection, plan_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None
