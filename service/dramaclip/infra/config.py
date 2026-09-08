"""设置：代码默认值 + DB 覆盖。DB 为唯一读取源（docs/service/03 第 2 节）。

键清单与 docs/service/04-数据模型.md §3 settings 表一致。
"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import settings as settings_repo

DEFAULTS: dict[str, str] = {
    "analysis.full_threshold": "15",
    "analysis.prescreen_threshold": "70",
    "asr.engine": "faster_whisper",
    "asr.model": "small",
    "asr.device": "cpu",
    "asr.language": "zh",
    "subtitle.default_preset": "conflict-impact",
    "subtitle.smart_match": "true",
    "llm.base_url": "",
    "llm.api_key": "",
    "llm.model": "",
    "tts.engine": "kokoro",
    "tts.voice": "zf_001",
    "narration.style_id": "general",
    "strategy.min_duration_s": "30",
    "strategy.max_duration_s": "300",
    "export.encoder": "h264",
    "export.bitrate_kbps": "8000",
    "export.width": "1080",
    "export.height": "1920",
    "hardware.max_parallel_jobs": "2",
}

Settings = dict[str, str]


def load(conn: sqlite3.Connection) -> Settings:
    """缺省键全量落库，返回完整设置（默认值 + 用户覆盖）。"""
    stored = settings_repo.get_all(conn)
    for key, value in DEFAULTS.items():
        if key not in stored:
            settings_repo.set_value(conn, key, value)
            stored[key] = value
    return stored


def get_int(settings: Settings, key: str) -> int:
    """按 int 读取；缺失/非法回退默认值（docs/service/03 第 2 节约定）。"""
    try:
        return int(settings[key])
    except (KeyError, ValueError):
        return int(DEFAULTS.get(key, "0"))
