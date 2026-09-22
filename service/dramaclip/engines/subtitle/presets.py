"""字幕风格预设：内置（resources，只读随版本走）+ 用户自定义（DB，P2）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from dramaclip.infra.paths import resolve_resources_dir

FALLBACK_PRESET_ID = "conflict-impact"


@lru_cache(maxsize=1)
def _load_builtin() -> dict[str, dict[str, Any]]:
    presets: dict[str, dict[str, Any]] = {}
    presets_dir = resolve_resources_dir() / "subtitle-presets"
    if not presets_dir.is_dir():
        return presets
    for file in sorted(presets_dir.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("preset_id"):
            presets[str(data["preset_id"])] = data
    return presets


def list_presets() -> list[dict[str, Any]]:
    """全部内置预设（元信息 + 完整定义）。"""
    return list(_load_builtin().values())


def get_preset(preset_id: str | None) -> dict[str, Any]:
    """按 id 取预设；缺失回退默认冲突冲击，再缺失返回最小兜底。"""
    builtin = _load_builtin()
    if preset_id in builtin:
        return builtin[preset_id]
    return builtin.get(
        FALLBACK_PRESET_ID,
        {
            "preset_id": FALLBACK_PRESET_ID,
            "dimensions": {},
            # 没有 "name"：字幕字面是随包资产（engines.subtitle.caption_font），不由预设指定
            "font": {"size": 64, "bold": True, "outline_width": 3, "shadow": 1, "margin_v": 80},
        },
    )
