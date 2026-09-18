"""sherpa-onnx TTS 引擎（VITS melo-zh_en，44.1kHz，CPU RTF~0.69）。"""

from __future__ import annotations

import os
import struct
from pathlib import Path

_MODEL_FILE = "model.onnx"  # float32（int8 版 protobuf 解析失败不可用）


class SherpaTtsEngine:
    """sherpa-onnx VITS melo-zh_en 引擎：CPU 高音质中文配音。"""

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = str(model_dir)
        self._tts = None

    @property
    def name(self) -> str:
        return "sherpa_melo"

    @property
    def sample_rate(self) -> int:
        return self._tts.sample_rate if self._tts else 44100

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        import wave

        tts = self._ensure_tts()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        audio = tts.generate(text=text, sid=0)
        samples = audio.samples
        with wave.open(str(out_path), "w") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(tts.sample_rate)
            f.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, int(s * 32767)))) for s in samples))
        return out_path

    def _ensure_tts(self):
        if self._tts is None:
            import sherpa_onnx

            base = self._model_dir
            self._tts = sherpa_onnx.OfflineTts(
                sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=os.path.join(base, _MODEL_FILE),
                            lexicon=os.path.join(base, "lexicon.txt"),
                            tokens=os.path.join(base, "tokens.txt"),
                            dict_dir=os.path.join(base, "dict"),
                        ),
                    ),
                )
            )
        return self._tts
