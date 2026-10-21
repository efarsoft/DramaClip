"""试听：显式 cuda 实际 cpu 判红；缓存 key 含设备。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from dramaclip.infra import compute
from dramaclip.infra.model_manager import selftest


class _Engine:
    def __init__(self, report: compute.ComputeReport) -> None:
        self._report = report
        self.capabilities = lambda: type("Caps", (), {"supports_cloning": False})()

    def synthesize(self, _text: str, _voice: str, out: Path) -> Path:
        out.write_bytes(b"RIFF....WAVE")
        return out

    def compute(self) -> compute.ComputeReport:
        return self._report


def test_run_tts_explicit_cuda_actual_cpu_is_red(
    monkeypatch, tmp_path: Path
) -> None:
    report = compute.ComputeReport(
        component="tts.kokoro", requested="cuda", resolved="cuda", actual="cpu",
        reason="静默回退",
    )
    engine = _Engine(report)
    monkeypatch.setattr("dramaclip.engines.tts.factory.create", lambda *_a, **_k: engine)
    monkeypatch.setattr("dramaclip.engines.tts.base.audio_duration_s", lambda _p: 1.0)
    result = selftest.run_tts(
        tmp_path, tmp_path, type("Spec", (), {"engine": "edge"})(), "v", device="cuda"
    )
    assert result["ok"] is False
    assert result["compute"]["actual"] == "cpu"


def test_preview_key_changes_with_device() -> None:
    from dramaclip.api import tts as tts_api

    assert tts_api._content_key(
        "kokoro", "zf_001", "你好", "cpu", ""
    ) != tts_api._content_key("kokoro", "zf_001", "你好", "cuda", "")


def test_preview_cache_hit_replays_the_receipt_from_its_sidecar(
    monkeypatch, tmp_path: Path
) -> None:
    """缓存命中不重新推理，但必须能说清上次是谁在哪算的；sidecar 不参与命中判据。"""
    from dramaclip.api import tts as tts_api

    report = compute.ComputeReport(
        component="tts.kokoro", requested="cpu", resolved="cpu", actual="cpu"
    )
    engine = _Engine(report)
    calls: list[str] = []

    def _synthesize(text: str, _voice: str, out: Path) -> Path:
        calls.append(text)
        out.write_bytes(b"RIFF....WAVE")
        return out

    engine.synthesize = _synthesize  # type: ignore[method-assign]
    monkeypatch.setattr(tts_api, "create_tts", lambda *_a, **_k: engine)
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "wav")
    context = SimpleNamespace(
        data_dir=tmp_path,
        work_dir=tmp_path,
        settings={"tts.device": "cpu", "tts.model": "m", "tts.api_key": ""},
    )
    models_dir = tmp_path / "models"

    first, first_report = tts_api._preview_audio(context, "kokoro", "zf_001", "你好", models_dir)
    second, second_report = tts_api._preview_audio(context, "kokoro", "zf_001", "你好", models_dir)

    assert first == second
    assert len(calls) == 1, "同参数第二次必须命中缓存，不再推理"
    assert first_report == report
    assert second_report == replace(report, reason="缓存命中")
    sidecar = first.with_name(first.name + ".compute.json")
    assert sidecar.is_file()
    assert tts_api._find_cached(first.parent, tts_api._content_key(
        "kokoro", "zf_001", "你好", "cpu", "m"
    )) == first, "sidecar 不得被当成可播放的缓存音频"
