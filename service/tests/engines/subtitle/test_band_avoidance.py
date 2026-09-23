"""A2 源硬字幕带避让：band→MarginV 换算纯函数 + build_ass 集成。

区分声明（业主立锁「硬字幕擦除不当核心」）：本模块是**避让**——把我们烧的字幕
抬到源片硬字幕带顶之上，不叠成两行；源片像素一个不动，不是擦除。擦除质量那条锁
约束的是另一条线，与这里不冲突。

几何单一真相：ass_generator 的 PlayResY=1920（\an2 下 MarginV=字幕底边距画面底
的像素数）；源带 top 是距画面**顶**的归一化值，故源带顶距画面底 = (1-top)×1920。
"""

from __future__ import annotations

import math
from typing import Any

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import (
    _PLAY_RES_Y,
    avoid_source_band_margin_v,
    build_ass,
)

_PRESET_MARGIN = 80


def _event_fields(ass: str, index: int = 0) -> list[str]:
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    return lines[index][len("Dialogue: ") :].split(",")


def _style_field(ass: str, index: int) -> str:
    line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    return line[len("Style: ") :].split(",")[index]


# ---- 纯函数换算 ----

def test_missing_band_keeps_preset_margin() -> None:
    """band 缺失（NULL/OCR 未装/未探测到）→ 原样返回预设值，降级不可见。"""
    assert avoid_source_band_margin_v(None, _PRESET_MARGIN) == _PRESET_MARGIN


def test_band_below_our_subtitle_does_not_lift() -> None:
    """源带整体在我们字幕之下（带顶距底 38px < margin 80px）→ 不重叠，不抬。"""
    assert avoid_source_band_margin_v((0.98, 1.0), _PRESET_MARGIN) == _PRESET_MARGIN


def test_overlap_lifts_bottom_edge_above_band_top() -> None:
    """真重叠才抬：抬后我们字幕底边必须在源带顶之上（含间隙）。"""
    band = (0.85, 0.95)  # 源带顶距底 = 0.15 × 1920 = 288px > 80 → 重叠
    margin = avoid_source_band_margin_v(band, _PRESET_MARGIN)
    assert margin > _PRESET_MARGIN
    assert margin >= math.ceil((1.0 - band[0]) * _PLAY_RES_Y), "底边必须落在源带顶之上，不重叠"


def test_edge_band_values() -> None:
    """边界 0.0/1.0 不炸、语义正确。"""
    # top=1.0：源带贴死画面底缘，距底 0px，永远不重叠 → 不抬
    assert avoid_source_band_margin_v((1.0, 1.0), _PRESET_MARGIN) == _PRESET_MARGIN
    # top=0.0：整幅画面都是源带（探测异常形状），抬到封顶值为止，不飞出画面
    margin = avoid_source_band_margin_v((0.0, 0.1), _PRESET_MARGIN)
    assert _PRESET_MARGIN < margin <= _PLAY_RES_Y


def test_lift_is_capped_below_frame_top() -> None:
    """源带很高（如源片字幕在画面中部）时封顶：避让不能把字幕抬出画面。"""
    margin = avoid_source_band_margin_v((0.1, 0.3), _PRESET_MARGIN)
    assert margin <= _PLAY_RES_Y * 2 // 3, "MarginV 超过画面 2/3 就等于字幕飞出演示区"


def test_small_overlap_still_lifts() -> None:
    """轻微压线（源带顶 96px vs margin 80px）也是重叠：抬，不糊弄。"""
    margin = avoid_source_band_margin_v((0.95, 0.99), _PRESET_MARGIN)
    assert margin > _PRESET_MARGIN
    assert margin >= 0.05 * _PLAY_RES_Y


# ---- build_ass 集成 ----

_LINES: list[dict[str, Any]] = [{"start": 0, "end": 2, "text": "普通台词"}]


def test_no_band_byte_identical_to_status_quo() -> None:
    """硬验收：不给 band（或给 None）→ ass 与现状逐字节一致。"""
    preset = presets.get_preset("conflict-impact")
    baseline = build_ass(_LINES, preset)
    assert build_ass(_LINES, preset, source_band=None) == baseline


def test_non_overlapping_band_byte_identical() -> None:
    """源带在我们字幕之下 → 不抬 → 逐字节一致（不做无谓避让）。"""
    preset = presets.get_preset("conflict-impact")
    baseline = build_ass(_LINES, preset)
    assert build_ass(_LINES, preset, source_band=(0.98, 1.0)) == baseline


def test_overlapping_band_lifts_style_and_event_margin() -> None:
    preset = presets.get_preset("conflict-impact")  # bottom_bar，margin_v=90
    ass = build_ass(_LINES, preset, source_band=(0.85, 0.95))
    assert ass != build_ass(_LINES, preset)
    lifted = int(_event_fields(ass)[7])
    assert lifted >= (1.0 - 0.85) * _PLAY_RES_Y, "事件 MarginV 未清过源带顶"
    assert _style_field(ass, 21) == str(lifted), "Style MarginV 必须同步（两处真相守卫）"
    assert "\\an2" in ass, "布局不变，只抬边距"


def test_climax_center_layout_unaffected_by_band() -> None:
    """center_single（climax 档）：MarginV 不参与定位，band 给不给事件行零变化。

    Style 头行按预设 default 布局（bottom_bar）走，MarginV 跟着抬——那服务的是同片
    里的 \an2 事件；\an5 事件行自带 MarginV=0 覆盖 Style，纵向定位不受影响。
    """
    preset = presets.get_preset("conflict-impact")
    lines = [{"start": 0, "end": 2, "text": "我要报仇！"}]  # triumph → center_single
    baseline = build_ass(lines, preset)
    assert "\\an5" in baseline
    with_band = build_ass(lines, preset, source_band=(0.5, 0.9))
    assert _event_fields(with_band)[7] == "0", "居中事件 MarginV 必须仍为 0"
    assert _event_line_of(with_band) == _event_line_of(baseline), "事件行零改动"
    assert "\\an5" in with_band


def _event_line_of(ass: str) -> str:
    return next(line for line in ass.splitlines() if line.startswith("Dialogue:"))


def test_karaoke_center_preset_unaffected_by_band() -> None:
    preset = presets.get_preset("karaoke-pop")  # layout.default = center_single
    assert build_ass(_LINES, preset, source_band=(0.5, 0.9)) == build_ass(_LINES, preset)


def test_top_title_unaffected_by_band() -> None:
    """top_title（\an8）：MarginV 是距**顶**距离，底部源带避让不适用，零改动。"""
    preset = {
        "preset_id": "probe",
        "font": {"name": "X", "size": 64, "margin_v": 80},
        "dimensions": {"layout": {"default": "top_title"}},
    }
    assert build_ass(_LINES, preset, source_band=(0.5, 0.9)) == build_ass(_LINES, preset)
