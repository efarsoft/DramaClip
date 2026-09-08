"""解说风格库：内置只读风格（resources，随版本走）。

风格注入编剧 system prompt，影响钩子句式、叙事节奏与文案口味；
规则降级编排不受风格影响（模板文案无风格自由度）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from dramaclip.infra.paths import resolve_resources_dir

FALLBACK_STYLE_ID = "general"


@lru_cache(maxsize=1)
def _load_builtin() -> dict[str, dict[str, Any]]:
    styles: dict[str, dict[str, Any]] = {}
    styles_dir = resolve_resources_dir() / "narration-styles"
    if not styles_dir.is_dir():
        return styles
    for file in sorted(styles_dir.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("style_id"):
            styles[str(data["style_id"])] = data
    return styles


def list_styles() -> list[dict[str, Any]]:
    """全部内置风格（元信息 + 完整定义）。"""
    return list(_load_builtin().values())


def get_style(style_id: str | None) -> dict[str, Any]:
    """按 id 取风格；缺失回退通用风格，再缺失返回空指令兜底。"""
    styles = _load_builtin()
    if style_id is not None and style_id in styles:
        return styles[style_id]
    return styles.get(
        FALLBACK_STYLE_ID,
        {"style_id": FALLBACK_STYLE_ID, "name": "通用", "directives": ""},
    )
