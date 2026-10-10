"""B6 preview 接线：indextts2 克隆场景响应附 reference_quality 质检报告。

附加字段是开放集（protocol schema 的 result 无 additionalProperties:false，
contract_sync 只钉 required 集合与方法名单），不动 protocol/* 也合法。
质检永不阻断试听：poor 也照常合成并返回 path，报告照附。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from dramaclip.api import tts as tts_api
from dramaclip.engines.tts import factory, reference_qc
from dramaclip.infra import config

_SR = 22050


class FakeEngine:
    def __init__(self) -> None:
        self.name = "fake"
        self.calls: list[tuple[str, str, Path]] = []

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.calls.append((text, voice, out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"audio-bytes")
        return out_path


@pytest.fixture(autouse=True)
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    stub = FakeEngine()
    monkeypatch.setattr(
        tts_api, "create_tts", lambda name, models_dir=None, api_key="": stub  # noqa: ARG005
    )
    monkeypatch.setattr(tts_api, "audio_duration_s", lambda _path: 2.5)
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "mp3")
    monkeypatch.setattr(reference_qc, "_CACHE", {})
    return stub


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings=dict(config.DEFAULTS),
    )


def _indextts2_ready(tmp_path: Path) -> None:
    """indextts2 的 _assert_model_present 要模型目录存在（试听前置门槛，与质检无关）。"""
    factory.model_dir(tmp_path / "models", "indextts2").mkdir(parents=True, exist_ok=True)


def _ref(tmp_path: Path, name: str, samples: np.typing.NDArray[np.float32]) -> Path:
    path = tmp_path / name
    sf.write(str(path), samples, _SR)
    return path


def _voiced(seconds: float) -> np.typing.NDArray[np.float32]:
    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    phase = t % 0.4
    env = np.where(phase < 0.25, 1.0, 0.0)
    ramp = np.clip(np.minimum(phase / 0.01, (0.25 - phase) / 0.01), 0.0, 1.0)
    return (0.3 * np.sin(2 * np.pi * 220.0 * t) * env * ramp).astype(np.float32)


def test_preview_attaches_reference_quality_for_indextts2_clone(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _indextts2_ready(tmp_path)
    ref = _ref(tmp_path, "ref.wav", _voiced(5.0))

    result = tts_api.preview(context, {"engine": "indextts2", "voice": str(ref)})

    quality = result["reference_quality"]
    assert quality["grade"] == "good"
    assert quality["reasons"] == [] and quality["suggestions"] == []
    assert Path(result["path"]).is_file(), "质检好不影响正常试听"


def test_preview_reference_quality_reports_poor_but_does_not_block(tmp_path: Path) -> None:
    """poor 也照常返回 path：质检是报告不是门禁，拦死是假门禁。"""
    context = _context(tmp_path)
    _indextts2_ready(tmp_path)
    ref = _ref(tmp_path, "silent.wav", np.zeros(_SR * 5, dtype=np.float32))

    result = tts_api.preview(context, {"engine": "indextts2", "voice": str(ref)})

    quality = result["reference_quality"]
    assert quality["grade"] == "poor"
    assert any("静音" in reason for reason in quality["reasons"])
    assert quality["suggestions"]
    assert Path(result["path"]).is_file()


def test_preview_omits_reference_quality_for_other_engines(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    context = _context(tmp_path)

    result = tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})

    assert "reference_quality" not in result, "固定音色表引擎没有参考音频这一说"
    assert fake_engine.calls


def test_preview_omits_reference_quality_when_voice_is_not_a_file(tmp_path: Path) -> None:
    """voice 不是文件路径时无从质检——不附字段，也不替引擎判死（合成失败自有报错）。"""
    context = _context(tmp_path)
    _indextts2_ready(tmp_path)

    result = tts_api.preview(context, {"engine": "indextts2", "voice": "not-a-path"})

    assert "reference_quality" not in result
