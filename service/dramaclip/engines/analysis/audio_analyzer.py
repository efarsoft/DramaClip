"""音频特征分析：stdlib wave + numpy 核心；BPM 可选 librosa（懒加载，缺省 None）。
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

from dramaclip.engines.analysis.models import AudioFeatures, SpeechZone

_CHUNK_MS = 80
_INT16_FULL_SCALE = 32768.0
_ABS_RMS_FLOOR = 120.0 / _INT16_FULL_SCALE
_MEAN_MULTIPLIER = 1.65
_MIN_SPEECH_S = 0.28
_CURVE_POINT_S = 0.5  # 能量曲线采样间隔


def analyze_audio(wav_path: Path) -> AudioFeatures:
    """输入 16k 单声道 wav（管线标准产物），输出能量曲线/静音比/语音区/BPM。"""
    import numpy as np  # ml extras 懒加载

    with wave.open(str(wav_path), "rb") as handle:
        sample_rate = handle.getframerate()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / _INT16_FULL_SCALE
    if samples.size == 0:
        return AudioFeatures(silence_ratio=1.0)

    peak = float(np.max(np.abs(samples)))
    peak_dbfs = round(20.0 * math.log10(peak), 2) if peak > 0 else None
    clipping = peak >= 0.999

    chunk_size = max(1, int(sample_rate * _CHUNK_MS / 1000))
    chunk_count = samples.size // chunk_size
    if chunk_count == 0:
        return AudioFeatures(silence_ratio=1.0, peak_dbfs=peak_dbfs, clipping=clipping)
    trimmed = samples[: chunk_count * chunk_size].reshape(chunk_count, chunk_size)
    rms = np.sqrt(np.mean(np.square(trimmed), axis=1))

    threshold = max(float(np.mean(rms)) * _MEAN_MULTIPLIER, _ABS_RMS_FLOOR)
    speech_mask = rms > threshold
    speech_zones = _mask_to_zones(speech_mask, chunk_count, chunk_size, sample_rate)

    total_s = chunk_count * chunk_size / sample_rate
    speech_s = sum(zone.end - zone.start for zone in speech_zones)
    return AudioFeatures(
        energy_curve=_downsample_curve(rms, chunk_size, sample_rate),
        silence_ratio=round(1.0 - (speech_s / total_s if total_s > 0 else 0.0), 4),
        speech_zones=speech_zones,
        bpm=_estimate_bpm(samples, sample_rate),
        peak_dbfs=peak_dbfs,
        clipping=clipping,
    )


def _mask_to_zones(
    mask: np.ndarray,  # type: ignore[name-defined] # noqa: F821
    chunk_count: int,
    chunk_size: int,
    sample_rate: int,
) -> list[SpeechZone]:
    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for index in range(chunk_count):
        if bool(mask[index]) and run_start is None:
            run_start = index
        elif not bool(mask[index]) and run_start is not None:
            runs.append((run_start, index))
            run_start = None
    if run_start is not None:
        runs.append((run_start, chunk_count))
    span_s = chunk_size / sample_rate
    return [
        SpeechZone(start=round(begin * span_s, 3), end=round(end * span_s, 3))
        for begin, end in runs
        if (end - begin) * span_s >= _MIN_SPEECH_S
    ]


def _downsample_curve(
    rms: np.ndarray,  # type: ignore[name-defined] # noqa: F821
    chunk_size: int,
    sample_rate: int,
) -> list[list[float]]:
    points_per_curve = max(1, int(_CURVE_POINT_S / (chunk_size / sample_rate)))
    trimmed = rms[: len(rms) // points_per_curve * points_per_curve]
    if trimmed.size == 0:
        return []
    means = trimmed.reshape(-1, points_per_curve).mean(axis=1)
    return [
        [round(index * points_per_curve * chunk_size / sample_rate, 3), round(float(value), 5)]
        for index, value in enumerate(means)
    ]


def _estimate_bpm(samples: np.ndarray, sample_rate: int) -> float | None:  # type: ignore[name-defined] # noqa: F821
    try:
        # importlib 绕开静态导入：librosa.beat 是惰性重导出，mypy 在 strict 下
        # 必报 attr-defined，而它又是 ml extras 的可选依赖——类型检查不该决定
        # 运行时行为，拿不到模块就是 None。
        import importlib

        beat = importlib.import_module("librosa.beat")
    except ImportError:
        return None
    import numpy as np  # ml extras 懒加载

    tempo, _ = beat.beat_track(y=samples, sr=sample_rate)
    value = float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else None
    return round(value, 1) if value else None
