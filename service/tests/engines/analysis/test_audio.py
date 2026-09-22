"""engines.analysis.audio_analyzer：numpy 核心。

阈值公式 max(均值×1.65, 120/满量程) 要求信号有语音/静音对比度（v1 实测条件），
故夹具用突发音（35% 占空比）模拟语音分布，恒定正弦不适用该公式域。
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from dramaclip.engines.analysis import audio_analyzer

_RATE = 16000


def _write_burst_wav(path: Path, *, total_s: float, tone_s: float, gap_s: float) -> None:
    """周期性突发音：tone_s 高电平 + gap_s 静音。"""
    frames = int(total_s * _RATE)
    tone_frames = int(tone_s * _RATE)
    period_frames = int((tone_s + gap_s) * _RATE)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_RATE)
        chunks = []
        for index in range(frames):
            in_tone = (index % period_frames) < tone_frames
            value = int(20000 * math.sin(2 * math.pi * 440 * index / _RATE)) if in_tone else 0
            chunks.append(struct.pack("<h", value))
        handle.writeframes(b"".join(chunks))


@pytest.fixture(autouse=True)
def _require_numpy() -> None:
    pytest.importorskip("numpy")


def test_burst_tone_detected_as_speech_zones(tmp_path: Path) -> None:
    wav = tmp_path / "burst.wav"
    _write_burst_wav(wav, total_s=3.0, tone_s=0.35, gap_s=0.65)
    features = audio_analyzer.analyze_audio(wav)
    assert len(features.speech_zones) == 3, "3 个突发段应识别为 3 个语音区"
    assert 0.4 < features.silence_ratio < 0.8
    assert features.energy_curve, "能量曲线不应为空"
    assert features.clipping is False


def test_full_scale_tone_is_clipping(tmp_path: Path) -> None:
    wav = tmp_path / "hot.wav"
    frames = int(0.4 * _RATE)
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_RATE)
        handle.writeframes(
            b"".join(
                struct.pack("<h", 32767 if index % 2 == 0 else -32767) for index in range(frames)
            )
        )
    features = audio_analyzer.analyze_audio(wav)
    assert features.clipping is True
    assert features.peak_dbfs is not None and features.peak_dbfs >= -0.1


def test_full_silence_has_no_speech_zones(tmp_path: Path) -> None:
    wav = tmp_path / "silence.wav"
    _write_burst_wav(wav, total_s=2.0, tone_s=0.0, gap_s=1.0)
    features = audio_analyzer.analyze_audio(wav)
    assert features.silence_ratio > 0.99
    assert features.speech_zones == []
