"""narration_plans 表仓储。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = (
    "id", "project_id", "narration_mode", "episode_ids", "plan_data", "status", "created_at",
    "angle", "angle_reason", "variant_index", "overlap_max", "batch_id", "titles",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_dict(row: tuple) -> dict[str, Any]:  # type: ignore[type-arg]
    data = dict(zip(_COLUMNS, row, strict=True))
    data["episode_ids"] = json.loads(data["episode_ids"])
    data["plan_data"] = json.loads(data["plan_data"])
    data["titles"] = json.loads(data["titles"]) if data["titles"] else []
    return data


def set_titles(conn: sqlite3.Connection, plan_id: str, titles: str) -> None:
    conn.execute("UPDATE narration_plans SET titles = ? WHERE id = ?", (titles, plan_id))
    conn.commit()


def update_plan_data(conn: sqlite3.Connection, plan_id: str, plan_data: dict[str, Any]) -> None:
    """配音回填后把 plan_data 写回（audio_path / duration）。"""
    conn.execute(
        "UPDATE narration_plans SET plan_data = ? WHERE id = ?",
        (json.dumps(plan_data, ensure_ascii=False), plan_id),
    )
    conn.commit()


def create(
    conn: sqlite3.Connection,
    project_id: str,
    narration_mode: str,
    episode_ids: list[str],
    plan_data: dict[str, Any],
    *,
    status: str = "ready",
    angle: str = "",
    angle_reason: str = "",
    variant_index: int = 1,
    overlap_max: float | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """建一条方案行并原样返回（含五个角度字段）。
    """
    plan_id = uuid4().hex
    created_at = _now_ms()
    conn.execute(
        "INSERT INTO narration_plans (id, project_id, narration_mode, episode_ids, plan_data,"
        " status, created_at, angle, angle_reason, variant_index, overlap_max, batch_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            project_id,
            narration_mode,
            json.dumps(episode_ids),
            json.dumps(plan_data, ensure_ascii=False),
            status,
            created_at,
            angle,
            angle_reason,
            variant_index,
            overlap_max,
            batch_id,
        ),
    )
    conn.commit()
    return {
        "id": plan_id,
        "project_id": project_id,
        "narration_mode": narration_mode,
        "episode_ids": episode_ids,
        "plan_data": plan_data,
        "status": status,
        "created_at": created_at,
        "angle": angle,
        "angle_reason": angle_reason,
        "variant_index": variant_index,
        "overlap_max": overlap_max,
        "batch_id": batch_id,
    }


def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    """项目全部方案，最近优先。
    """
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans WHERE project_id = ?"
        " ORDER BY created_at DESC, id",
        (project_id,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_by_batch(
    conn: sqlite3.Connection, project_id: str, batch_id: str
) -> list[dict[str, Any]]:
    """一次 plan_variants 调用产出的整组方案，按 (模式, 变体号) 升序。
    """
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans"
        " WHERE project_id = ? AND batch_id = ?"
        " ORDER BY narration_mode, variant_index",
        (project_id, batch_id),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get(conn: sqlite3.Connection, plan_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None
