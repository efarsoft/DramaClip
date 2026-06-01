"""
HuggingFace download progress adapter for DramaClip.

Strictly modeled after reference/OmniVoice-Studio/backend/utils/hf_progress.py

Purpose:
- Monkey-patch huggingface_hub's tqdm so every snapshot_download / hf_hub_download
  emits structured progress that can be consumed by the frontend via the existing
  IPC "progress.update" mechanism.
- Support context tagging with repo_id so frontend can route events correctly.
- Provide register_listener / emit for advanced use.
- Keep backward compatibility with existing progress_callback style.

Usage:
    from app.utils.hf_progress import install, register_listener, emit

    install()   # call once early (e.g. in backend_main or model_manager import)

    # When starting a catalog model download:
    from contextvars import ContextVar
    # (we use a simple module-level current_repo for simplicity in DramaClip)

    listener_id = register_listener(lambda ev: ...)
    download_hf_model("FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
    ...
"""

from __future__ import annotations

import contextvars
import itertools
import logging
import threading
from typing import Callable, Optional, Any

from loguru import logger

# Context variable to tag which repo is currently being downloaded.
# Set this around calls to download_hf_model so events get proper repo_id.
current_repo_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "dramaclip_hf_progress_repo_id", default=None
)

ProgressEvent = dict  # {repo_id, filename, downloaded, total, pct, phase, ...}
Listener = Callable[[ProgressEvent], None]

_listeners: dict[int, Listener] = {}
_listener_lock = threading.Lock()
_listener_counter = itertools.count(1)
_installed = False
_install_lock = threading.Lock()


def register_listener(cb: Listener) -> int:
    """Register a callback. Returns listener id for later unregister."""
    with _listener_lock:
        lid = next(_listener_counter)
        _listeners[lid] = cb
        return lid


def unregister_listener(lid: int) -> None:
    with _listener_lock:
        _listeners.pop(lid, None)


def _emit(event: ProgressEvent) -> None:
    """Fan-out to all listeners. Never let a bad listener kill a download."""
    rid = current_repo_id.get()
    if rid is not None and "repo_id" not in event:
        event = {**event, "repo_id": rid}

    with _listener_lock:
        listeners = list(_listeners.values())

    for cb in listeners:
        try:
            cb(event)
        except Exception as e:
            logger.debug(f"hf_progress listener error (non-fatal): {e}")


def emit(event: ProgressEvent) -> None:
    """Public emit for manual lifecycle events (start, error, done, etc.)."""
    _emit(event)


class _DramaClipTqdm:
    """
    Minimal tqdm replacement that forwards progress to our listener system
    instead of (or in addition to) printing bars.
    """

    def __init__(self, *args, **kwargs):
        self.total = kwargs.get("total")
        self.n = 0
        self.desc = kwargs.get("desc", "")
        self._last_pct = 0.0

    def update(self, n: int = 1):
        self.n += n
        if self.total and self.total > 0:
            pct = min(self.n / self.total, 1.0)
        else:
            pct = 0.0

        # Throttle a bit
        if abs(pct - self._last_pct) > 0.01 or pct >= 1.0:
            self._last_pct = pct
            _emit({
                "filename": self.desc or "unknown",
                "downloaded": self.n,
                "total": self.total,
                "pct": pct,
                "phase": "progress",
            })

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass

    def set_description(self, desc: str, refresh=True):
        self.desc = desc


def install() -> None:
    """
    Monkey-patch huggingface_hub to use our progress system.
    Safe to call multiple times.
    """
    global _installed
    with _install_lock:
        if _installed:
            return

        try:
            import huggingface_hub.utils.tqdm as hf_tqdm_module
            original_tqdm = hf_tqdm_module.tqdm

            # Replace the class used internally by hf_hub_download / snapshot_download
            hf_tqdm_module.tqdm = _DramaClipTqdm   # type: ignore

            # Also patch the submodule if accessed differently
            try:
                import huggingface_hub.utils as hf_utils
                hf_utils.tqdm = _DramaClipTqdm     # type: ignore
            except Exception:
                pass

            _installed = True
            logger.info("[hf_progress] huggingface_hub tqdm patched for DramaClip progress system")
        except Exception as e:
            logger.warning(f"[hf_progress] Failed to patch huggingface_hub tqdm: {e}")
            # Still mark as installed so we don't spam warnings
            _installed = True


def ensure_installed():
    """Idempotent helper – call this before any HF download."""
    if not _installed:
        install()


# Convenience: a listener that feeds directly into DramaClip's IPC progress system
def create_ipc_progress_listener(task_id_prefix: str = "model"):
    """
    Returns a listener function you can register.
    It will translate HF events into the standard send_progress calls.
    """
    from app.ipc.handlers.base import send_progress

    def listener(ev: ProgressEvent):
        repo = ev.get("repo_id") or "unknown"
        task_id = f"{task_id_prefix}:{repo}"

        pct = int(ev.get("pct", 0) * 100) if ev.get("pct") is not None else 0
        phase = ev.get("phase", "download")
        filename = ev.get("filename", "")

        msg = f"{filename}" if filename else "Downloading..."
        if phase == "done":
            msg = "Download complete"

        detail = {
            "downloaded": ev.get("downloaded"),
            "total": ev.get("total"),
            "filename": filename,
        }

        send_progress(
            task_id=task_id,
            progress=pct,
            message=msg,
            phase=phase,
            # Note: the server.send_progress in this version accepts detail via the notification
        )

        # Also send a richer notification if needed (frontend can listen to progress.update)
        # For now we rely on the existing progress.update channel with detail.

    return listener
