"""单集分析管线：抽音频 → ASR → 场景 → 音频特征（原案第三章第一层）。

转写完成后的产物级体检（时间轴坍缩检测）在这里做而不是各引擎里：判据对全部
引擎通用（本地 funasr / whisper / 云端切片都可能有坏产物），而且 pipeline 拿得到
整条转写结果与全片时长——引擎层只见自己的片段。
"""

from __future__ import annotations

import hashlib
import threading
import wave
from collections.abc import Callable
from pathlib import Path

from dramaclip.engines.analysis import audio_analyzer, scene_detector
from dramaclip.engines.analysis.models import AsrSegment, EpisodeRawAnalysis
from dramaclip.engines.analysis.transcriber import AsrEngine
from dramaclip.infra.ffmpeg import runner

ProgressReporter = Callable[[float, str], None]

_COLLAPSE_MIN_SEGMENTS = 20
"""段数下限：台词稀疏的集本来段就少，少量段挤在一起是正常场景。"""

_COLLAPSE_SPAN_S = 15.0
"""坍缩窗：《颠勺》EP1 实锤 46 段挤 0–11.58s；段总跨度低于这个窗（且远小于全片）
＝字级时间戳失去真实锚、全挤进首个转写单元的特征形态。"""


def _wav_duration_s(wav_path: Path) -> float:
    """wav 时长（秒）；读不到返回 0，坍缩检测按「无法判定」跳过。"""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except (OSError, wave.Error):
        return 0.0


def collapse_warning(segments: list[AsrSegment], duration_s: float) -> str | None:
    """时间轴坍缩特征：大量段挤进开头窄窗（远小于全片）。

    不拦流程只留痕——坏时间轴的后果在下游可见（字幕错位、台词保护区错位），
    但分析层没有更好的时间轴可换，能做的是把「这份转写不可信」如实告诉用户。
    """
    if len(segments) < _COLLAPSE_MIN_SEGMENTS:
        return None
    span = max(seg.end for seg in segments) - min(seg.start for seg in segments)
    if duration_s > 0 and span > min(_COLLAPSE_SPAN_S, duration_s * 0.1):
        return None
    window = f"{span:.1f}s" if span > 0 else "0s"
    detail = f"（全片 {duration_s:.0f}s）" if duration_s > 0 else ""
    return (
        f"转写时间轴疑似坍缩：{len(segments)} 段全挤在 {window} 内{detail}"
        "——字幕/台词锚点不可信，建议切云端 ASR 重析本集"
    )


def source_signature(video_path: Path, *, ocr_channel: bool = True) -> str | None:
    """源文件签名（B8 失效判据）：md5(path|size|mtime_ns|ocr_channel)；文件缺失返回 None。

    为何三元够用：同路径、同字节大小、同纳秒 mtime 但内容不同的概率可忽略——
    替换文件必然改 mtime，截断/追加必然改 size。不纳入 shots/scenes digest 是因为
    镜头列表本身是分析的产物，签名依赖分析结果会构成循环（判失效前先要有效结果）。
    ocr_channel（OCR 通道可用性）参与签名：通道缺失时产物是纯 ASR 降级版，
    依赖装好后签名失配即强制重算，降级结果不会永久滞留。
    """
    try:
        stat = video_path.stat()
    except OSError:
        return None
    basis = f"{video_path}|{stat.st_size}|{stat.st_mtime_ns}|{int(ocr_channel)}"
    return hashlib.md5(basis.encode("utf-8")).hexdigest()


def extract_audio(video_path: Path, wav_path: Path) -> None:
    """抽 16k 单声道 wav 到工作目录。"""
    runner.run(
        runner.extract_audio_args(str(video_path), str(wav_path)),
        timeout_s=600,
    )


def analyze_episode(
    video_path: Path,
    work_dir: Path,
    transcriber: AsrEngine,
    language: str,
    *,
    cancel: threading.Event | None = None,
    report: ProgressReporter | None = None,
    hotwords: str = "",
) -> EpisodeRawAnalysis:
    """执行单集第一层分析。cancel 置位在步骤间隙生效。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    wav_path = work_dir / f"{video_path.stem}.wav"

    def _cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    def _emit(percent: float, message: str) -> None:
        if report is not None:
            report(percent, message)

    _emit(0.02, "提取音频")
    extract_audio(video_path, wav_path)
    if _cancelled():
        raise runner.FfmpegError("已取消", cancelled=True)
    _emit(0.2, f"ASR 转写（{transcriber.name}）")
    asr_segments = transcriber.transcribe(wav_path, language=language, hotwords=hotwords)
    if _cancelled():
        raise runner.FfmpegError("已取消", cancelled=True)
    warnings: list[str] = []
    collapse = collapse_warning(asr_segments, _wav_duration_s(wav_path))
    if collapse is not None:
        warnings.append(collapse)
    _emit(0.55, "场景切割")
    scenes = scene_detector.merge_scenes(scene_detector.detect_scenes(video_path))
    _emit(0.75, "音频特征")
    audio = audio_analyzer.analyze_audio(wav_path)
    _emit(1.0, "分析完成")
    return EpisodeRawAnalysis(
        asr_segments=asr_segments, scenes=scenes, audio=audio, warnings=warnings
    )
