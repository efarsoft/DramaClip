"""engines.subtitle：预设加载 / 情绪匹配 / ASS 生成。"""

from __future__ import annotations

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import build_ass
from dramaclip.engines.subtitle.emotion_matcher import match_emotion


def test_builtin_presets_loaded() -> None:
    all_presets = presets.list_presets()
    ids = {preset["preset_id"] for preset in all_presets}
    assert {"calm-narrative", "conflict-impact"} <= ids


def test_get_preset_fallback() -> None:
    assert presets.get_preset("nonexistent")["preset_id"] == "conflict-impact"
    assert presets.get_preset("calm-narrative")["preset_id"] == "calm-narrative"


def test_match_emotion_label_and_keywords() -> None:
    assert match_emotion("随便什么", "Angry") == "anger"
    assert match_emotion("你给我滚出去") == "anger"
    assert match_emotion("我终于翻身了") == "triumph"
    assert match_emotion("今天天气不错") == "default"


def test_build_ass_structure() -> None:
    preset = presets.get_preset("conflict-impact")
    ass = build_ass(
        [
            {"start": 0.5, "end": 3.2, "text": "你给我滚出去！"},
            {"start": 4.0, "end": 6.0, "text": ""},
        ],
        preset,
    )
    assert ass.startswith("[Script Info]")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.50,0:00:03.20" in ass
    assert "你给我滚出去！" in ass
    assert ass.count("Dialogue:") == 1, "空文本行应被跳过"
    assert "\\fad(200,200)" in ass, "冲突预设淡入 200ms"
    assert "&H000000FF" in ass, "anger 情绪红色"


def test_build_ass_climax_layout_centered() -> None:
    preset = presets.get_preset("conflict-impact")
    ass = build_ass([{"start": 0, "end": 2, "text": "我要报仇！"}], preset)
    # 报仇 → triumph 高潮情绪 → climax 布局；margin_v=10（居中）而非底部 90
    assert ",10,,,{" in ass and "\\fscx112" in ass and "&H0000D7FF" in ass
