"""停顿切分：能量检测找句间停顿，把整条音频切成短语级片段（本地 ASR 基础设施）。

BGM 素材的痛点：人声句间有停顿，但音乐把停顿填满——funasr 内部 VAD 的阈值式
判据分不清「人声停了」与「安静」，导致跨停顿并句 + 字级时间戳插值漂移。
本模块从**能量曲线**找停顿：BGM 平稳（能量曲线平直），语音段能量显著抬升——
「平稳底噪上的能量谷」就是句间停顿，比「绝对安静」可靠得多。

切分后逐片段转写：每段=一个自然短语组，并句/串音物理消失；时间戳以片段起点
为锚（真实切分位置，非插值）。
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

_FRAME_S = 0.03  # 帧长 30ms：短剧旁白语速下足够分辨停顿
_MIN_PAUSE_S = 0.32  # 停顿判定：能量谷持续时长下限（短剧句间停顿普遍 0.3s+）
_MIN_CLIP_S = 1.0  # 片段最短时长（防过碎）
_MAX_CLIP_S = 12.0  # 片段最长时长（超长在内部最弱谷处二次切分）
_NOISE_PERCENTILE = 0.2  # 底噪估计：能量最低 20% 帧的均值
_SPEECH_FACTOR = 2.2  # 语音判定：能量 > 底噪 × 此系数


@dataclass(frozen=True)
class Clip:
    """语音片段：绝对起止秒。"""

    start: float
    end: float


class PauseAnalysisUnavailable(ValueError):
    """这份素材量不出停顿（格式不合、过短）——调用方据此退回整条直喂。

    单独成类是为了和**代码写错**分的开：早先调用方 `except (OSError, ValueError)`
    把两类混为一谈，`strict=True` 的 zip 必抛的 ValueError 被当成「素材不可用」
    静默吞掉——于是一个超 12s 的语音区段就能让整条分析退回直喂，而这在整集素材
    上是常态。编程错误要继续往外抛。
    """


def _frame_energies(pcm: bytes, frame_bytes: int) -> list[float]:
    """逐帧 RMS（16bit 小端）：audioop 在 3.13 移除，纯 int 运算。"""
    energies: list[float] = []
    for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        total = 0
        samples = frame_bytes // 2
        for j in range(samples):
            sample = int.from_bytes(pcm[i + j * 2 : i + j * 2 + 2], "little", signed=True)
            total += sample * sample
        energies.append((total / samples) ** 0.5)
    return energies


def _noise_floor(energies: list[float]) -> float:
    """底噪估计：能量最低 20% 帧的均值（BGM 平稳段的主导能量）。"""
    ordered = sorted(energies)
    tail = ordered[: max(1, int(len(ordered) * _NOISE_PERCENTILE))]
    return sum(tail) / len(tail) or 1.0


def speech_clips(
    wav_path: Path,
    *,
    min_pause_s: float = _MIN_PAUSE_S,
    min_clip_s: float = _MIN_CLIP_S,
    max_clip_s: float = _MAX_CLIP_S,
) -> list[Clip]:
    """能量停顿检测：返回语音片段列表（绝对秒）。无有效切分时返回整条单片段。"""
    with wave.open(str(wav_path), "rb") as wf:
        width = wf.getsampwidth()
        if width != 2 or wf.getnchannels() != 1:
            actual = f"{width * 8}bit/{wf.getnchannels()}ch"
            raise PauseAnalysisUnavailable(f"仅支持 16k 单声道 16bit wav，实际 {actual}")
        rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    duration = len(pcm) / (2 * rate)
    frame_bytes = int(rate * _FRAME_S) * 2
    energies = _frame_energies(pcm, frame_bytes)
    if not energies:
        raise PauseAnalysisUnavailable("音频过短，无法分析")
    del pcm

    floor = _noise_floor(energies)
    threshold = floor * _SPEECH_FACTOR
    speech = [energy >= threshold for energy in energies]

    # 帧序 → 语音区段（帧索引 × 帧长）
    frames_per_pause = max(1, int(min_pause_s / _FRAME_S))
    regions: list[list[int]] = []
    start = None
    for index, is_speech in enumerate(speech):
        if is_speech and start is None:
            start = index
        if not is_speech and start is not None:
            if regions and start - regions[-1][1] <= frames_per_pause:
                regions[-1][1] = index  # 短停顿合并进当前语音区
            else:
                regions.append([start, index])
            start = None
    if start is not None:
        if regions and start - regions[-1][1] <= frames_per_pause:
            regions[-1][1] = len(speech)
        else:
            regions.append([start, len(speech)])

    clips: list[Clip] = []
    for s_frame, e_frame in regions:
        s, e = s_frame * _FRAME_S, e_frame * _FRAME_S
        if e - s < min_clip_s:
            continue
        if e - s <= max_clip_s:
            if clips and s - clips[-1].end < min_pause_s:
                clips[-1] = Clip(clips[-1].start, e)
            else:
                clips.append(Clip(s, e))
            continue
        # 超长区段：在内部能量最低的等分点附近二次切分
        span_frames = e_frame - s_frame
        parts = int((e - s) / max_clip_s) + 1
        part_frames = span_frames // parts
        cuts = [s_frame + k * part_frames for k in range(1, parts)]
        cuts = [_weakest(cut, part_frames // 4, energies) for cut in cuts]
        bounds = [s_frame, *cuts, e_frame]
        for a, b in pairwise(bounds):
            a_s, b_e = a * _FRAME_S, b * _FRAME_S
            if b_e - a_s < min_clip_s:
                continue
            # 区段内的人工切点两侧本就相连，不参与「短停顿并回」判定——那条只对
            # 区段之间成立（区段生成时已并过 ≤min_pause_s 的停顿），照套会把刚
            # 切开的两半并回一整段，二次切分等于没切。
            clips.append(Clip(a_s, b_e))
    if not clips:
        clips = [Clip(0.0, duration)]
    return clips


def fill_degenerate(clips: list[Clip], *, max_clip_s: float = _MAX_CLIP_S) -> str | None:
    """切分退化信号：顶格片段（≈max_clip_s）占比过半 → 能量谷疑被 BGM 填满。

    正常素材的切点落在真实停顿上，片段长短随语句自然分布；BGM 填满停顿时谷不深、
    语音区段连成一片，二次切分也只能在「最不坏的位置」硬下刀——产物里大量片段顶到
    max_clip_s。《颠勺》EP1 实锤形态：切分退化 → 整条直喂 → funasr VAD 失效 →
    时间轴坍缩。返回描述文案（None=切分健康），调用方据此留痕/建议切云端。
    """
    if len(clips) < 2:
        return None
    at_cap = sum(1 for clip in clips if clip.end - clip.start >= max_clip_s * 0.95)
    if at_cap * 2 < len(clips):
        return None
    return f"{at_cap}/{len(clips)} 段顶到 {max_clip_s:.0f}s 上限、无真实停顿可切"


def _weakest(center_frame: int, window: int, energies: list[float]) -> int:
    """center_frame ± window 范围内能量最低的帧索引（最像停顿的位置）。"""
    lo = max(0, center_frame - window)
    hi = min(len(energies), center_frame + window)
    window_energies = energies[lo:hi]
    return lo + window_energies.index(min(window_energies))


def split_wav(
    wav_path: Path, clips: list[Clip], out_dir: Path
) -> list[tuple[Clip, Path]]:
    """按片段切出 wav 文件（ffmpeg 精确 seek），返回 [(片段, 路径)]。"""
    import subprocess

    from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Clip, Path]] = []
    for index, clip in enumerate(clips):
        out = out_dir / f"clip-{index:02d}.wav"
        subprocess.run(  # noqa: S603 - 参数为受控列表
            [
                str(resolve_ffmpeg()),
                "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(wav_path),
                "-ss", f"{clip.start:.3f}",
                "-t", f"{clip.end - clip.start:.3f}",
                "-c", "copy",
                str(out),
            ],
            check=True,
        )
        results.append((clip, out))
    return results
