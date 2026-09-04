"""infra.config：默认值合并与类型读取。"""

from __future__ import annotations

import sqlite3

from dramaclip.infra import config


def test_load_persists_defaults_and_merges(memory_db: sqlite3.Connection) -> None:
    settings_repo_set_stub(memory_db)  # 预置一个用户覆盖
    settings = config.load(memory_db)
    assert settings["analysis.full_threshold"] == "15"
    assert settings["llm.model"] == "custom-model"  # 用户覆盖优先
    stored = dict(memory_db.execute("SELECT key, value FROM settings").fetchall())
    assert len(stored) == len(config.DEFAULTS)  # 缺省键已全量落库


def settings_repo_set_stub(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('llm.model', 'custom-model', 0)"
    )
    conn.commit()


def test_get_int_fallback_on_invalid(memory_db: sqlite3.Connection) -> None:
    config.load(memory_db)
    settings = dict(memory_db.execute("SELECT key, value FROM settings").fetchall())
    settings["hardware.max_parallel_jobs"] = "oops"
    assert config.get_int(settings, "hardware.max_parallel_jobs") == 2  # 回退默认
    assert config.get_int(settings, "analysis.full_threshold") == 15
