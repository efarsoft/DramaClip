"""平台 UI 安全区：预览遮罩几何 + 自检劝告（不改变字幕落位）。

像素值为推断（报告 2026-11-09：右 150/底 250–350/顶 150，底取中值 300），
待真机校验一轮后固化。字幕落位跟随源台词带（业主裁决「区域一致即可」）：
本模块只报「可能被平台 UI 遮挡」，永不移动字幕——移动会撞出片前覆盖闸
（ass_generator.placement_violations）。风险只灰不红：遮罩是推断值，
红判据会与覆盖裁决自相矛盾。
"""

from __future__ import annotations

from typing import Any

#: 推断值的标定画布（9:16 竖屏）；其他画幅按比例折算，误差真机校验时一并收。
REFERENCE_SIZE = (1080, 1920)
TOP_PX = 150
RIGHT_PX = 150
BOTTOM_PX = 300


def mask_ratios() -> dict[str, float]:
    """遮罩占画布的比例（顶/右/底三条 UI 常驻区）。"""
    width, height = REFERENCE_SIZE
    return {"top": TOP_PX / height, "right": RIGHT_PX / width, "bottom": BOTTOM_PX / height}


def check_safe_zone(band: tuple[float, float] | None) -> dict[str, Any]:
    """自检劝告项：字幕带底是否进入平台底部互动区（band 为归一化覆盖承诺）。"""
    if band is None:
        return {"pass": None, "reason": "无字幕覆盖承诺"}
    limit = 1.0 - mask_ratios()["bottom"]
    if float(band[1]) > limit:
        return {
            "pass": None,
            "reason": (
                f"字幕带底 {float(band[1]):.2f} 进入平台底部互动区"
                f"（推断遮罩 >{limit:.2f}，待真机校验）：预览可叠安全区确认，不影响覆盖承诺"
            ),
        }
    return {"pass": True, "reason": "字幕带在平台底部互动区外（推断遮罩，待真机校验）"}
