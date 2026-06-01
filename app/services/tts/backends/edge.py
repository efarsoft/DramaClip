"""
EdgeTTSBackend — stable free cloud fallback (Azure Edge V1).

Implements the strict TTSBackend protocol (returns torch.Tensor).
Internally reuses the proven azure_tts_v1 (writes voice_file + SubMaker side-effects)
then loads the produced WAV as tensor so the new registry path stays compatible
with DramaClip's downstream ducking/SRT pipeline.
"""

from __future__ import annotations

from typing import Optional, Tuple

import torch
from loguru import logger

from app.services.tts.tts_backend import TTSBackend, register_backend
from app.services.tts.voice import azure_tts_v1


class EdgeTTSBackend(TTSBackend):
    id = "edge_tts"
    display_name = "Edge TTS (免费云端备用 - 最稳定)"

    supports_voice_cloning = False
    supports_voice_design = False
    gpu_compat = ("cloud",)

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
            return True, "ready"
        except ImportError:
            return False, "edge_tts package not installed (pip install edge_tts)"

    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def supported_languages(self) -> list[str]:
        return ["multi"]

    def generate(
        self,
        text: str,
        *,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        instruct: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        guidance_scale: float = 2.0,
        num_steps: int = 16,
        # DramaClip legacy compat kwargs (voice.py still passes these)
        voice_name: Optional[str] = None,
        voice_file: Optional[str] = None,
        voice_rate: Optional[float] = None,
        voice_pitch: Optional[float] = None,
        **extras,
    ) -> torch.Tensor:
        """
        Returns tensor after delegating to legacy azure_tts_v1 (which writes voice_file).
        Upper layer (voice.py) will also build SubMaker from the file we wrote.
        """
        vname = voice_name or "zh-CN-XiaoxiaoNeural"
        vfile = voice_file or "temp_edge_tts.wav"
        vrate = voice_rate if voice_rate is not None else speed
        vpitch = voice_pitch if voice_pitch is not None else 1.0

        try:
            sub = azure_tts_v1(
                text=text,
                voice_name=vname,
                voice_rate=vrate,
                voice_pitch=vpitch,
                voice_file=vfile,
            )
            if sub is None:
                raise RuntimeError("azure_tts_v1 returned None")

            # Load the WAV we just wrote as tensor (1, n_samples) @ 24k
            import soundfile as sf
            data, sr = sf.read(vfile)
            if data.ndim > 1:
                data = data.mean(axis=1)  # mono
            wav = torch.from_numpy(data).float().unsqueeze(0)
            return wav

        except Exception as e:
            logger.error(f"EdgeTTSBackend.generate failed: {e}")
            # Return 1s silent tensor so caller doesn't crash
            return torch.zeros(1, 24000)


register_backend(EdgeTTSBackend)
