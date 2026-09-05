"""阶段一：轻量预筛（原案 3附）：每集 1-3s，纯 FFmpeg/既有信号，不用 GPU/模型。

预筛分 = 30×切镜密度 + 25×人声活跃度 + 25×能量峰值密度 + 20×运动幅度（各归一化 0-1）。
复用第一层引擎信号（audio_analyzer / scene_detector）；运动幅度用 FFmpeg signalstats 采样。
"""

from __future__ import annotations

import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path

from dramaclip.engines.analysis import audio_analyzer, scene_detector
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

# 原案 3附.4 权重
_W_SCENE = 30.0
_W_VOICE = 25.0
_W_ENERGY = 25.0
_W_MOTION = 20.0

_YDIF_SAMPLE_FPS = 2  # 运动采样降帧（速度：1-3s/集 的关键）


def motion_intensity(video_path: Path) -> float:
    """帧间差分均值（signalstats YDIF），归一化 0-1。解码降帧到 2fps 提速。"""
    args = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={_YDIF_SAMPLE_FPS},signalstats,metadata=print:file=-",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(  # noqa: S603
        [resolve_ffmpeg(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    values: list[float] = []
    for line in result.stdout.splitlines():
        if "lavfi.signalstats.YDIF=" in line:
            try:
                values.append(float(line.split("YDIF=")[1].strip()))
            except ValueError:
                continue
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return max(0.0, min(mean / 8.0, 1.0))  # YDIF≈8 视为高强度


def prescreen_episode(
    video_path: Path,
    wav_path: Path,
) -> dict[str, float]:
    """预筛单集，返回四项信号 + prescreen_score + recommended。调用方负责落库。"""
    from dramaclip.engines.analysis import pipeline as analysis_pipeline

    wav_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_pipeline.extract_audio(video_path, wav_path)

    zones_source = wav_path
    features = audio_analyzer.analyze_audio(zones_source)
    speech_ratio = 1.0 - features.silence_ratio
    peaks = _energy_peak_density(features.energy_curve, features.silence_ratio)

    cuts = scene_detector.detect_scenes(video_path)
    duration = features.energy_curve[-1][0] if features.energy_curve else 0.0
    cuts_per_min = (len(cuts) / duration * 60.0) if duration > 0 else 0.0
    scene_density = min(cuts_per_min / 30.0, 1.0)  # 每分钟 30 切 ≈ 满格

    motion = motion_intensity(video_path)
    energy_density = min(peaks, 1.0)

    score = (
        _W_SCENE * scene_density
        + _W_VOICE * speech_ratio
        + _W_ENERGY * energy_density
        + _W_MOTION * motion
    )
    return {
        "audio_peak_density": round(energy_density, 4),
        "scene_cut_density": round(scene_density, 4),
        "voice_activity_ratio": round(speech_ratio, 4),
        "motion_intensity": round(motion, 4),
        "prescreen_score": round(score, 1),
        "recommended": score >= 70.0,
    }


def _energy_peak_density(curve: list[list[float]], silence_ratio: float) -> float:
    """能量曲线的局部峰值密度（峰/点），按静音比补偿。"""
    if len(curve) < 3:
        return 0.0
    values = [value for _t, value in curve]
    peaks = sum(
        1
        for index in range(1, len(values) - 1)
        if values[index] > values[index - 1] and values[index] >= values[index + 1]
    )
    density = peaks / (len(values) - 2)
    return density * (1.0 - silence_ratio)
