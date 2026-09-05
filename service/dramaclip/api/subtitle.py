"""subtitle 命名空间：list_presets。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.subtitle import presets
from dramaclip.transport.rpc import Router


def register(router: Router, context: Any = None) -> None:  # noqa: ARG001 - 与其他命名空间签名一致
    router.register("subtitle.list_presets", lambda _params: list_presets())


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "preset_id": str(preset["preset_id"]),
            "preset_name": str(preset["preset_name"]),
            "description": str(preset["description"]),
        }
        for preset in presets.list_presets()
    ]
