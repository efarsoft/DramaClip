"""
TTS Backend Abstraction — Strictly modeled after OmniVoice-Studio (debpalash/OmniVoice-Studio)

Every TTS engine (local CosyVoice3, Kokoro, KittenTTS, cloud OpenAI-compatible, Edge, etc.)
must implement this narrow, clean protocol.

Design goals (matching OmniVoice-Studio):
- is_available() returns rich (bool, str) install hints so UI can guide users without crashes.
- generate() returns raw torch.Tensor (1, n_samples) @ sample_rate — upper layers (voice.py)
  are responsible for writing to disk + building SubMaker timing for DramaClip pipeline.
- supports_voice_design + description param for text-to-voice (no ref_audio).
- unload() for VRAM hygiene when switching engines in Settings.
- Lazy registration for heavy local models (CosyVoice3, future IndexTTS2, etc.).

This replaces the previous 2000+ line if-elif hell in voice.py.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any, List, Dict

import torch
from loguru import logger


# ── HF token leak mitigation (copied from OmniVoice-Studio for safety) ─────
_HF_TOKEN_MASK_RE = re.compile(r"hf_[A-Za-z0-9]{30,}")
_HF_TOKEN_MASK = "hf_***REDACTED***"


def _mask_hf_tokens(value: Any) -> Any:
    """Redact HF tokens from error/install messages before they reach UI/logs."""
    if not isinstance(value, str):
        return value
    return _HF_TOKEN_MASK_RE.sub(_HF_TOKEN_MASK, value)


class TTSBackend(ABC):
    """
    Abstract Base Class for all TTS engines in DramaClip.

    Strictly aligned with reference/OmniVoice-Studio/backend/services/tts_backend.py
    (as of 2026 research). Local-first priority: CosyVoice family (id="cosyvoice", standardized per OmniVoice-Studio reference),
    Kokoro-82M, future GPT-SoVITS / IndexTTS2 etc. are first-class citizens.
    """

    # --- Identity (must be overridden by subclasses) ---
    id: str = "base"
    display_name: str = "Base TTS Engine"

    # --- Capabilities (surfaced in Settings UI Engine Matrix) ---
    supports_voice_cloning: bool = False   # ref_audio + ref_text
    supports_voice_design: bool = False    # description-only voice creation (no audio ref)
    supports_instruct: bool = False        # natural language emotion control

    # Hardware targets — used for recommendations and warnings in UI
    gpu_compat: tuple[str, ...] = ("cpu",)   # "cuda", "mps", "rocm", "cpu", "cloud"

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Output sample rate in Hz (e.g. 24000 for most CosyVoice, 22050/24000 for Kokoro)."""
        ...

    @property
    @abstractmethod
    def supported_languages(self) -> list[str]:
        """ISO codes or ["multi"] for broad zero-shot support."""
        ...

    @classmethod
    @abstractmethod
    def is_available(cls) -> Tuple[bool, str]:
        """
        Fast environment check. MUST NOT load heavy models.

        Returns:
            (available: bool, message: str)
            - If False, message MUST be a user-actionable install hint
              (e.g. "pip install ...", "download model via Settings → Model Manager",
               "Fun-CosyVoice3-0.5B-2512 (cosyvoice backend) requires CUDA 12.1+ or Apple MPS").
            - Never raise — callers rely on graceful degradation.
        """
        ...

    @abstractmethod
    def generate(
        self,
        text: str,
        *,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        instruct: Optional[str] = None,
        description: Optional[str] = None,   # Voice design: "young female, warm, slight Beijing accent"
        language: Optional[str] = None,
        duration: Optional[float] = None,
        speed: float = 1.0,
        guidance_scale: float = 2.0,
        num_steps: int = 16,
        **extras: Any,
    ) -> torch.Tensor:
        """
        Synthesize speech.

        Returns:
            torch.Tensor of shape (1, n_samples) at self.sample_rate.
            Caller (voice.py) is responsible for:
              1. Saving to the requested voice_file path (using torchaudio/soundfile)
              2. Measuring exact duration (ffprobe or soundfile)
              3. Constructing SubMaker for downstream ducking / alignment / SRT

        Voice Design mode:
            When description is provided AND ref_audio is None, engines that set
            supports_voice_design=True will synthesize a voice matching the description.
        """
        ...

    def unload(self) -> None:
        """
        Release GPU memory / file handles / model weights.

        Idempotent. Called by registry on engine switch and app shutdown.
        Default is no-op so legacy adapters keep working during Phase 1 transition.
        Pure local engines (Phase 2+) MUST override and call torch.cuda.empty_cache() etc.
        """
        return None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"

    # 可选：子类可声明自己依赖的中央 catalog 模型（repo_id）
    required_model_repo: Optional[str] = None


# Re-exports for backward compatibility during Phase 1 transition.
# Backends may still do: from app.services.tts.tts_backend import ... register_backend
from .registry import (
    register_backend,
    register_lazy_backend,
    get_backend_class,
    get_active_tts_backend,
    list_backends,
    list_available_backends,
    _INSTALL_HINTS,
)

__all__ = [
    "TTSBackend",
    "register_backend",
    "register_lazy_backend",
    "get_backend_class",
    "get_active_tts_backend",
    "list_backends",
    "list_available_backends",
    "_mask_hf_tokens",
]
