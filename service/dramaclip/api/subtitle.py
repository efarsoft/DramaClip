"""subtitle 命名空间：list_presets / safe_zone。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.subtitle import presets, safe_zone
from dramaclip.transport.rpc import Router


def register(router: Router, context: Any = None) -> None:  # noqa: ARG001 - 与其他命名空间签名一致
    router.register("subtitle.list_presets", lambda _params: list_presets())
    router.register("subtitle.safe_zone", lambda _params: safe_zone_payload())


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "preset_id": str(preset["preset_id"]),
            "preset_name": str(preset["preset_name"]),
            "description": str(preset["description"]),
        }
        for preset in presets.list_presets()
    ]


def safe_zone_payload() -> dict[str, Any]:
    """遮罩几何唯一出口：前端叠层经此读取，不各写一份常量。"""
    return {
        "reference": list(safe_zone.REFERENCE_SIZE),
        **safe_zone.mask_ratios(),
        "note": "推断值，待真机校验；按 9:16 竖屏标定",
    }
