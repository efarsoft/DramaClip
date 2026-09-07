"""infra.storage：迁移幂等、settings 仓储。"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage import db
from dramaclip.infra.storage.repos import settings as settings_repo


def test_migrate_creates_all_tables(memory_db: sqlite3.Connection) -> None:
    rows = memory_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {row[0] for row in rows}
    expected = {
        "schema_migrations",
        "projects",
        "episodes",
        "episode_prescreen",
        "episode_analysis",
        "narration_plans",
        "export_jobs",
        "tts_cache",
        "subtitle_presets",
        "jobs",
        "settings",
    }
    assert expected <= tables


def test_migrate_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        expected_migrations = [
            "001_init.sql",
            "002_add_audio_features.sql",
            "003_export_meta.sql",
                "004_export_error.sql",
        ]
        assert db.migrate(conn) == expected_migrations
        assert db.migrate(conn) == []  # 第二次全量跳过
    finally:
        conn.close()


def test_settings_roundtrip(memory_db: sqlite3.Connection) -> None:
    assert settings_repo.get_all(memory_db) == {}
    settings_repo.set_value(memory_db, "llm.model", "qwen-plus")
    settings_repo.set_value(memory_db, "llm.model", "qwen-max")  # 覆盖更新
    settings_repo.set_value(memory_db, "tts.engine", "edge")
    assert settings_repo.get_all(memory_db) == {"llm.model": "qwen-max", "tts.engine": "edge"}
