"""TTS 引擎工厂（按 settings tts.engine 实例化）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.tts.base import TtsEngine


def create(engine: str, models_dir: Path | None = None) -> TtsEngine:
    from dramaclip.engines.tts.engines.edge import EdgeTtsEngine
    from dramaclip.engines.tts.engines.kokoro import KokoroEngine

    if engine == "edge":
        return EdgeTtsEngine()
    if engine == "kokoro":
        if models_dir is None:
            raise ValueError("kokoro 引擎需要 models_dir")
        return KokoroEngine(models_dir / "tts" / "kokoro" / "Kokoro-82M-v1.1-zh")
    if engine == "sherpa_melo":
        from dramaclip.engines.tts.engines.sherpa import SherpaTtsEngine

        if models_dir is None:
            raise ValueError("sherpa_melo 引擎需要 models_dir")
        return SherpaTtsEngine(models_dir / "tts" / "sherpa-onnx" / "melo" / "vits-melo-tts-zh_en")
    raise ValueError(f"未知 TTS 引擎: {engine}（可用: edge / kokoro / sherpa_melo）")
