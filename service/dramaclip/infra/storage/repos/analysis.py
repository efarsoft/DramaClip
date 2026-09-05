"""episode_analysis 表仓储（upsert 语义：重分析覆盖旧结果）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4


def upsert(
    conn: sqlite3.Connection,
    episode_id: str,
    *,
    asr_segments: str,
    scene_data: str | None,
    audio_features: str | None,
    conflict_scores: str | None = None,
    highlights: str | None = None,
    genre: str | None = None,
) -> None:
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO episode_analysis"
        " (id, episode_id, asr_segments, scene_data, audio_features,"
        "  conflict_scores, highlights, genre, analyzed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(episode_id) DO UPDATE SET"
        " asr_segments = excluded.asr_segments, scene_data = excluded.scene_data,"
        " audio_features = excluded.audio_features, conflict_scores = excluded.conflict_scores,"
        " highlights = excluded.highlights, genre = excluded.genre,"
        " analyzed_at = excluded.analyzed_at",
        (
            uuid4().hex,
            episode_id,
            asr_segments,
            scene_data,
            audio_features,
            conflict_scores,
            highlights,
            genre,
            now,
        ),
    )
    conn.commit()


def update_asr_segments(conn: sqlite3.Connection, episode_id: str, segments_json: str) -> bool:
    """仅覆盖 asr_segments（用户修正转写），其余语义列保留。"""
    cursor = conn.execute(
        "UPDATE episode_analysis SET asr_segments = ?, analyzed_at = ? WHERE episode_id = ?",
        (segments_json, int(time.time() * 1000), episode_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get(conn: sqlite3.Connection, episode_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, episode_id, asr_segments, scene_data, audio_features, conflict_scores,"
        " highlights, genre, characters, analyzed_at FROM episode_analysis WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    if row is None:
        return None
    keys = (
        "id",
        "episode_id",
        "asr_segments",
        "scene_data",
        "audio_features",
        "conflict_scores",
        "highlights",
        "genre",
        "characters",
        "analyzed_at",
    )
    return dict(zip(keys, row, strict=True))


def exists(conn: sqlite3.Connection, episode_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM episode_analysis WHERE episode_id = ?", (episode_id,)
    ).fetchone()
    return row is not None
