"""B6 克隆参考音频质检：inspect_reference 纯函数判据 + indextts2 合成留痕接线。

测试音频全部用 numpy 现场合成（正弦+音节包络=「人声形状」/白噪/削波/静音），
不依赖任何真实参考音频。质检是报告不是门禁：本文件任何用例都不许期待 raise。
"""

from __future__ import annotations

import io
import json
import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from dramaclip.engines.tts import reference_qc
from dramaclip.engines.tts.engines import indextts2 as indextts2_mod
from dramaclip.engines.tts.engines.indextts2 import IndexTts2Engine

_SR = 22050  # worker 落盘采样率（与 indextts2._SAMPLE_RATE 同口径）
_LOGGER = "dramaclip.engines.tts.engines.indextts2"


def _voiced(seconds: float, amp: float = 0.3, noise_sigma: float = 0.0) -> Any:
    """类人声形状：220Hz 正弦按 0.25s 响 / 0.15s 停的音节节奏切段，可叠加白噪底。

    段边界做 10ms 起收坡——爆音会造成假削波，干扰削波判据。
    """
    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    phase = t % 0.4
    env = np.where(phase < 0.25, 1.0, 0.0)
    ramp = np.clip(np.minimum(phase / 0.01, (0.25 - phase) / 0.01), 0.0, 1.0)
    signal = amp * np.sin(2 * np.pi * 220.0 * t) * env * ramp
    if noise_sigma > 0:
        signal = signal + np.random.default_rng(42).normal(0.0, noise_sigma, n)
    return signal.astype(np.float32)


def _write(tmp_path: Path, name: str, samples: Any) -> Path:
    path = tmp_path / name
    sf.write(str(path), samples, _SR)
    return path


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """模块级缓存跨用例会串台：每个用例前清空。"""
    monkeypatch.setattr(reference_qc, "_CACHE", {})


# ---------------------------------------------------------------- 判据分档


def test_clean_reference_grades_good(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(_write(tmp_path, "ref.wav", _voiced(5.0)))
    assert q.grade == "good"
    assert q.reasons == [] and q.suggestions == []
    assert set(q.metrics) == {"duration_s", "rms_dbfs", "peak_dbfs", "clip_ratio", "snr_db"}
    assert q.metrics["duration_s"] == pytest.approx(5.0, abs=0.01)
    assert q.metrics["snr_db"] >= 15.0


def test_clipped_reference_grades_poor(tmp_path: Path) -> None:
    clipped = np.clip(_voiced(5.0) * 10.0, -1.0, 1.0)
    q = reference_qc.inspect_reference(_write(tmp_path, "clip.wav", clipped))
    assert q.metrics["clip_ratio"] > 0.01
    assert q.grade == "poor"
    assert any("削波" in reason for reason in q.reasons)
    assert any("增益" in sug for sug in q.suggestions)


def test_short_reference_grades_poor_on_duration(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(_write(tmp_path, "short.wav", _voiced(1.0)))
    assert q.grade == "poor"
    assert any("时长" in reason and "1.0" in reason for reason in q.reasons)
    assert any("3" in sug and "10" in sug for sug in q.suggestions)


def test_overlong_reference_grades_fair(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(_write(tmp_path, "long.wav", _voiced(35.0)))
    assert q.grade == "fair"
    assert any("时长" in reason for reason in q.reasons)


def test_silent_reference_grades_poor(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(
        _write(tmp_path, "silence.wav", np.zeros(_SR * 5, dtype=np.float32))
    )
    assert q.grade == "poor"
    assert any("静音" in reason for reason in q.reasons)
    assert q.metrics["rms_dbfs"] <= -60.0


def test_low_level_reference_grades_fair(tmp_path: Path) -> None:
    samples = _voiced(5.0)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    quiet = (samples * (10 ** (-45.0 / 20)) / rms).astype(np.float32)
    q = reference_qc.inspect_reference(_write(tmp_path, "quiet.wav", quiet))
    assert q.grade == "fair"
    assert any("音量" in reason for reason in q.reasons)


def test_noisy_reference_flags_snr(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(
        _write(tmp_path, "noisy.wav", _voiced(5.0, noise_sigma=0.15))
    )
    assert q.grade in {"fair", "poor"}
    assert any("信噪比" in reason for reason in q.reasons)


def test_mildly_noisy_reference_is_fair(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(
        _write(tmp_path, "mild.wav", _voiced(5.0, noise_sigma=0.05))
    )
    assert q.grade == "fair"
    assert any("信噪比" in reason for reason in q.reasons)


# ---------------------------------------------------------------- 坏输入不 raise


def test_missing_file_reports_poor_without_raising(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(tmp_path / "nope.wav")
    assert q.grade == "poor"
    assert any("不存在" in reason for reason in q.reasons)
    assert q.suggestions


def test_unreadable_file_reports_poor_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "junk.wav"
    path.write_bytes(b"riff-not-audio")
    q = reference_qc.inspect_reference(path)
    assert q.grade == "poor"
    assert q.reasons and q.suggestions


def test_empty_stream_reports_poor(tmp_path: Path) -> None:
    q = reference_qc.inspect_reference(_write(tmp_path, "empty.wav", np.zeros(0, dtype="float32")))
    assert q.grade == "poor"
    assert any("音频流" in reason for reason in q.reasons)


# ---------------------------------------------------------------- 缓存


def test_cache_hit_does_not_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "ref.wav", _voiced(5.0))
    calls: list[Path] = []
    real = reference_qc._read_samples

    def counted(p: Path) -> Any:
        calls.append(p)
        return real(p)

    monkeypatch.setattr(reference_qc, "_read_samples", counted)
    first = reference_qc.inspect_reference(path)
    second = reference_qc.inspect_reference(path)
    assert second is first, "缓存命中返回同一份结果"
    assert len(calls) == 1, "缓存命中不重读音频"


def test_cache_invalidates_when_file_changes(tmp_path: Path) -> None:
    path = _write(tmp_path, "ref.wav", _voiced(5.0))
    assert reference_qc.inspect_reference(path).metrics["duration_s"] == pytest.approx(
        5.0, abs=0.01
    )
    sf.write(str(path), _voiced(1.0), _SR)  # 大小/mtime 变 → (size, mtime_ns) 键失效
    q = reference_qc.inspect_reference(path)
    assert q.metrics["duration_s"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------- indextts2 接线


class _FakeStdin(io.TextIOBase):
    def __init__(self, proc: _FakeProc) -> None:
        self._proc = proc

    def write(self, job_line: str) -> int:
        self._proc.handle(json.loads(job_line))
        return len(job_line)

    def flush(self) -> None: ...


class _FakeProc:
    """假 worker（与 test_long_text_synth 同形）：真写 wav、按序回应答。"""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.replies: list[str] = ['{"ready": true, "device": "cpu"}']
        self.stdin = _FakeStdin(self)
        self.stdout = self

    def handle(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_SR)
            wav.writeframes(b"\x01\x00" * (len(job["text"]) * 10))
        self.replies.append(json.dumps({"id": job["id"], "ok": True}))

    def readline(self) -> str:
        return self.replies.pop(0) + "\n"


@pytest.fixture
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> _FakeProc:
    proc = _FakeProc()
    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: True)
    monkeypatch.setattr(indextts2_mod, "_ensure_worker", lambda _d: proc)
    return proc


def test_synthesize_warns_on_poor_reference_but_still_synthesizes(
    tmp_path: Path, fake_worker: _FakeProc, caplog: pytest.LogCaptureFixture
) -> None:
    ref = _write(tmp_path, "silent.wav", np.zeros(_SR * 5, dtype=np.float32))
    out = tmp_path / "n0.wav"

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = IndexTts2Engine(tmp_path).synthesize("短句。", str(ref), out)

    assert result == out and out.is_file(), "poor 不阻断：质检是报告不是门禁"
    assert len(fake_worker.jobs) == 1
    warns = [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER and r.levelno == logging.WARNING
    ]
    assert warns, "poor 必须留痕"
    assert "poor" in warns[0] and "静音" in warns[0], "留痕带 grade+reasons"


def test_synthesize_good_reference_logs_no_qc_warning(
    tmp_path: Path, fake_worker: _FakeProc, caplog: pytest.LogCaptureFixture
) -> None:
    ref = _write(tmp_path, "ref.wav", _voiced(5.0))
    out = tmp_path / "n0.wav"

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        IndexTts2Engine(tmp_path).synthesize("短句。", str(ref), out)

    assert out.is_file()
    assert not [
        r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING
    ]


def test_synthesize_unreadable_reference_still_synthesizes(
    tmp_path: Path, fake_worker: _FakeProc
) -> None:
    """假参考（b"riff"）质检读不懂——合成照常，质检永不挡路。"""
    ref = tmp_path / "fake.wav"
    ref.write_bytes(b"riff")
    out = tmp_path / "n0.wav"

    IndexTts2Engine(tmp_path).synthesize("短句。", str(ref), out)

    assert out.is_file() and len(fake_worker.jobs) == 1
