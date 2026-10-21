"""方案配音：只汇总真实推理过的段；全缓存时 compute 为空。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.narration import synthesis
from dramaclip.infra import compute


class _Engine:
    name = "kokoro"

    def __init__(self) -> None:
        self.report = compute.ComputeReport(
            component="tts.kokoro", requested="cpu", resolved="cpu", actual="cpu",
        )

    def capabilities(self):  # type: ignore[no-untyped-def]
        return type("Caps", (), {"supports_cloning": False})()

    def synthesize(self, _text: str, _voice: str, out: Path) -> Path:
        out.write_bytes(b"RIFF")
        return out

    def compute(self):  # type: ignore[no-untyped-def]
        return self.report


def test_pool_collects_only_real_inference(
    monkeypatch, tmp_path: Path
) -> None:
    engine = _Engine()
    pool = synthesis._EnginePool("kokoro", tmp_path, None, device="cpu")
    monkeypatch.setattr(pool, "_instances", {"kokoro": engine})
    path = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")
    assert path.exists()
    reports = pool.compute_reports()
    assert [r.component for r in reports] == ["tts.kokoro"]


def test_pool_cache_hit_has_no_report(monkeypatch, tmp_path: Path) -> None:
    engine = _Engine()
    pool = synthesis._EnginePool("kokoro", tmp_path, None, device="cpu")
    monkeypatch.setattr(pool, "_instances", {"kokoro": engine})
    cache = tmp_path / "cache"
    cache.mkdir()
    key = synthesis._cache_key("你好", "kokoro", "", "")
    (cache / f"{key}.mp3").write_bytes(b"RIFF")
    pool.synthesize_item("s1", "你好", "", "", tmp_path, cache)
    assert pool.compute_reports() == []
