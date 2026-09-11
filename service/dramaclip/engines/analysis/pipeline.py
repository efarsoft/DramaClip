"""单集分析管线：抽音频 → ASR → 场景 → 音频特征（原案第三章第一层）。

进度权重：抽音频 0→0.2，ASR 0.2→0.55，场景 0.55→0.75，音频 0.75→0.95，完成 1.0。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from dramaclip.engines.analysis import audio_analyzer, scene_detector
from dramaclip.engines.analysis.models import EpisodeRawAnalysis
from dramaclip.engines.analysis.transcriber import AsrEngine
from dramaclip.infra.ffmpeg import runner

ProgressReporter = Callable[[float, str], None]


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
    _emit(0.55, "场景切割")
    scenes = scene_detector.merge_scenes(scene_detector.detect_scenes(video_path))
    _emit(0.75, "音频特征")
    audio = audio_analyzer.analyze_audio(wav_path)
    _emit(1.0, "分析完成")
    return EpisodeRawAnalysis(asr_segments=asr_segments, scenes=scenes, audio=audio)
