"""
KokoroBackend

Lightweight high-quality TTS option.
Models declared via central catalog (app/config/models.yaml) + uniform HF snapshot_download.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple, Any

import torch
import numpy as np
from loguru import logger

from app.services.tts.tts_backend import TTSBackend, register_backend


class KokoroBackend(TTSBackend):
    id = "kokoro"
    display_name = "Kokoro-82M (极轻量本地 · CPU友好)"
    required_model_repo = "hexgrad/Kokoro-82M-v1.1-zh"

    supports_voice_cloning = True
    supports_voice_design = False
    gpu_compat = ("cuda", "cpu")

    _pipeline = None  # lazy singleton
    _local_voices_dir: Optional[Path] = None  # 本地语音包目录

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        try:
            from app.services.model_manager import check_kokoro_model, get_model_by_repo_id

            model_present = check_kokoro_model()
            catalog_entry = get_model_by_repo_id("hexgrad/Kokoro-82M-v1.1-zh")

            if not model_present:
                return False, (
                    "Kokoro-82M 模型未下载。"
                    "请通过中央模型目录（models.yaml）使用统一 download_hf_model 下载。"
                )

            # Check runtime dependency
            try:
                from kokoro import KPipeline  # noqa: F401
            except ImportError:
                return False, "模型已就绪，但 kokoro 推理包未安装。请运行: pip install kokoro \"misaki[zh]\""

            return True, "ready (central catalog)"
        except Exception as e:
            return False, f"检查失败: {e}"

    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def supported_languages(self) -> list[str]:
        return ["zh", "en", "multi"]

    def _ensure_pipeline(self):
        """懒加载 KPipeline（首次调用时初始化，后续复用）。"""
        if self._pipeline is not None:
            return

        from kokoro import KPipeline

        # 设置本地模型路径
        try:
            from app.services.model_manager import _get_kokoro_cache_dir
            local_kokoro = _get_kokoro_cache_dir()
            if local_kokoro.exists() and any(local_kokoro.rglob("*.pth")):
                os.environ.setdefault("HF_HOME", str(local_kokoro.parent))
                # 缓存本地 voices 目录，后续 generate() 解析语音名用
                voices_dir = local_kokoro / "voices"
                if voices_dir.is_dir():
                    KokoroBackend._local_voices_dir = voices_dir
                logger.info(f"[KokoroBackend] Using local weights from {local_kokoro}")
        except Exception:
            pass

        self._pipeline = KPipeline(lang_code='z')  # z = 中文
        logger.info("[KokoroBackend] KPipeline initialized")

    def generate(
        self,
        text: str,
        *,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        instruct: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
        duration: Optional[float] = None,
        speed: float = 1.0,
        guidance_scale: float = 2.0,
        num_steps: int = 16,
        voice: Optional[str] = None,
        **extras: Any,
    ) -> torch.Tensor:
        """
        使用 Kokoro-82M 合成语音。
        返回 (1, n_samples) @ 24000Hz 的 torch.Tensor。
        """
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(f"Kokoro unavailable: {msg}")

        self._ensure_pipeline()

        safe_speed = max(0.5, min(2.0, float(speed)))
        voice_name = voice or ref_audio or "zf_001"  # 默认中文女声

        # 解析语音名 → 本地 .pt 路径（避免 KPipeline 去 HF 下载）
        if not voice_name.endswith('.pt') and self._local_voices_dir:
            local_pt = self._local_voices_dir / f"{voice_name}.pt"
            if local_pt.is_file():
                voice_name = str(local_pt)
                logger.debug(f"[KokoroBackend] Resolved voice to local: {local_pt}")

        # 如果有 ref_audio（声音克隆），Kokoro 的 KPipeline 支持直接传入
        lang_code = 'z'  # 中文
        if language and language.startswith('en'):
            lang_code = 'a'  # 英文

        try:
            generator = self._pipeline(
                text,
                voice=voice_name,
                speed=safe_speed,
            )

            pieces = []
            for _gs, _ps, audio in generator:
                if audio is not None and len(audio) > 0:
                    pieces.append(audio)

            if not pieces:
                raise RuntimeError("Kokoro 未生成有效音频")

            full_audio = np.concatenate(pieces)
            tensor = torch.from_numpy(full_audio.copy()).float().unsqueeze(0)

            logger.info(f"[KokoroBackend] Generated {tensor.shape[-1]} samples ({tensor.shape[-1]/24000:.2f}s)")
            return tensor

        except Exception as e:
            logger.error(f"[KokoroBackend] Synthesis failed: {e}")
            raise

    def unload(self) -> None:
        self._pipeline = None
        logger.info("[KokoroBackend] Pipeline unloaded")


register_backend(KokoroBackend)
