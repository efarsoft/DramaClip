"""bgm_tracks 表仓储（C 项第一波）。

层级纪律：repo 只吃标量/dict，不 import engines（BgmTrack → kwargs 的转换在
接线层做）——与 episodes/plans 仓储同形状。

upsert 语义：file_path UNIQUE，重扫同目录幂等（同路径覆盖元数据、保留 id 与
added_at 首见时间；bpm 允许被新扫描覆盖——librosa 装上后重扫会把 None 补成真值）。
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = (
    "id",
    "file_path",
    "emotion",
    "duration_s",
    "bpm",
    "license",
    "attribution",
    "source_url",
    "added_at",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_dict(row: tuple) -> dict[str, Any]:  # type: ignore[type-arg]
    return dict(zip(_COLUMNS, row, strict=True))


def upsert_track(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    emotion: str,
    duration_s: float,
    bpm: float | None,
    license: str = "",
    attribution: str = "",
    source_url: str = "",
) -> None:
    """单曲入库（同路径幂等覆盖）。id/added_at 首见即定，重扫不漂移。"""
    conn.execute(
        "INSERT INTO bgm_tracks"
        " (id, file_path, emotion, duration_s, bpm, license, attribution, source_url, added_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(file_path) DO UPDATE SET"
        " emotion = excluded.emotion,"
        " duration_s = excluded.duration_s,"
        " bpm = excluded.bpm,"
        " license = excluded.license,"
        " attribution = excluded.attribution,"
        " source_url = excluded.source_url",
        (
            uuid4().hex,
            file_path,
            emotion,
            float(duration_s),
            None if bpm is None else float(bpm),
            license,
            attribution,
            source_url,
            _now_ms(),
        ),
    )
    conn.commit()


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """全库清单（emotion, file_path 排序——确定性输出，UI 列表与测试同吃）。"""
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM bgm_tracks ORDER BY emotion, file_path"
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_by_emotion(conn: sqlite3.Connection, emotion: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM bgm_tracks WHERE emotion = ? ORDER BY file_path",
        (emotion,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def remove_by_path(conn: sqlite3.Connection, file_path: str) -> bool:
    """删一条（素材文件被移走/删掉时的库面对账）；返回是否真删了行。"""
    cursor = conn.execute("DELETE FROM bgm_tracks WHERE file_path = ?", (file_path,))
    conn.commit()
    return cursor.rowcount > 0
