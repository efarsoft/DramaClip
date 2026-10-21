"""自检不得假绿：显式 cuda 落 CPU、actual=unknown 都判 ok=false。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra import compute
from dramaclip.infra.model_manager import selftest


class _Engine:
    name = "fake"

    def __init__(self, report: compute.ComputeReport) -> None:
        self._report = report

    def transcribe(self, _wav: Path, _lang: str) -> list[object]:
        seg = type("Seg", (), {"text": "你好"})()
        return [seg]

    def compute(self) -> compute.ComputeReport:
        return self._report


def test_explicit_cuda_actual_cpu_is_red(monkeypatch) -> None:
    report = compute.ComputeReport(
        component="asr.whisper", requested="cuda", resolved="cuda", actual="cpu",
        fallback=False, reason="静默回退",
    )
    monkeypatch.setattr(selftest, "_build_asr", lambda *_a, **_k: _Engine(report))
    result = selftest.run_asr(Path("models"), object(), device="cuda")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "cuda" in result["error"]
    assert result["compute"]["actual"] == "cpu"


def test_unknown_actual_is_red(monkeypatch) -> None:
    report = compute.ComputeReport(
        component="asr.whisper", requested="auto", resolved="cpu", actual="unknown",
    )
    monkeypatch.setattr(selftest, "_build_asr", lambda *_a, **_k: _Engine(report))
    result = selftest.run_asr(Path("models"), object())  # type: ignore[arg-type]
    assert result["ok"] is False
