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
    # 报仇 → triumph 高潮情绪 → climax 布局 center_single：必须真的居中（\an5），
    # 而不是贴底只留 10px——后者是「字幕下半被裁」的成因。
    assert "\\an5" in ass and "\\fscx112" in ass and "&H0000D7FF" in ass
    assert _event_fields(ass)[7] == "0", "居中对齐下 MarginV 不参与定位，须为 0"


def _event_fields(ass: str, index: int = 0) -> list[str]:
    """第 index 条 Dialogue 的逗号字段（Format 同序：7 是 MarginV）。"""
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    return lines[index][len("Dialogue: ") :].split(",")


def _style_field(ass: str, index: int) -> str:
    line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    return line[len("Style: ") :].split(",")[index]


def test_layout_dimension_drives_alignment_not_just_margin() -> None:
    """回归守卫：预设的 layout 维度必须落到事件对齐上。

    这条在修复前必红：`_ALIGNMENT` 当时是死代码，Style Alignment 恒为 2（贴底），
    非 bottom_bar 只是把 MarginV 从 90 改成 10 —— 字号 72 的字直接沉出画面底缘。
    """
    by_layout = {
        "bottom_bar": 2,
        "center_single": 5,
        "center_multi": 5,
        "top_title": 8,
    }
    for layout, alignment in by_layout.items():
        preset = {
            "preset_id": "probe",
            "font": {"name": "X", "size": 72, "margin_v": 90},
            "dimensions": {"layout": {"default": layout}},
        }
        ass = build_ass([{"start": 0, "end": 2, "text": "台词"}], preset)
        assert f"\\an{alignment}" in ass, f"{layout} 应给出 \\an{alignment}"
        assert _style_field(ass, 18) == str(alignment), f"{layout} 的 Style Alignment 未跟随"


def test_bottom_bar_keeps_clear_of_frame_edge() -> None:
    """贴底布局的 MarginV 必须是预设留白；10 那档只在居中/置顶时才会出现。"""
    preset = presets.get_preset("conflict-impact")
    ass = build_ass([{"start": 0, "end": 2, "text": "普通台词"}], preset)
    assert _event_fields(ass)[7] == "90", "bottom_bar 用预设 margin_v=90，不是硬编码 10"
    assert "\\an2" in ass


def test_karaoke_pop_default_layout_is_not_bottom_bar() -> None:
    """karaoke-pop 的 layout.default 本就是 center_single：整片每行都该居中。

    修复前它是**每一行**被裁（贴底 + MarginV 10），业主截图即此形状。
    """
    preset = presets.get_preset("karaoke-pop")
    ass = build_ass(
        [
            {"start": 0, "end": 2, "text": "第一行"},
            {"start": 2, "end": 4, "text": "第二行"},
        ],
        preset,
    )
    assert ass.count("\\an5") == 2
    assert "\\an2" not in ass
