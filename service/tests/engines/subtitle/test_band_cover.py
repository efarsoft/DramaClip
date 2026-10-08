"""源字幕带压位：band→MarginV 换算纯函数 + build_ass 集成。

语义（2026-10-06 业主裁决「直接覆盖原始字幕」，推翻 90004e4 的只避让）：
编码端先对该带 delogo 擦除，我们的字幕**放回带内居中**——观众看竖屏短剧
的字幕位置习惯。band 缺失降级为预设边距，逐字节一致。
2026-10-08 扩展：居中档（climax/卡拉OK）在有源带时同样落带内压位——
悬空的居中大字挡脸，观感即「字幕位置不对」（业主截图反馈）。

几何单一真相：ass_generator 的 PlayResY=1920（\\an2 下 MarginV=字幕底边距
画面底的像素数）；盒子估高 = font_px × 1.9（字身 + 底框 padding）。
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


def test_band_centers_the_caption_box() -> None:
    """真机形状：盒底 = 带底，再上提 (带高-盒高)/2 让盒子在带内居中。"""
    font_px = 64
    margin = cover_band_margin_v(_REAL_BAND, _PRESET_MARGIN, None, font_px)
    band_bottom_px = (1 - 0.8291) * _PLAY_RES_Y
    band_h = (0.8291 - 0.7174) * _PLAY_RES_Y
    expected = round(band_bottom_px + (band_h - font_px * 1.9) / 2)
    assert margin == max(_PRESET_MARGIN, expected)


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


def test_climax_center_layout_falls_into_band() -> None:
    """climax 居中档：无源带保持垂直居中冲击设计；有源带落带内压位。

    悬空的居中大字挡脸，观感即「字幕位置不对」（2026-10-08 业主截图反馈）——
    带已被擦除，字幕回带内，字号冲击力保留。
    """
    preset = presets.get_preset("conflict-impact")
    lines = [{"start": 0, "end": 2, "text": "我要报仇！"}]  # triumph → center_single
    baseline = build_ass(lines, preset)
    assert "\\an5" in baseline, "无带时保持居中冲击设计"
    assert _event_fields(baseline)[7] == "0"

    font_px = int(preset.get("font", {}).get("size", 64))
    with_band = build_ass(lines, preset, source_band=(0.5, 0.9))
    assert "\\an2" in with_band, "有源带 → 落带内，不再悬空居中"
    expected = cover_band_margin_v((0.5, 0.9), 90, None, font_px)
    assert _event_fields(with_band)[7] == str(expected), "MarginV 按带内压位公式"


def _event_line_of(ass: str) -> str:
    return next(line for line in ass.splitlines() if line.startswith("Dialogue:"))


def test_karaoke_center_preset_falls_into_band() -> None:
    """center_single（卡拉OK档）同样统一：无带居中，有源带落带内压位。"""
    preset = presets.get_preset("karaoke-pop")  # layout.default = center_single
    baseline = build_ass(_LINES, preset)
    with_band = build_ass(_LINES, preset, source_band=(0.5, 0.9))
    assert with_band != baseline, "有源带时落带，输出必然变化"
    font_px = int(preset.get("font", {}).get("size", 64))
    margin_v = int(preset.get("font", {}).get("margin_v", 80))
    assert _event_fields(with_band)[7] == str(
        cover_band_margin_v((0.5, 0.9), margin_v, None, font_px)
    ), "MarginV 按带内压位公式"


def test_top_title_unaffected_by_band() -> None:
    """top_title：MarginV 是距**顶**距离，底部源带压位不适用，零改动。"""
    preset = {
        "preset_id": "probe",
        "font": {"name": "X", "size": 64, "margin_v": 80},
        "dimensions": {"layout": {"default": "top_title"}},
    }
    assert build_ass(_LINES, preset, source_band=(0.5, 0.9)) == build_ass(_LINES, preset)
