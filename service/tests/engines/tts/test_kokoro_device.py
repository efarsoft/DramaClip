"""Kokoro 必须真的 .to(device)；显式 cuda 失败不回退，auto 回退要记账。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.engines.tts.engines import kokoro as kokoro_mod
from dramaclip.infra import compute


class _FakeModel:
    def __init__(self, config: str, model: str) -> None:
        self.device = "cpu"
        self.moved_to: str | None = None

    def to(self, device: object) -> _FakeModel:
        self.moved_to = str(device)
        self.device = self.moved_to
        return self

    def eval(self) -> _FakeModel:
        return self


def test_kokoro_moves_model_to_cpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(kokoro_mod, "_kokoro_importable", lambda: True)
    fake_kokoro = SimpleNamespace(KPipeline=lambda **_: object())
    fake_model_mod = SimpleNamespace(KModel=_FakeModel)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.setitem(sys.modules, "kokoro.model", fake_model_mod)
    engine = kokoro_mod.KokoroEngine(tmp_path, device="cpu")
    engine._ensure_pipeline()
    report = engine.compute()
    assert report is not None
    assert (report.requested, report.actual, report.fallback) == ("cpu", "cpu", False)


def test_kokoro_explicit_cuda_probe_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kokoro_mod, "_probe_torch_device", lambda _d: ("cpu", "cuda 不可用"))
    engine = kokoro_mod.KokoroEngine(tmp_path, device="cuda")
    with pytest.raises(compute.ComputeUnavailableError):
        engine._ensure_pipeline()
