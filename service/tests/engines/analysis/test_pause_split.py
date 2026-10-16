"""pause_split：能量停顿检测与片段切分（合成音频验证）。"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from dramaclip.engines.analysis import pause_split

_RATE = 16000


def _write_wav(path: Path, tone_seconds: list[float], tone_amp: int = 8000) -> None:
    """交替写入【 Tone秒正弦 / gap秒静音】的 16k 单声道 16bit wav。"""
    frames: list[bytes] = []
    for i, seconds in enumerate(tone_seconds):
        n = int(_RATE * seconds)
        if i % 2 == 0:  # 偶数位 = 语音段（正弦）
            for k in range(n):
                value = int(tone_amp * math.sin(2 * math.pi * 440 * k / _RATE))
                frames.append(int.to_bytes(value, 2, "little", signed=True))
        else:  # 奇数位 = 停顿（静音）
            frames.extend([b"\x00\x00"] * n)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(b"".join(frames))


def test_speech_clips_finds_phrase_gaps(tmp_path: Path) -> None:
    """语音 1.2s / 停顿 0.6s 交替 ×3 → 3 个片段（并句物理消失的基础）。"""
    wav = tmp_path / "burst.wav"
    _write_wav(wav, [1.2, 0.6, 1.2, 0.6, 1.2])
    clips = pause_split.speech_clips(wav)
    assert len(clips) == 3
    assert clips[0].start == pytest.approx(0.0, abs=0.15)
    assert clips[2].end == pytest.approx(4.8, abs=0.3)
    for clip in clips:
        assert clip.end - clip.start >= 1.0


def test_speech_clips_single_tone_is_one_clip(tmp_path: Path) -> None:
    """连续语音无停顿 → 单片段（不误切）。"""
    wav = tmp_path / "steady.wav"
    _write_wav(wav, [3.0])
    clips = pause_split.speech_clips(wav)
    assert len(clips) == 1
    assert clips[0].end - clips[0].start == pytest.approx(3.0, abs=0.2)


def test_speech_clips_pure_silence_falls_back_whole(tmp_path: Path) -> None:
    """纯静音（无语音特征）→ 整条单片段兜底，不抛不空。"""
    wav = tmp_path / "silent.wav"
    _write_wav(wav, [1.5, 1.5])  # 全静音（两段都是静音语义，但构造只区分奇偶）
    clips = pause_split.speech_clips(wav)
    assert clips and clips[0].end - clips[0].start >= 1.0


def test_speech_clips_splits_oversized_region(tmp_path: Path) -> None:
    """单个区段长过 `_MAX_CLIP_S` → 在内部能量谷二次切分，片段不得越过上限。

    这是停顿切分的常态而非边角：整集音频里 BGM 把句间填满，语音区段轻松超 12s。
    构造 13s 语音 / 4s 停顿 / 13s 语音（静音占满 20% 帧，底噪估计才不会被语音污染），
    两个区段都落进超长分支 → 每段各切两刀。
    """
    wav = tmp_path / "long.wav"
    _write_wav(wav, [13.0, 4.0, 13.0])
    clips = pause_split.speech_clips(wav)

    assert len(clips) == 4, "两个 13s 区段各应切成 2 个片段"
    assert clips[0].start == pytest.approx(0.0, abs=0.2)
    assert clips[-1].end == pytest.approx(30.0, abs=0.2)
    for clip in clips:
        assert 1.0 <= clip.end - clip.start <= pause_split._MAX_CLIP_S + 0.1


def test_split_wav_cuts_at_clip_bounds(tmp_path: Path) -> None:
    wav = tmp_path / "burst.wav"
    _write_wav(wav, [1.2, 0.6, 1.2])
    clips = pause_split.speech_clips(wav)
    results = pause_split.split_wav(wav, clips, tmp_path / "out")
    paths = [path for _clip, path in results if path.is_file()]
    assert len(paths) == len(results) and all(p.is_file() for p in paths)
    for clip, path in results:
        assert path.is_file() and path.stat().st_size > 1000
        assert clip.end - clip.start == pytest.approx(1.2, abs=0.1)


def test_sample_width_mismatch_raises(tmp_path: Path) -> None:
    """8bit wav → 如实报错（分档：调用方回退整条直喂）。"""
    wav = tmp_path / "8bit.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(_RATE)
        wf.writeframes(b"\x80" * _RATE)
    with pytest.raises(ValueError, match="16k 单声道"):
        pause_split.speech_clips(wav)
