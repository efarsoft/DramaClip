"""B9：beat 时间戳落库（audio_analyzer 保留 beat_track 的帧并转秒）。

假 librosa 用 monkeypatch 塞进 sys.modules——分析测试不真加载 librosa（重依赖，
且真 beat_track 对 3 秒突发音的输出没有可断言的确定值）。
"""

from __future__ import annotations

import json
import math
import struct
import sys
import types
import wave
from pathlib import Path

import pytest

from dramaclip.engines.analysis import audio_analyzer
from dramaclip.engines.analysis.models import AudioFeatures

_RATE = 16000


@pytest.fixture(autouse=True)
def _require_numpy() -> None:
    pytest.importorskip("numpy")


def _write_tone_wav(path: Path, total_s: float = 3.0) -> None:
    """有内容的 wav 即可（beat 提取被 stub，信号形状无关）。"""
    frames = int(total_s * _RATE)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_RATE)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(20000 * math.sin(2 * math.pi * 440 * i / _RATE)))
                for i in range(frames)
            )
        )


def _stub_librosa_beat(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tempo: float = 120.0,
    frames: tuple[int, ...] = (16000, 32000),
) -> None:
    """假 librosa.beat：beat_track 返回 (tempo, 帧号)，frames_to_time 按 sr 换算。"""
    import numpy as np

    module = types.ModuleType("librosa.beat")
    module.beat_track = (  # type: ignore[attr-defined]
        lambda y, sr: (np.float32(tempo), np.asarray(frames))
    )
    module.frames_to_time = (  # type: ignore[attr-defined]
        lambda fr, sr: np.asarray(fr, dtype=float) / sr
    )
    parent = types.ModuleType("librosa")
    parent.beat = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "librosa", parent)
    monkeypatch.setitem(sys.modules, "librosa.beat", module)


def test_beat_frames_are_kept_and_converted_to_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """此前 `tempo, _ = beat_track(...)` 把 beat 帧丢弃：现在必须保留并转秒。"""
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)
    _stub_librosa_beat(monkeypatch, tempo=120.0, frames=(16000, 32000, 47999))
    features = audio_analyzer.analyze_audio(wav)
    assert features.bpm == 120.0
    assert features.beats == [1.0, 2.0, 3.0], "帧号/sr 转秒，四舍五入到 3 位小数"


def test_beats_are_sorted_ascending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """落库契约是升序（吸附层做最近邻时依赖它可读、可二分）。"""
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)
    _stub_librosa_beat(monkeypatch, frames=(48000, 16000, 32000))
    features = audio_analyzer.analyze_audio(wav)
    assert features.beats == [1.0, 2.0, 3.0]


def test_beats_capped_defensively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """上限截断是防御不是常态：45 分钟集 120bpm ≈ 5400 拍，远够不着 20000。"""
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)
    _stub_librosa_beat(monkeypatch, frames=tuple(range(audio_analyzer._BEATS_CAP + 5000)))
    features = audio_analyzer.analyze_audio(wav)
    assert len(features.beats) == audio_analyzer._BEATS_CAP


def test_no_librosa_degrades_to_empty_beats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 librosa（ml extras 未装）：bpm=None、beats=[]，既有降级路径不变。"""
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)
    monkeypatch.setitem(sys.modules, "librosa", None)
    monkeypatch.setitem(sys.modules, "librosa.beat", None)
    features = audio_analyzer.analyze_audio(wav)
    assert features.bpm is None
    assert features.beats == []


def test_beat_track_failure_degrades_to_empty_beats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """librosa 在但 beat_track 抛错（损坏音频/内部异常）：不能让整条分析失败。"""
    wav = tmp_path / "tone.wav"
    _write_tone_wav(wav)

    module = types.ModuleType("librosa.beat")

    def _boom(y: object, sr: int) -> None:
        raise RuntimeError("beat tracking exploded")

    module.beat_track = _boom  # type: ignore[attr-defined]
    parent = types.ModuleType("librosa")
    parent.beat = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "librosa", parent)
    monkeypatch.setitem(sys.modules, "librosa.beat", module)
    features = audio_analyzer.analyze_audio(wav)
    assert features.bpm is None
    assert features.beats == []
    assert features.energy_curve, "音频其余特征照常产出"


def test_old_record_json_without_beats_field_validates_to_empty_list() -> None:
    """旧库分析记录的 audio_features JSON 没有 beats 字段：默认空列表，天然兼容，
    不强制重分析（B8 源签名也不含分析产物形状）。"""
    legacy = json.dumps({"silence_ratio": 0.4, "bpm": 90.0, "clipping": False})
    features = AudioFeatures.model_validate(json.loads(legacy))
    assert features.beats == []
    assert features.bpm == 90.0
