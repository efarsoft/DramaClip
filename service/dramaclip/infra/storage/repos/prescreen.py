"""episode_prescreen 表仓储（预筛结果，每集一条）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def upsert(
    conn: sqlite3.Connection,
    episode_id: str,
    *,
    audio_peak_density: float,
    scene_cut_density: float,
    voice_activity_ratio: float,
    motion_intensity: float,
    prescreen_score: float,
    recommended: bool,
) -> None:
    conn.execute(
        "INSERT INTO episode_prescreen"
        " (episode_id, audio_peak_density, scene_cut_density, voice_activity_ratio,"
        "  motion_intensity, prescreen_score, recommended, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(episode_id) DO UPDATE SET"
        " audio_peak_density = excluded.audio_peak_density,"
        " scene_cut_density = excluded.scene_cut_density,"
        " voice_activity_ratio = excluded.voice_activity_ratio,"
        " motion_intensity = excluded.motion_intensity,"
        " prescreen_score = excluded.prescreen_score,"
        " recommended = excluded.recommended,"
        " created_at = excluded.created_at",
        (
            episode_id,
            audio_peak_density,
            scene_cut_density,
            voice_activity_ratio,
            motion_intensity,
            prescreen_score,
            int(recommended),
            _now_ms(),
        ),
    )
    conn.commit()


def get(conn: sqlite3.Connection, episode_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT episode_id, audio_peak_density, scene_cut_density, voice_activity_ratio,"
        " motion_intensity, prescreen_score, recommended, created_at"
        " FROM episode_prescreen WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    if row is None:
        return None
    keys = (
        "episode_id",
        "audio_peak_density",
        "scene_cut_density",
        "voice_activity_ratio",
        "motion_intensity",
        "prescreen_score",
        "recommended",
        "created_at",
    )
    return dict(zip(keys, row, strict=True))
