"""TTS 引擎工厂（按 settings tts.engine 实例化）。"""

from __future__ import annotations

from dramaclip.engines.tts.base import TtsEngine


def create(engine: str) -> TtsEngine:
    from dramaclip.engines.tts.engines.edge import EdgeTtsEngine

    if engine == "edge":
        return EdgeTtsEngine()
    raise ValueError(f"未知 TTS 引擎: {engine}（可用: edge；kokoro/indextts 于后续阶段）")
