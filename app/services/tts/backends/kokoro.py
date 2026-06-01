"""
KokoroBackend

Lightweight high-quality TTS option.
Models declared via central catalog (app/config/models.yaml) + uniform HF snapshot_download.
"""

from __future__ import annotations

from typing import Optional, Tuple

import torch
from loguru import logger

from app.services.tts.tts_backend import TTSBackend, register_backend


class KokoroBackend(TTSBackend):
    id = "kokoro"
    display_name = "Kokoro-82M (极轻量本地 · CPU友好)"
    required_model_repo = "hexgrad/Kokoro-82M-v1.1-zh"

    supports_voice_cloning = True
    supports_voice_design = False
    gpu_compat = ("cuda", "cpu")

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        try:
            from app.services.model_manager import check_kokoro_model, get_model_by_repo_id

            model_present = check_kokoro_model()
            catalog_entry = get_model_by_repo_id("hexgrad/Kokoro-82M-v1.1-zh")

            if model_present:
                return True, "ready (central catalog)"
            else:
                return False, (
                    "Kokoro-82M 模型未下载。"
                    "请通过中央模型目录（models.yaml）使用统一 download_hf_model 下载。"
                )
        except Exception as e:
            return False, f"检查失败: {e}"

    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def supported_languages(self) -> list[str]:
        return ["zh", "en", "multi"]

    def generate(self, text: str, **kw) -> torch.Tensor:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(f"Kokoro unavailable: {msg}")
        raise NotImplementedError("Kokoro full implementation pending (will use catalog-declared model)")

    def unload(self) -> None:
        pass


register_backend(KokoroBackend)
