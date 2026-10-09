"""analysis repo：subtitle_band 列读写（A2 源硬字幕带落库，形状学 ocr_segments）。

NULL 语义：无硬字幕带 / 未探测 / OCR 未装——三种降级共用 NULL，消费端（字幕避让）
对 NULL 一律回退现状 margin_v，不做区分。
"""

from __future__ import annotations

import json
import sqlite3

from dramaclip.infra.storage.repos import analysis as repo


def _seed_episode(conn: sqlite3.Connection, episode_id: str = "e1") -> str:
    conn.execute(
        "INSERT INTO projects (id, name, source_path, status, created_at, updated_at)"
        " VALUES ('p1', 'n', '/tmp/p1', 'created', 1, 1)"
    )
    conn.execute(
        "INSERT INTO episodes (id, project_id, episode_number, source_path, duration,"
        " status, created_at) VALUES (?, 'p1', 1, '/tmp/a.mp4', 1.0, 'pending', 1)",
        (episode_id,),
    )
    conn.commit()
    return episode_id


def _upsert(conn: sqlite3.Connection, episode_id: str, **extra: object) -> None:
    repo.upsert(
        conn,
        episode_id,
        asr_segments="[]",
        scene_data=None,
        audio_features=None,
        **extra,  # type: ignore[arg-type]
    )


def test_subtitle_band_roundtrip(memory_db: sqlite3.Connection) -> None:
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, subtitle_band=json.dumps([0.76, 0.90]))
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["subtitle_band"])) == [0.76, 0.90]


def test_subtitle_band_null_by_default(memory_db: sqlite3.Connection) -> None:
    """不传 band（OCR 未装/未探测）→ NULL 透传，读端拿到 None。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id)
    row = repo.get(memory_db, episode_id)
    assert row is not None and row["subtitle_band"] is None


def test_reupsert_without_band_preserves_previous(memory_db: sqlite3.Connection) -> None:
    """与 ocr_segments 同款 COALESCE 语义：本轮没探到不清掉上一轮的结果。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, subtitle_band=json.dumps([0.8, 0.92]))
    _upsert(memory_db, episode_id)  # 重分析但 OCR 降级 → band=None
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["subtitle_band"])) == [0.8, 0.92]


def test_reupsert_with_new_band_overwrites(memory_db: sqlite3.Connection) -> None:
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, subtitle_band=json.dumps([0.8, 0.92]))
    _upsert(memory_db, episode_id, subtitle_band=json.dumps([0.6, 0.7]))
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["subtitle_band"])) == [0.6, 0.7]


def test_update_asr_keeps_subtitle_band(memory_db: sqlite3.Connection) -> None:
    """其余列的定点更新不得碰 subtitle_band。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, subtitle_band=json.dumps([0.7, 0.8]))
    repo.update_asr_segments(memory_db, episode_id, "[]")
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["subtitle_band"])) == [0.7, 0.8]


def test_update_subtitle_band_roundtrip(memory_db: sqlite3.Connection) -> None:
    """定点更新（形状学 update_ocr_segments）：只覆盖 subtitle_band，其余列保留。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, ocr_segments="[]")
    assert repo.update_subtitle_band(memory_db, episode_id, json.dumps([0.76, 0.9])) is True
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["subtitle_band"])) == [0.76, 0.9]
    assert row["ocr_segments"] == "[]", "其余列保留"
    assert repo.update_subtitle_band(memory_db, "nope", "[]") is False, "不存在的集返回 False"

def test_visual_track_roundtrip(memory_db: sqlite3.Connection) -> None:
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, visual_track=json.dumps({"contact_sheet": "/d/e1.png"}))
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["visual_track"])) == {"contact_sheet": "/d/e1.png"}


def test_visual_track_null_by_default(memory_db: sqlite3.Connection) -> None:
    """拼图未生成/失败 → NULL 透传，读端拿到 None（分档语义，消费端回退纯台词）。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id)
    row = repo.get(memory_db, episode_id)
    assert row is not None and row["visual_track"] is None


def test_reupsert_without_visual_track_preserves_previous(memory_db: sqlite3.Connection) -> None:
    """COALESCE 语义：语义层单独重跑不带拼图，不清掉上一轮的视觉轨。"""
    episode_id = _seed_episode(memory_db)
    _upsert(memory_db, episode_id, visual_track=json.dumps({"contact_sheet": "/d/e1.png"}))
    _upsert(memory_db, episode_id, highlights="[]")
    row = repo.get(memory_db, episode_id)
    assert row is not None
    assert json.loads(str(row["visual_track"])) == {"contact_sheet": "/d/e1.png"}

