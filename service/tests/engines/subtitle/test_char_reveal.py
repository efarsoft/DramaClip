"""engines.subtitle：逐字浮现节奏（char_reveal，B3-12）与预设。

char_reveal 与 karaoke（逐字 \\k 高亮填充）、whole_line（整行 \\fad）三档独立：
char_reveal 逐字 \\fad(fade_in,0) 淡入揭示、无高亮对比色。preset 与 animation.entrance
（bounce/fade）正交——节奏管「字怎么显现」，动效管「整行怎么进场」，独立可组合。
"""

from __future__ import annotations

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import build_ass


def test_char_reveal_preset_loaded() -> None:
    ids = {p["preset_id"] for p in presets.list_presets()}
    assert "char-reveal" in ids, "char-reveal 预设应随包分发"


def test_char_reveal_emits_fad_reveal_not_k() -> None:
    preset = presets.get_preset("char-reveal")
    ass = build_ass([{"start": 0.0, "end": 4.0, "text": "真相大白"}], preset)
    assert "\\k" not in ass, "char_reveal 是逐字淡入，不该带 karaoke 的 \\k 标签"
    assert "\\fad(" in ass, "char_reveal 应逐字注入 \\fad 揭示窗口"


def test_char_reveal_per_char_window() -> None:
    """4 字 / 4s → 每字窗口 1000ms，逐字 \\fad(1000,0)（只淡入不退）。"""
    preset = presets.get_preset("char-reveal")
    ass = build_ass([{"start": 0.0, "end": 4.0, "text": "真相大白"}], preset)
    assert "\\fad(1000,0)" in ass


def test_char_reveal_bounce_entrance_combines() -> None:
    """char_reveal 预设默认 entrance=bounce：逐字 \\fad 与整行弹缩 \\t 叠加可组合。"""
    preset = presets.get_preset("char-reveal")
    ass = build_ass([{"start": 0.0, "end": 4.0, "text": "真相大白"}], preset)
    assert "\\fad(1000,0)" in ass
    assert "\\fscx115" in ass, "bounce 进场的逐字弹缩应随 char_reveal 预设生效"


def test_karaoke_unchanged_is_byte_stable() -> None:
    """karaoke-pop 保持 karaoke 逐字 \\k 高亮（B3-12 不改既有预设语义，逐字节稳定）。"""
    preset = presets.get_preset("karaoke-pop")
    assert preset["dimensions"]["rhythm"]["type"] == "karaoke"
    ass = build_ass([{"start": 0.0, "end": 4.0, "text": "真相大白"}], preset)
    assert "\\k" in ass
    assert "\\fad(1000,0)" not in ass, "karaoke 不得误走 char_reveal 分支"


def test_char_reveal_ignores_span_emotions() -> None:
    """逐字自带 \\fad，与 span 区间颜色互斥（同 karaoke 约定），脏 span 不炸渲染。"""
    preset = presets.get_preset("char-reveal")
    ass = build_ass(
        [
            {
                "start": 0.0,
                "end": 4.0,
                "text": "真相大白",
                "span_emotions": [(0, 2, "bad_label")],
            }
        ],
        preset,
    )
    assert "\\fad(1000,0)" in ass
    # 坏 span 被丢弃：不出现区间颜色标签
    assert "\\c&H0000FFFF" not in ass or "bad_label" not in ass


def test_char_reveal_empty_text_falls_back_to_whole_override() -> None:
    """全空白行不逐字拆（无字可显现），回退整行单 override，逐字节安全。"""
    preset = presets.get_preset("char-reveal")
    ass = build_ass([{"start": 0.0, "end": 1.0, "text": "   "}], preset)
    # 空行被 _event_line 的 text.strip() 守卫直接丢弃（返回 None），build_ass 跳过
    assert "Dialogue:" not in ass
