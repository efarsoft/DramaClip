"""engines.subtitle.safe_zone：平台 UI 安全区（推断值，待真机校验）。

钉住「几何常量」「风险只灰不红」「无承诺灰」——安全区永不移动字幕、
永不判红（覆盖裁决优先：字幕落位跟随源台词带）。
"""

from __future__ import annotations

from dramaclip.engines.subtitle import safe_zone


def test_mask_ratios_reference() -> None:
    ratios = safe_zone.mask_ratios()
    assert ratios == {"top": 150 / 1920, "right": 150 / 1080, "bottom": 300 / 1920}


def test_no_band_is_gray() -> None:
    assert safe_zone.check_safe_zone(None) == {"pass": None, "reason": "无字幕覆盖承诺"}


def test_risk_is_gray_not_red() -> None:
    item = safe_zone.check_safe_zone((0.80, 0.92))
    assert item["pass"] is None, "劝告项永不判红（遮罩是推断值，落位跟随源带）"
    assert "底部互动区" in item["reason"]


def test_clear_is_green() -> None:
    assert safe_zone.check_safe_zone((0.60, 0.80))["pass"] is True
