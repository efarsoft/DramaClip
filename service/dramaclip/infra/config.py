"""设置：代码默认值 + DB 覆盖。DB 为唯一读取源（docs/service/03 第 2 节）。
"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import settings as settings_repo

# 单一真相源（docs/04 §5.2）：以下数值只在此处定义一次，别处一律 import 不再各写一份。
# 放在 infra 而非渲染层，是因为依赖方向恒为 engines → infra——
# 反过来让 encoder 当设置的源会成环，所以设置的默认值与渲染几何同源读这里。
EXPORT_WIDTH = 1080  # 竖屏画幅（无 UI 覆盖，仅 settings 键可改；见 docs/service/04 §3）
EXPORT_HEIGHT = 1920
PRESCREEN_THRESHOLD = 70  # 预筛推荐线：评分量纲 0-100（prescreen 四项权重和为 100）

DEFAULTS: dict[str, str] = {
    "analysis.full_threshold": "15",
    "analysis.prescreen_threshold": str(PRESCREEN_THRESHOLD),
    "analysis.ocr_enabled": "1",
    "asr.engine": "faster_whisper",
    "asr.model": "small",
    "asr.device": "auto",
    "asr.compute_type": "int8",
    "asr.language": "zh",
    "subtitle.default_preset": "conflict-impact",
    "subtitle.smart_match": "true",
    "llm.base_url": "",
    "llm.api_key": "",
    "llm.model": "",
    "tts.engine": "kokoro",
    "tts.voice": "zf_001",
    "narration.style_id": "auto",
    # 每模式的方案数 K（规格 §4.3「方案数 K 」的全局默认；项目级覆盖走 projects.settings）
    "narration.variants_per_mode": "3",
    "strategy.min_duration_s": "30",
    "strategy.max_duration_s": "300",
    "download.hf_mirror": "https://hf-mirror.com",
    "download.ms_base": "https://modelscope.cn",
    # 成片响度目标（EBU R128）：Phase C 整片两遍 loudnorm 收口，见 engines/exporter/loudness.py
    "export.loudness_target_lufs": "-14",
    "export.loudness_true_peak_dbtp": "-1.5",
    "export.width": str(EXPORT_WIDTH),
    "export.height": str(EXPORT_HEIGHT),
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


def get_float(settings: Settings, key: str) -> float:
    """按 float 读取；settings 里缺失或脏值回退 DEFAULTS。
    """
    try:
        return float(settings[key])
    except (KeyError, ValueError, TypeError):
        return float(DEFAULTS[key])
