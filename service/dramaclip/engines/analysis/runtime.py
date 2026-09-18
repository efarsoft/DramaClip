"""引擎运行时：按设置懒构建并缓存引擎单例（模型加载昂贵，进程内只加载一次）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.analysis.transcriber import (
    AsrEngine,
    FasterWhisperEngine,
    SenseVoiceEngine,
)
from dramaclip.infra import config


class AnalysisRuntime:
    """transcriber 等引擎的懒加载单例容器（线程安全由构建锁保证）。"""

    def __init__(self, settings: config.Settings, models_dir: Path) -> None:
        self._settings = settings
        self._models_dir = models_dir
        self._transcriber: AsrEngine | None = None

    def transcriber(self) -> AsrEngine:
        if self._transcriber is None:
            self._transcriber = _build_transcriber(self._settings, self._models_dir)
        return self._transcriber


def _build_transcriber(settings: config.Settings, models_dir: Path) -> AsrEngine:
    engine = settings.get("asr.engine", "faster_whisper")
    if engine == "sensevoice":
        return SenseVoiceEngine(models_dir=models_dir)
    if engine == "paraformer":
        from dramaclip.engines.analysis.transcriber import ParaformerEngine

        return ParaformerEngine(models_dir=models_dir)
    model_size = settings.get("asr.model", "base")
    device = settings.get("asr.device", "cpu")
    return FasterWhisperEngine(
        model_size, device=device, models_dir=models_dir / "asr" / "faster-whisper"
    )


def language(settings: config.Settings) -> str:
    return settings.get("asr.language", "zh")
