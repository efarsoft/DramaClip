"""system.health：设备档位结论的唯一装配点——三处安装态必须按本 data_dir 读齐。"""

from __future__ import annotations

from typing import Any

import pytest

_NONE = {
    "ready": True,
    "vendor": "none",
    "name": "",
    "driver_version": "",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [],
}


def test_health_passes_the_tts_venv_torch_variant(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.api import system as system_api
    from dramaclip.infra import device_profile as dp
    from dramaclip.infra import gpu as gpu_mod
    from dramaclip.infra.model_manager import cuda_runtime, tts_runtime

    seen: dict[str, Any] = {}

    def fake_profile(snapshot: dict[str, Any], installed: bool, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        seen["installed"] = installed
        return {"tier": "none", "caps": {}}

    monkeypatch.setattr(gpu_mod, "snapshot", lambda force=False: dict(_NONE))
    monkeypatch.setattr(dp, "profile", fake_profile)
    monkeypatch.setattr(cuda_runtime, "status", lambda _d: {"installed": False})
    monkeypatch.setattr(tts_runtime, "ort_state", lambda _d: {"variant": "unknown"})
    monkeypatch.setattr(tts_runtime, "torch_variant", lambda _d: "unknown")

    result = system_api.health({}, tmp_path)

    assert seen["torch_variant"] == "unknown", "profile 必须收到按本 data_dir 读的 torch 变体"
    assert seen["separation_ort"] == {"variant": "unknown"}
    assert result["gpu_info"]["vendor"] == "none"
