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


def supported() -> frozenset[str]:
    """真能构建出来的转写引擎名——``registry.engine_ready`` 读这里，两边不各存一份名单。

    ``paraformer`` / ``firedred`` 在模型清单里有登记项但这里没有实现，所以它们不是
    「已接入」；旧代码里那条 ``paraformer`` 分支 import 的是一个不存在的类，走到就炸。
    """
    return frozenset({"faster_whisper", "sensevoice"})


def _build_transcriber(settings: config.Settings, models_dir: Path) -> AsrEngine:
    engine = settings.get("asr.engine", "faster_whisper")
    if engine not in supported():
        available = " / ".join(sorted(supported()))
        raise ValueError(f"未知 ASR 引擎: {engine}（可用: {available}）")
    if engine == "sensevoice":
        return SenseVoiceEngine(models_dir=models_dir)
    model_size = settings.get("asr.model", "base")
    device = settings.get("asr.device", "cpu")
    return FasterWhisperEngine(
        model_size,
        device=device,
        models_dir=models_dir / "asr" / "faster-whisper",
        compute_type=settings.get("asr.compute_type", "auto"),
    )


def language(settings: config.Settings) -> str:
    return settings.get("asr.language", "zh")
