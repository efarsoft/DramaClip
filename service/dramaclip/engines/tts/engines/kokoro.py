"""Kokoro 本地 TTS 引擎（82M v1.1-zh，24kHz）。

模型放置：models/tts/kokoro/Kokoro-82M-v1.1-zh/（config.json + kokoro-v1_1-zh.pth + voices/*.pt），
可在线下载或手动导入（registry 探测）。
推理懒加载单例；音色 = voices/<voice>.pt（zf_001/zf_003/zm_001…）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_SAMPLE_RATE = 24000


class KokoroEngine:
    """实现 TtsEngine 协议（duck typing）。"""

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._pipeline: Any | None = None
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "kokoro"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import numpy as np
        import soundfile as sf

        pipeline = self._ensure_pipeline()
        voice_name = voice or "zf_001"
        voice_pt = self._model_dir / "voices" / f"{voice_name}.pt"
        if not voice_pt.is_file():
            voice_pt = self._model_dir / "voices" / "zf_001.pt"

        chunks = []
        with self._lock:
            for _gs, _ps, audio in pipeline(text, voice=str(voice_pt)):
                chunks.append(np.asarray(audio))
        audio_np = np.concatenate(chunks)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), audio_np, _SAMPLE_RATE)
        return out_path

    def _ensure_pipeline(self) -> Any:
        from kokoro import KPipeline
        from kokoro.model import KModel

        if self._loaded:
            return self._pipeline
        with self._lock:
            if self._loaded:
                return self._pipeline
            config = self._model_dir / "config.json"
            weights = self._model_dir / "kokoro-v1_1-zh.pth"
            kmodel = KModel(config=str(config), model=str(weights))
            pipeline = KPipeline(lang_code="z", model=kmodel)
            self._pipeline = pipeline
            self._loaded = True
        return self._pipeline
