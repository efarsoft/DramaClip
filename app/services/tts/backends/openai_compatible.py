"""
OpenAICompatibleTTSBackend — any provider implementing OpenAI /v1/audio/speech.

Strict TTSBackend protocol (returns torch.Tensor).
Writes voice_file as side-effect (for DramaClip legacy pipeline) then returns
the audio tensor. Supports "instructions" via future model param for emotion.
"""

from __future__ import annotations

from typing import Optional, Tuple

import torch
from loguru import logger

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

from app.services.tts.tts_backend import TTSBackend, register_backend
from app.config.unified_config import get_config


class OpenAICompatibleTTSBackend(TTSBackend):
    id = "openai_tts"
    display_name = "OpenAI Compatible (云端高质量)"

    supports_voice_cloning = False
    supports_voice_design = False
    gpu_compat = ("cloud",)

    def __init__(self):
        self._client: Optional[OpenAI] = None

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        if OpenAI is None:
            return False, "openai package not installed (pip install openai)"

        config = get_config()
        tts_openai = config.get("tts", {}).get("openai", {}) or {}
        openai_protocol = config.get("openai_protocol", {}) or {}

        api_key = tts_openai.get("api_key") or openai_protocol.get("api_key")
        if not api_key:
            return False, "No API key configured (tts.openai.api_key or openai_protocol.api_key)"

        return True, "ready"

    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def supported_languages(self) -> list[str]:
        return ["multi"]

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client

        config = get_config()
        tts_openai = config.get("tts", {}).get("openai", {}) or {}
        openai_protocol = config.get("openai_protocol", {}) or {}

        api_key = tts_openai.get("api_key") or openai_protocol.get("api_key")
        base_url = tts_openai.get("base_url") or openai_protocol.get("base_url") or "https://api.openai.com/v1"

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        return self._client

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
        # DramaClip compat
        voice_name: Optional[str] = None,
        voice_file: Optional[str] = None,
        voice_rate: Optional[float] = None,
        model: str = "tts-1-hd",
        **extras,
    ) -> torch.Tensor:
        if not text or not text.strip():
            logger.warning("Empty text passed to OpenAICompatibleTTSBackend")
            return torch.zeros(1, 24000)

        vfile = voice_file or "temp_openai_tts.wav"
        vname = voice_name or "alloy"

        try:
            client = self._get_client()

            # Some providers support "instructions" for prosody/emotion.
            # We pass it via extra_body if the SDK supports it; otherwise ignore gracefully.
            kwargs: dict = {"model": model, "voice": vname, "input": text, "response_format": "wav"}
            if instruct:
                # Many Chinese OpenAI-compat providers accept "instructions"
                kwargs["extra_body"] = {"instructions": instruct}

            response = client.audio.speech.create(**kwargs)
            response.stream_to_file(vfile)

            # Load as tensor (real duration will be measured by caller too)
            import soundfile as sf
            data, sr = sf.read(vfile)
            if data.ndim > 1:
                data = data.mean(axis=1)
            wav = torch.from_numpy(data).float().unsqueeze(0)
            logger.info(f"OpenAI-compatible TTS success: {vfile}")
            return wav

        except Exception as e:
            logger.error(f"OpenAI-compatible TTS failed: {e}")
            return torch.zeros(1, 24000)


register_backend(OpenAICompatibleTTSBackend)
