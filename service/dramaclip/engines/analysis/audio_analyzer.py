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
# beats 上限是防御不是常态：45 分钟集 120bpm ≈ 5400 个拍点，20000 远够不着；
# 防的是异常音频让 beat_track 吐出病态长的帧表把 JSON 列撑爆。
_BEATS_CAP = 20000


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
    bpm, beats = _estimate_bpm(samples, sample_rate)
    return AudioFeatures(
        energy_curve=_downsample_curve(rms, chunk_size, sample_rate),
        silence_ratio=round(1.0 - (speech_s / total_s if total_s > 0 else 0.0), 4),
        speech_zones=speech_zones,
        bpm=bpm,
        peak_dbfs=peak_dbfs,
        clipping=clipping,
        beats=beats,
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


def _estimate_bpm(
    samples: np.ndarray, sample_rate: int  # type: ignore[name-defined] # noqa: F821
) -> tuple[float | None, list[float]]:
    """BPM + 拍点时刻（秒，3 位小数，升序）。

    B9 之前这里是 `tempo, _ = beat.beat_track(...)`——beat 帧被丢弃，落库的只有
    一个没人消费的 BPM 数字。现在把帧转秒保留下来，编排层（narration/beat_align）
    用它做切点吸附。任何失败（无 librosa / beat_track 抛错）都降级为
    (None, [])：音频特征缺一块不该让整条分析失败。
    """
    try:
        # importlib 绕开静态导入：librosa.beat 是惰性重导出，mypy 在 strict 下
        # 必报 attr-defined，而它又是 ml extras 的可选依赖——类型检查不该决定
        # 运行时行为，拿不到模块就是 None。
        import importlib

        beat = importlib.import_module("librosa.beat")
    except ImportError:
        return None, []
    import numpy as np  # ml extras 懒加载

    try:
        tempo, frames = beat.beat_track(y=samples, sr=sample_rate)
        tempo_value = float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else None
        times = beat.frames_to_time(np.asarray(frames), sr=sample_rate)
        beats = sorted(round(float(t), 3) for t in np.asarray(times).reshape(-1))[:_BEATS_CAP]
    except Exception:  # noqa: BLE001 - 节拍提取是增强，不是分析正确性的一部分
        return None, []
    return (round(tempo_value, 1) if tempo_value else None), beats
