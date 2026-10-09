"""源字幕带压位：band→MarginV 换算纯函数 + build_ass 集成。

语义（2026-10-06 业主裁决「直接覆盖原始字幕」，推翻 90004e4 的只避让）：
编码端先对该带 delogo 擦除，我们的字幕**放回带内居中**——观众看竖屏短剧
的字幕位置习惯。band 缺失降级为预设边距，逐字节一致。
2026-10-08 扩展：居中档（climax/卡拉OK）在有源带时同样落带内压位——
悬空的居中大字挡脸，观感即「字幕位置不对」（业主截图反馈）。

几何单一真相：ass_generator 的 PlayResY=1920（\\an2 下 MarginV=字幕**盒底**距画面
底的像素数）；墨迹中心在盒底上方 0.455×字号处（随包字面真机标定）。
"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import (
    _PLAY_RES_Y,
    build_ass,
    cover_band_margin_v,
)

_PRESET_MARGIN = 80
_REAL_BAND = (0.7174, 0.8291)  # 真机《钟情错付》实测带：顶 71.7%、底 82.9%
# 真机标定：\an2 锚的是盒底，墨迹中心在它上方 0.455 个字号处。
# 旧实现按 font_px×1.9 的「盒子」在带内居中，墨迹因此系统性偏低 ~30px——
# 业主「字幕要精准覆盖原有字幕」差的就是这一段（2026-10-09 逐集量出）。
_INK_CENTER_ABOVE_ANCHOR = 0.455


def _event_fields(ass: str, index: int = 0) -> list[str]:
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    return lines[index][len("Dialogue: ") :].split(",")


def _style_field(ass: str, index: int) -> str:
    line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    return line[len("Style: ") :].split(",")[index]


# ---- 纯函数换算 ----

def test_missing_band_keeps_preset_margin() -> None:
    """band 缺失（NULL/OCR 未装/未探测到）→ 原样返回预设值，降级不可见。"""
    assert cover_band_margin_v(None, _PRESET_MARGIN) == _PRESET_MARGIN


def test_margin_puts_ink_center_on_target_center() -> None:
    """覆盖优先的对齐目标：**墨迹中心**落在目标矩形中心（±1px 取整）。

    真机三档形状各验一次（下部带 / 中部带 / 贴近底缘），旧公式按幻影盒
    （font×1.9）居中，墨迹系统性偏低 ~30px，这条用例正是当时的空档。
    """
    font_px = 64
    for rect in ((0.7174, 0.8291), (0.613, 0.740), (0.85, 0.95)):
        margin = cover_band_margin_v(rect, _PRESET_MARGIN, None, font_px)
        ink_center = margin + _INK_CENTER_ABOVE_ANCHOR * font_px  # 距画面底
        target = (1 - (rect[0] + rect[1]) / 2) * _PLAY_RES_Y
        assert abs(ink_center - target) <= 1, f"{rect}：墨迹中心差 {ink_center - target:+.1f}px"


def test_thin_band_puts_box_bottom_on_band_bottom() -> None:
    """带比盒子矮（带高 38px < 盒高 121px）：负偏移取 0，盒子贴带底向上长。"""
    assert cover_band_margin_v((0.98, 1.0), _PRESET_MARGIN, None, 64) == _PRESET_MARGIN


def test_high_band_is_capped() -> None:
    """带探到画面上部（异常形状）→ 封顶 2/3 画布，不把字幕抬出演示区。"""
    margin = cover_band_margin_v((0.1, 0.3), _PRESET_MARGIN, None, 64)
    assert margin == _PLAY_RES_Y * 2 // 3


# ---- build_ass 集成 ----

_LINES: list[dict[str, Any]] = [{"start": 0, "end": 2, "text": "普通台词"}]


def test_no_band_byte_identical_to_status_quo() -> None:
    """硬验收：不给 band（或给 None）→ ass 与现状逐字节一致。"""
    preset = presets.get_preset("conflict-impact")
    baseline = build_ass(_LINES, preset)
    assert build_ass(_LINES, preset, source_band=None) == baseline


def test_band_cover_moves_style_and_event_margin_together() -> None:
    preset = presets.get_preset("conflict-impact")  # bottom_bar，margin_v=90
    font_px = int(preset.get("font", {}).get("size", 64))
    ass = build_ass(_LINES, preset, source_band=_REAL_BAND)
    covered = int(_event_fields(ass)[7])
    assert covered == cover_band_margin_v(_REAL_BAND, 90, None, font_px)
    assert _style_field(ass, 21) == str(covered), "Style MarginV 必须同步（两处真相守卫）"
    assert "\\an2" in ass, "布局不变，只改边距"


def test_climax_layout_bottoms_with_and_without_band() -> None:
    """climax 大字档：位置统一落底部字幕带（2026-10-08 裁决：字幕禁止居中）——
    有源带压带内（带已被擦除），无源带贴预设边距；字号与情绪色保留。"""
    preset = presets.get_preset("conflict-impact")
    lines = [{"start": 0, "end": 2, "text": "我要报仇！"}]  # triumph → center_single
    font_px = int(preset.get("font", {}).get("size", 64))

    baseline = build_ass(lines, preset)
    assert "\\an2" in baseline, "无源带 → 贴预设边距，不居中"
    assert _event_fields(baseline)[7] == "90", "无带时用预设边距"

    with_band = build_ass(lines, preset, source_band=(0.5, 0.9))
    assert "\\an2" in with_band
    expected = cover_band_margin_v((0.5, 0.9), 90, None, font_px)
    assert _event_fields(with_band)[7] == str(expected), "MarginV 按带内压位公式"
    assert "\\fscx112" in with_band, "climax 大字冲击力保留"


def _event_line_of(ass: str) -> str:
    return next(line for line in ass.splitlines() if line.startswith("Dialogue:"))


def test_karaoke_center_preset_bottoms() -> None:
    """卡拉OK档统一落底部字幕带（居中已废，2026-10-08 裁决）。"""
    preset = presets.get_preset("karaoke-pop")  # layout.default = center_single
    ass = build_ass(_LINES, preset, source_band=(0.5, 0.9))
    assert "\\an2" in ass
    assert "\\an5" not in ass


def test_top_title_unaffected_by_band() -> None:
    """top_title：MarginV 是距**顶**距离，底部源带压位不适用，零改动。"""
    preset = {
        "preset_id": "probe",
        "font": {"name": "X", "size": 64, "margin_v": 80},
        "dimensions": {"layout": {"default": "top_title"}},
    }
    assert build_ass(_LINES, preset, source_band=(0.5, 0.9)) == build_ass(_LINES, preset)


def test_garbage_band_falls_back_to_preset_margin() -> None:
    """满幅文字背景误检的「带」（高 >35% 画布）不采信：回退预设底部边距，
    字幕不悬空画面中部（2026-10-09 真机 16:9 片头字幕墙反馈）。"""
    garbage_band = (0.135, 0.816)  # 高 68%：真机误检形状
    ass = build_ass(_LINES, presets.get_preset("conflict-impact"), source_band=garbage_band)
    assert _event_fields(ass)[7] == "90", "conflict-impact 预设边距 90，不跟随垃圾带"
