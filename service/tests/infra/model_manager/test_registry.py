"""registry v2：档位/评级元数据 + 状态探测。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.model_manager import registry
from dramaclip.infra.model_manager.registry import builtin_specs


def test_catalog_has_tier_metadata() -> None:
    specs = {spec.model_id: spec for spec in builtin_specs()}
    assert specs["faster-whisper-base"].tier == "fast"
    assert specs["faster-whisper-small"].tier == "balanced"
    assert specs["faster-whisper-large-v3"].tier == "accurate"
    assert all(1 <= spec.speed <= 5 for spec in specs.values())
    assert all(1 <= spec.quality <= 5 for spec in specs.values())


def test_detect_status_not_installed(tmp_path: Path) -> None:
    spec = builtin_specs()[0]
    status = registry.detect_status(tmp_path / "models", spec)
    assert status["status"] == "not_installed"
    assert status["size_label"] != ""
    assert status["tier"] != ""


def test_detect_status_installed_via_weights(tmp_path: Path) -> None:
    spec = next(s for s in builtin_specs() if s.model_id == "kokoro-82m")
    base = tmp_path / "models" / spec.placement
    base.mkdir(parents=True)
    (base / "model.pth").write_bytes(b"x")
    status = registry.detect_status(tmp_path / "models", spec)
    assert status["status"] == "installed"


def test_find_returns_none_when_missing(tmp_path: Path) -> None:
    spec = builtin_specs()[0]
    assert registry.find(spec, tmp_path / "models") is None
