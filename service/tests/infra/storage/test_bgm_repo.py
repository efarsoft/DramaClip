"""repos.bgm：019 表仓储（幂等 upsert / 确定性清单 / 情绪过滤 / 删除对账）。"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import bgm


def _upsert(
    conn: sqlite3.Connection, path: str, emotion: str = "suspense", bpm: float | None = 110.0
) -> None:
    bgm.upsert_track(
        conn,
        file_path=path,
        emotion=emotion,
        duration_s=60.0,
        bpm=bpm,
        license="CC-BY 4.0",
        attribution="Tester",
        source_url="https://example.test/x",
    )


def test_upsert_and_list_roundtrip(memory_db: sqlite3.Connection) -> None:
    _upsert(memory_db, "/bgm/suspense/a.wav")
    (row,) = bgm.list_all(memory_db)
    assert row["file_path"] == "/bgm/suspense/a.wav"
    assert row["emotion"] == "suspense"
    assert row["duration_s"] == 60.0
    assert row["bpm"] == 110.0
    assert row["license"] == "CC-BY 4.0"
    assert row["attribution"] == "Tester"
    assert row["source_url"] == "https://example.test/x"
    assert isinstance(row["added_at"], int)


def test_rescan_same_path_is_idempotent(memory_db: sqlite3.Connection) -> None:
    """file_path UNIQUE：重扫同目录覆盖元数据、不重复插行、id/added_at 首见即定。"""
    _upsert(memory_db, "/bgm/suspense/a.wav")
    first = bgm.list_all(memory_db)[0]
    # 二次扫描：librosa 装上后 bpm 从 None 补成真值 / 情绪改判，都只更新不新增
    bgm.upsert_track(
        memory_db,
        file_path="/bgm/suspense/a.wav",
        emotion="anger",
        duration_s=60.0,
        bpm=120.0,
    )
    rows = bgm.list_all(memory_db)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["added_at"] == first["added_at"]
    assert rows[0]["emotion"] == "anger"
    assert rows[0]["bpm"] == 120.0


def test_bpm_none_allowed(memory_db: sqlite3.Connection) -> None:
    _upsert(memory_db, "/bgm/default/a.wav", emotion="default", bpm=None)
    (row,) = bgm.list_all(memory_db)
    assert row["bpm"] is None


def test_list_all_sorted_by_emotion_then_path(memory_db: sqlite3.Connection) -> None:
    _upsert(memory_db, "/bgm/suspense/z.wav", emotion="suspense")
    _upsert(memory_db, "/bgm/anger/b.wav", emotion="anger")
    _upsert(memory_db, "/bgm/anger/a.wav", emotion="anger")
    paths = [row["file_path"] for row in bgm.list_all(memory_db)]
    assert paths == ["/bgm/anger/a.wav", "/bgm/anger/b.wav", "/bgm/suspense/z.wav"]


def test_list_by_emotion_filters(memory_db: sqlite3.Connection) -> None:
    _upsert(memory_db, "/bgm/anger/a.wav", emotion="anger")
    _upsert(memory_db, "/bgm/suspense/b.wav", emotion="suspense")
    assert [r["file_path"] for r in bgm.list_by_emotion(memory_db, "anger")] == [
        "/bgm/anger/a.wav"
    ]
    assert bgm.list_by_emotion(memory_db, "triumph") == []


def test_remove_by_path_reports_hit(memory_db: sqlite3.Connection) -> None:
    _upsert(memory_db, "/bgm/anger/a.wav", emotion="anger")
    assert bgm.remove_by_path(memory_db, "/bgm/anger/a.wav") is True
    assert bgm.remove_by_path(memory_db, "/bgm/anger/a.wav") is False  # 幂等
    assert bgm.list_all(memory_db) == []


def test_migration_creates_bgm_tracks(memory_db: sqlite3.Connection) -> None:
    """019 已随 migrate 建表（memory_db 夹具走全量迁移）。"""
    (count,) = memory_db.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='bgm_tracks'"
    ).fetchone()
    assert count == 1
