"""
CosyVoiceBackend — standardized naming aligned with OmniVoice-Studio reference.

In the reference project (backend/services/tts_backend.py):
    class CosyVoiceBackend(TTSBackend):
        id = "cosyvoice"
        display_name = "CosyVoice 3 (9 langs, zero-shot, instruct, Apache-2.0)"

We adopt the exact same clean, family-level naming for the registry:
- id = "cosyvoice" (short, stable, no version suffix in the key)
- Class = CosyVoiceBackend

The concrete model we target in DramaClip is FunAudioLLM/Fun-CosyVoice3-0.5B-2512.
Version and capability details live only in display_name and install hints (standard practice).

This keeps the TTS registry IDs consistent with the reference (cosyvoice, kokoro, etc.).
Legacy engine names (cosyvoice2_local, cosyvoice2, etc.) are mapped in voice.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import torch
from loguru import logger

from app.services.tts.tts_backend import TTSBackend, register_backend


class CosyVoiceBackend(TTSBackend):
    id = "cosyvoice"
    display_name = "CosyVoice 3 (Fun-CosyVoice3-0.5B-2512) — 短剧中文音质首选"
    required_model_repo = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

    supports_voice_cloning = True
    supports_voice_design = True
    supports_instruct = True
    gpu_compat = ("cuda", "mps", "cpu")

    # CosyVoice language tags for cross-lingual synthesis (reference-aligned).
    LANG_TAGS = {
        "zh": "<|zh|>", "en": "<|en|>", "ja": "<|ja|>",
        "ko": "<|ko|>", "yue": "<|yue|>", "de": "<|de|>",
        "es": "<|es|>", "fr": "<|fr|>", "it": "<|it|>",
        "ru": "<|ru|>",
    }

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        try:
            from app.services.model_manager import check_cosyvoice2_model, load_model_catalog, get_model_by_repo_id

            # Use central catalog (reference-aligned)
            catalog_entry = get_model_by_repo_id("FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
            model_present = check_cosyvoice2_model()

            if model_present:
                try:
                    from cosyvoice.cli.cosyvoice import CosyVoice, AutoModel  # noqa: F401
                    return True, "ready (model in central catalog)"
                except ImportError:
                    return False, (
                        "模型已在中央目录就绪，但 'cosyvoice' 推理包未安装。"
                        "参考 OmniVoice-Studio: git clone --recursive FunAudioLLM/CosyVoice + pip install -r requirements.txt (+ SoX on some systems)。"
                    )
            else:
                return False, (
                    "Fun-CosyVoice3-0.5B-2512 未下载。"
                    "使用统一 HF 下载（huggingface_hub.snapshot_download）: "
                    "Settings → 模型管理 或调用 model_manager.download_hf_model('FunAudioLLM/Fun-CosyVoice3-0.5B-2512')"
                )
        except Exception as e:
            return False, f"检查失败: {e}"

    def __init__(self):
        self._model = None
        self._sample_rate = 22050  # Fun-CosyVoice3 当前集成默认采样率

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def supported_languages(self) -> list[str]:
        return list(self.LANG_TAGS.keys())

    def _ensure_loaded(self):
        if self._model is not None:
            return

        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(f"CosyVoice unavailable: {msg}")

        import os
        from pathlib import Path

        # Use unified resolve_model_path (reference-aligned: OmniVoice-Studio)
        from app.services.model_manager import resolve_model_path
        model_path = resolve_model_path("FunAudioLLM/Fun-CosyVoice3-0.5B-2512")

        if model_path is None:
            raise FileNotFoundError(
                "CosyVoice 模型未找到。请通过以下方式下载:\n"
                "  1. Settings → 模型管理 → 下载 Fun-CosyVoice3\n"
                "  2. 或调用 model_manager.download_hf_model('FunAudioLLM/Fun-CosyVoice3-0.5B-2512')\n"
                "搜索路径: pretrained_models/<repo>, ~/.cache/huggingface/hub/"
            )

        model_dir = str(model_path)
        assert Path(model_dir).is_absolute(), f"Model path must be absolute: {model_dir}"

        # 兼容官方加载器
        yaml3 = Path(model_dir) / "cosyvoice3.yaml"
        yaml_std = Path(model_dir) / "cosyvoice.yaml"
        if yaml3.exists() and not yaml_std.exists():
            import shutil
            shutil.copy(yaml3, yaml_std)
            logger.info("已自动创建 cosyvoice.yaml 以兼容官方 CosyVoice 加载器")

        try:
            from cosyvoice.cli.cosyvoice import AutoModel
            self._model = AutoModel(model_dir=model_dir)
            if hasattr(self._model, "sample_rate"):
                self._sample_rate = self._model.sample_rate
            logger.info(f"CosyVoiceBackend 使用 AutoModel 加载成功: {model_dir}")
        except Exception:
            from cosyvoice.cli.cosyvoice import CosyVoice
            self._model = CosyVoice(model_dir)
            logger.info(f"CosyVoiceBackend 使用 CosyVoice 类加载成功: {model_dir}")

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
        **extras,
    ) -> torch.Tensor:
        """
        CosyVoice 4-way inference (reference-aligned):

        1. instruct + ref_audio → inference_instruct2  (emotion / dialect control)
        2. ref_audio + ref_text → inference_zero_shot   (voice cloning)
        3. ref_audio only       → inference_cross_lingual (cross-lingual + lang tag)
        4. nothing              → inference_sft          (built-in speaker)
        """
        import numpy as np

        self._ensure_loaded()

        safe_speed = float(max(0.5, min(2.0, speed)))

        # ── 4-way inference routing ──────────────────────────────────────
        if instruct and ref_audio:
            # Instruct mode: e.g. "用四川话说<|endofprompt|>"
            if not instruct.endswith("<|endofprompt|>"):
                instruct = f"{instruct}<|endofprompt|>"
            logger.info("CosyVoice → inference_instruct2 (instruct + ref_audio)")
            results = self._model.inference_instruct2(
                text, instruct, ref_audio, stream=False,
            )
        elif ref_audio and ref_text:
            logger.info("CosyVoice → inference_zero_shot (voice cloning)")
            results = self._model.inference_zero_shot(
                text, ref_text, ref_audio, stream=False,
            )
        elif ref_audio:
            # Cross-lingual: prefix text with language tag if available.
            lang_tag = ""
            if language:
                full_lang = language.lower()
                lang_key = full_lang[:2] if len(full_lang) > 2 else full_lang
                lang_tag = self.LANG_TAGS.get(full_lang) or self.LANG_TAGS.get(lang_key, "")
            logger.info(f"CosyVoice → inference_cross_lingual (lang_tag={lang_tag!r})")
            results = self._model.inference_cross_lingual(
                f"{lang_tag}{text}", ref_audio, stream=False,
            )
        else:
            # No ref audio — SFT with first available speaker.
            spks = self._model.list_available_spks()
            spk = spks[0] if spks else "中文女"
            logger.info(f"CosyVoice → inference_sft (speaker={spk})")
            results = self._model.inference_sft(text, spk, stream=False)

        # ── collect audio chunks ─────────────────────────────────────────
        pieces = []
        for chunk in results:
            wav = chunk.get("tts_speech")
            if wav is None:
                continue
            if isinstance(wav, np.ndarray):
                wav = torch.from_numpy(wav).float()
            if not isinstance(wav, torch.Tensor):
                wav = torch.tensor(wav, dtype=torch.float32)
            pieces.append(wav)

        if not pieces:
            raise RuntimeError("CosyVoiceBackend 未能生成任何音频")

        wav = torch.cat(pieces, dim=-1)
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)

        return wav

    def unload(self) -> None:
        self._model = None
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


register_backend(CosyVoiceBackend)
