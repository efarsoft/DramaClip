"""
TTS Backend Registry — authoritative implementation (strictly following OmniVoice-Studio)

This module owns:
- _LazyRegistry (deferred import for heavy local models like CosyVoice per OmniVoice-Studio reference)
- _REGISTRY (active resolved classes)
- _INSTALL_HINTS (user-actionable guidance per engine)
- _LAST_ERRORS (ENGINE-06 cache for Settings UI)
- list_backends() / list_available_backends()  → rich metadata for frontend
- get_active_tts_backend() (respects config.tts.engine, local-first priority)
- register_* helpers (called at import time by backends/*.py)

Local priority order (DramaClip 2026):
1. cosyvoice (Fun-CosyVoice3-0.5B-2512) — best Chinese short-drama quality
2. kokoro (82M) — ultra-light, fast, good for CPU
3. edge_tts — stable free cloud fallback
4. openai_tts — high-quality cloud when key configured
"""

from __future__ import annotations

import importlib
from typing import Dict, Optional, Any

from loguru import logger

from .tts_backend import TTSBackend, _mask_hf_tokens


# ── Internal storage (module private) ───────────────────────────────────────

_REGISTRY: dict[str, type[TTSBackend]] = {}
_LAZY_REGISTRY: dict[str, tuple[str, str]] = {}   # backend_id -> (module_path, class_name)
_LAST_ERRORS: dict[str, str] = {}


class _LazyRegistry(dict):
    """
    Dict subclass that resolves heavy backends via deferred import on first access.

    Exact semantics from OmniVoice-Studio:
    - Keys in _LAZY_REGISTRY are invisible until touched.
    - __getitem__ / __contains__ / iteration trigger resolution lazily.
    - Once resolved, the class is cached in the normal dict for speed.
    - list_backends() stays cheap because iteration yields lazy keys without forcing import
      until the caller actually does self[k].
    """

    def __contains__(self, key: str) -> bool:
        return dict.__contains__(self, key) or key in _LAZY_REGISTRY

    def __getitem__(self, key: str):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if key in _LAZY_REGISTRY:
            mod_path, attr = _LAZY_REGISTRY[key]
            cls = getattr(importlib.import_module(mod_path), attr)
            self[key] = cls
            return cls
        raise KeyError(key)

    def __iter__(self):
        seen: set[str] = set()
        for k in dict.__iter__(self):
            seen.add(k)
            yield k
        for k in _LAZY_REGISTRY:
            if k not in seen:
                yield k

    def items(self):
        for k in self:
            yield k, self[k]

    def keys(self):
        return list(iter(self))

    def values(self):
        return [self[k] for k in self]


# The live registry (populated by register_* + lazy resolution)
_REGISTRY = _LazyRegistry(_REGISTRY)  # wrap the plain dict we created above


# ── INSTALL HINTS (P0 for user experience — local first) ────────────────────

_INSTALL_HINTS: dict[str, str] = {
    "cosyvoice": (
        "本地高质量首选（Fun-CosyVoice3-0.5B-2512）。"
        "在设置 → 模型管理 中一键下载，或运行: python -c \"from app.services.model_manager import download_cosyvoice2_model; download_cosyvoice2_model()\""
    ),
    "cosyvoice_subprocess": (
        "【推荐 - 进程隔离版】最高质量 CosyVoice 3。"
        "可彻底解决依赖冲突。模型管理中会出现“一键安装运行时”按钮，自动创建独立 venv 并安装。"
        "安装完成后此引擎会变为可用。"
    ),
    "kokoro": (
        "极轻量本地引擎 (82M)。适合低配CPU/GPU。"
        "模型管理中下载，或: huggingface-cli download hexgrad/Kokoro-82M --local-dir pretrained_models/Kokoro-82M"
    ),
    "edge_tts": "内置（edge-tts 包），始终可用。免费云端备用引擎。",
    "openai_tts": (
        "OpenAI 兼容协议云端TTS。需在 设置 → AI服务 配置 openai_protocol.api_key "
        "或 tts.openai.api_key。支持 Groq、Fireworks、硅基流动等任何 /v1/audio/speech 端点。"
    ),
    "cosyvoice2_local": "历史别名，已自动映射到标准 'cosyvoice'（参考 OmniVoice-Studio 命名）。请在设置中改用 'cosyvoice'。",
    "indextts2": "IndexTTS2 需要独立安装（git clone + uv pip）。详情见后续文档。",
}


def register_backend(backend_class: type[TTSBackend]) -> None:
    """Register a concrete backend class (called from backends/*.py at import)."""
    if not issubclass(backend_class, TTSBackend):
        raise TypeError(f"{backend_class} must subclass TTSBackend")
    _REGISTRY[backend_class.id] = backend_class
    logger.debug(f"[TTS] Registered backend: {backend_class.id}")


def register_lazy_backend(backend_id: str, module_path: str, class_name: str) -> None:
    """
    Register a heavy backend for lazy loading (CosyVoice3, future GPT-SoVITS etc.).
    The actual class is imported only on first get_backend_class() or list iteration touch.
    """
    _LAZY_REGISTRY[backend_id] = (module_path, class_name)
    logger.debug(f"[TTS] Registered lazy backend: {backend_id} -> {module_path}.{class_name}")


def get_backend_class(backend_id: str) -> type[TTSBackend]:
    """Resolve (possibly lazy) backend class. Raises ValueError if unknown."""
    if backend_id not in _REGISTRY:
        raise ValueError(f"Unknown TTS backend: {backend_id!r}. Known: {list(_REGISTRY)}")
    return _REGISTRY[backend_id]


def get_active_tts_backend(backend_id: Optional[str] = None) -> TTSBackend:
    """
    Instantiate the configured engine.

    Resolution order:
      1. explicit backend_id param
      2. config.tts.engine (unified_config)
      3. "edge_tts" (stable local-friendly default during Phase 1 transition)
    """
    from app.config.unified_config import get_config

    if backend_id is None:
        cfg = get_config()
        tts_cfg = cfg.get("tts", {}) if isinstance(cfg, dict) else {}
        backend_id = tts_cfg.get("engine") if isinstance(tts_cfg, dict) else None

    if not backend_id:
        backend_id = "edge_tts"  # safe local-friendly default during Phase 1

    cls = get_backend_class(backend_id)
    # Future: some backends (OmniVoice style) accept model= for reuse
    return cls()


def list_backends() -> list[dict]:
    """
    Full rich list for UI / diagnostics. Exact shape from OmniVoice-Studio (ENGINE-05/06).

    Each entry:
    {
      "id", "display_name", "available", "reason", "install_hint",
      "last_error", "isolation_mode", "gpu_compat",
      "supports_voice_cloning", "supports_voice_design"
    }
    """
    out: list[dict] = []
    for bid, cls in _REGISTRY.items():
        try:
            ok, msg = cls.is_available()
        except Exception as exc:
            ok = False
            msg = f"{type(exc).__name__}: {exc}"
            logger.warning(f"[TTS] {bid}.is_available() raised — graceful degrade: {msg}")

        if ok:
            _LAST_ERRORS.pop(bid, None)
        else:
            _LAST_ERRORS[bid] = _mask_hf_tokens(msg)

        isolation = "subprocess" if getattr(cls, "_is_subprocess_isolated", False) else "in-process"

        # 增强：自动从 backend 类声明的 required_model_repo + 中央 catalog 获取状态
        required_models = []
        try:
            from app.services.model_manager import get_model_by_repo_id, load_model_catalog
            repo = getattr(cls, "required_model_repo", None)
            if repo:
                info = get_model_by_repo_id(repo)
                # 通用安装检测（优先用 catalog 里的信息）
                installed = False
                try:
                    # 简单启发式：如果本地有对应目录或 HF cache 有记录
                    from huggingface_hub import scan_cache_dir
                    hf_info = scan_cache_dir()
                    for entry in hf_info.repos:
                        if entry.repo_id == repo and entry.size_on_disk > 0:
                            installed = True
                            break
                except Exception:
                    pass

                required_models.append({
                    "repo_id": repo,
                    "installed": installed,
                    "label": info.get("label") if info else repo,
                })
        except Exception:
            pass

        out.append({
            "id": bid,
            "display_name": getattr(cls, "display_name", bid),
            "available": bool(ok),
            "reason": None if ok else _mask_hf_tokens(msg),
            "install_hint": _INSTALL_HINTS.get(bid),
            "last_error": _LAST_ERRORS.get(bid),
            "isolation_mode": isolation,
            "gpu_compat": list(getattr(cls, "gpu_compat", ("cpu",))),
            "supports_voice_cloning": getattr(cls, "supports_voice_cloning", False),
            "supports_voice_design": getattr(cls, "supports_voice_design", False),
            "sample_rate": getattr(cls, "sample_rate", None),
            "required_models": required_models,   # 新增：模型需求 + 状态
        })
    return out


# Back-compat alias used by system_handler.py and early callers
list_available_backends = list_backends


# ---------------------------------------------------------------------------
# Quality-first helpers (integrated with central model catalog)
# ---------------------------------------------------------------------------

def get_high_quality_tts_recommendations() -> list[dict]:
    """
    返回当前已知的高质量 TTS 选项（从中央 models.yaml 拉取）。
    不硬锁定任何单一模型为默认，质量优先，由用户/实际输出测试决定。
    """
    from app.services.model_manager import load_model_catalog

    catalog = load_model_catalog()
    tts_models = [m for m in catalog if m.get("role") == "TTS"]

    # 简单按是否有 quality_notes 排序（参考项目风格的推荐）
    tts_models.sort(key=lambda x: 0 if x.get("quality_notes") else 1)

    return [
        {
            "repo_id": m["repo_id"],
            "label": m["label"],
            "note": m.get("note") or m.get("quality_notes"),
            "size_gb": m.get("size_gb"),
        }
        for m in tts_models
    ]
