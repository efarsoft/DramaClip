"""infra.config：默认值合并与类型读取。"""

from __future__ import annotations

import sqlite3

import pytest

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


def test_get_float_falls_back_to_defaults_on_dirty_value() -> None:
    key = "export.loudness_target_lufs"
    assert config.get_float({key: "-12"}, key) == -12.0  # 用户覆盖优先
    assert config.get_float({key: "abc"}, key) == -14.0  # 脏值回退 DEFAULTS
    assert config.get_float({}, key) == -14.0  # 缺键回退 DEFAULTS
    assert config.get_float({}, "export.loudness_true_peak_dbtp") == -1.5


def test_get_float_raises_for_key_outside_defaults() -> None:
    """`get_float` 比 `get_int` 严：DEFAULTS 里没有的键直接 KeyError，不回 0.0。

    这是有意的分歧，不是待统一的疏漏。响度目标写错一个键名时，静默给 0.0 会把整片推到
    0 LUFS（还顺带炸真峰值门限），比当场报错难查得多。别为了"两个 getter 长得不一样"
    就把它改成 `DEFAULTS.get(key, "0")`。
    """
    with pytest.raises(KeyError):
        config.get_float({}, "export.loudness_typo")
