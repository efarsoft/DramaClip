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

import pytest

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import (
    _PLAY_RES_Y,
    build_ass,
    cover_band_margin_v,
    coverage_promised,
    placement_violations,
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


# ---- 出片前覆盖性静态闸（业主裁决④：字幕要盖在源台词带上，不许漂）--------------

_PRESET = presets.get_preset("conflict-impact")  # bottom_bar / margin_v 90
_BAND = (0.7174, 0.8291)  # 真机《钟情错付》实测带


def _with_event_margin(ass: str, margin_v: int) -> str:
    """把 Dialogue 的 MarginV 字段改成给定值（模拟「生成的 ASS 漂了」）。"""
    rows: list[str] = []
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            fields = line.split(",")
            fields[7] = str(margin_v)
            line = ",".join(fields)
        rows.append(line)
    return "\n".join(rows)


def test_gate_passes_when_caption_sits_on_band() -> None:
    """正常覆盖形状零违规——闸不能对今天的出片路径开火（误报即挡片）。"""
    ass = build_ass(_LINES, _PRESET, source_band=_BAND)
    assert placement_violations(ass, _BAND, 90) == []


# 真机《大明：灭国前，我觉醒了》：源画幅 1920×1080，ep8 采信行框并集。
_LANDSCAPE = (1920, 1080)
_LANDSCAPE_BAND = (0.811, 0.903)
_LANDSCAPE_PRESET_MARGIN = 51  # round(90 × 1080/1920) —— _margin_v 的纵向缩放


def test_gate_passes_landscape_caption_taller_than_band() -> None:
    """横屏画布上「我们的字比源字幕高」是几何必然，闸不能因为它挡片（真机 10 集拦 8 集）。

    墨迹高 = 字号 ÷ 画布高，而字号随**宽**缩放：同一预设竖屏 72/1920≈0.037，横屏
    128/1080≈0.119，换个画幅大 3 倍。源台词带高却是 OCR 实测值（这批素材
    0.088–0.109）。要求墨迹「装得下」这块带，等于要求 MarginV 去解一个跟 MarginV
    无关的不等式——它取任何值都不成立，闸于是对分毫不差的居中落位开火
    （真机报错：墨迹 0.798–0.916 vs 带 0.811–0.903，两者中心都是 0.857）。
    """
    ass = build_ass(_LINES, _PRESET, source_band=_LANDSCAPE_BAND, play_res=_LANDSCAPE)
    assert placement_violations(ass, _LANDSCAPE_BAND, _LANDSCAPE_PRESET_MARGIN) == []


def test_gate_still_flags_drift_on_landscape_canvas() -> None:
    """横屏放开的只有「尺寸差」这一种形状，漏接线那种照样拦（预设线 vs 带心差 0.041）。"""
    drifted = _with_event_margin(
        build_ass(_LINES, _PRESET, play_res=_LANDSCAPE), _LANDSCAPE_PRESET_MARGIN
    )
    violations = placement_violations(drifted, _LANDSCAPE_BAND, _LANDSCAPE_PRESET_MARGIN)
    assert len(violations) == 1, violations


def test_gate_does_not_judge_below_the_preset_clamp() -> None:
    """带心已在预设墨迹中心以下 → `cover_band_margin_v` 的下限钳生效，闸不追钳住兑现不了的位移。

    判据必须是钳子的镜像：`max(preset_margin_v, ...)` 在「目标比预设线还低」时把字幕
    留在预设位，此时任何要求它下移的判定都是追一个本就没做的承诺。用带**顶**判是旧
    包含式的近似，中间有一条漏区（带顶在预设墨迹之上、带心却在其下）。
    """
    band = (0.90, 1.00)  # 带顶 0.90 < 预设墨迹顶 0.917，但带心 0.95 > 预设墨迹中心 0.936
    ass = build_ass(_LINES, _PRESET, source_band=band)
    assert placement_violations(ass, band, 90) == []


def test_gate_flags_caption_below_band() -> None:
    """接线漏传 source_band 的形状：字幕仍贴预设底线，源带在 0.72–0.83。
    「盖不住」就是业主看到的「字幕到处乱跑」，必须在编码前拦住。"""
    drifted = _with_event_margin(build_ass(_LINES, _PRESET), 90)
    violations = placement_violations(drifted, _BAND, 90)
    assert len(violations) == 1, violations
    assert "0.717" in violations[0] and "0.829" in violations[0]


def test_gate_flags_caption_above_band() -> None:
    """MarginV 语义被改坏的形状：整行抬到画面中部，糊住人物（业主立案的原话形状）。"""
    drifted = _with_event_margin(build_ass(_LINES, _PRESET, source_band=_BAND), 900)
    assert len(placement_violations(drifted, _BAND, 90)) == 1


def test_gate_judges_every_row() -> None:
    """逐行判：一段里两行字幕，漂一行报一行（拆行的两行各自定时定距）。"""
    lines = [
        {"start": 0, "end": 2, "text": "第一行"},
        {"start": 2, "end": 4, "text": "第二行"},
    ]
    ass = _with_event_margin(build_ass(lines, _PRESET, source_band=_BAND), 90)
    assert len(placement_violations(ass, _BAND, 90)) == 2


def test_gate_stays_quiet_without_a_promise() -> None:
    """生成端本就没承诺覆盖的四种形状，闸不追一个没做的承诺（误报即挡片）。"""
    preset_margin = 90
    ass = build_ass(_LINES, _PRESET, source_band=_BAND)
    no_basis = _with_event_margin(build_ass(_LINES, _PRESET), 90)
    cases = [
        (ass, None, "无带 → 无基准"),
        (ass, (0.135, 0.816), "带高 68% → 满幅误检，生成端回退预设"),
        (ass, (0.1, 0.3), "带心在上半 → 2/3 封顶区，不是底部承诺区"),
        (no_basis, (0.93, 0.99), "带整体在预设墨迹以下 → 刻意不往下挪"),
    ]
    for text, band, why in cases:
        assert placement_violations(text, band, preset_margin) == [], why


def test_gate_only_judges_bottom_aligned_rows() -> None:
    """\an8（top_title）的 MarginV 是距顶距离，与底部源带不相干：不参与判定。"""
    preset = {
        "preset_id": "probe",
        "font": {"name": "X", "size": 64, "margin_v": 80},
        "dimensions": {"layout": {"default": "top_title"}},
    }
    ass = build_ass(_LINES, preset, source_band=(0.5, 0.9))
    assert "\\an8" in ass
    assert placement_violations(ass, (0.5, 0.9), 80) == []


def test_build_ass_gates_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """闸真的接在生成端：判出不一致就不返回 ASS（漏接线/字段漂/语义改坏都到不了编码）。"""
    monkeypatch.setattr(
        "dramaclip.engines.subtitle.ass_generator.placement_violations",
        lambda *a, **k: ["模拟：墨迹 0.92–0.95 不在带 0.717–0.829 内"],
    )
    with pytest.raises(ValueError, match="模拟：墨迹"):
        build_ass(_LINES, _PRESET, source_band=_BAND)


def test_coverage_promised_is_the_single_definition_of_the_promise() -> None:
    """「承诺覆盖」的唯一判据：闸与成片画面侧度量共用，两边不各写一份。

    两种放弃的形状都是生成端在 `cover_band_margin_v` 里回退预设边距的那两处。
    """
    assert coverage_promised(None) is False, "无带 = 无基准"
    assert coverage_promised((0.135, 0.816)) is False, "带高 68% = 满幅文字背景误检"
    assert coverage_promised((0.1, 0.3)) is False, "带心在上半 = 2/3 封顶辖区，不是覆盖承诺"
    assert coverage_promised((0.7174, 0.8291)) is True, "真机底部台词带"
    assert coverage_promised((0.45, 0.55)) is True, "带心 0.5 = 分界线上，仍算下半"
    # 两条阈值的**数值**也钉住：调常数必须显式改这里，不许静默放宽承诺面
    assert coverage_promised((0.5, 0.85)) is True, "带高正好 0.35 = 含等号，仍算台词带"
    assert coverage_promised((0.49, 0.85)) is False, "带高 0.36 = 越线，误检"
    assert coverage_promised((0.44, 0.55)) is False, "带心 0.495 = 上半，不承诺"
