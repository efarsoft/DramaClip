"""engines.subtitle：卡拉OK节奏与预设。"""

from __future__ import annotations

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import build_ass


def test_karaoke_preset_loaded() -> None:
    ids = {p["preset_id"] for p in presets.list_presets()}
    assert "karaoke-pop" in ids


def test_karaoke_rhythm_emits_k_tags() -> None:
    preset = presets.get_preset("karaoke-pop")
    ass = build_ass([{"start": 0.0, "end": 4.0, "text": "真相大白"}], preset)
    assert "\\k" in ass, "卡拉OK预设应生成 \\k 标签"
    # 4 字 / 4s → 每字 100 厘秒
    assert "\\k100" in ass
    # "真相"命中悬疑 → 已唱色黄色；未唱暗灰
    assert "\\1c&H0000FFFF" in ass
    assert "\\2c&H5A5A5A" in ass


def test_whole_line_rhythm_has_no_k_tags() -> None:
    preset = presets.get_preset("calm-narrative")
    ass = build_ass([{"start": 0.0, "end": 3.0, "text": "平静叙述"}], preset)
    assert "\\k" not in ass


def test_karaoke_single_char_minimum() -> None:
    preset = presets.get_preset("karaoke-pop")
    ass = build_ass([{"start": 0.0, "end": 0.1, "text": "爆"}], preset)
    assert "\\k10}" in ass, "0.1s = 10 厘秒"
