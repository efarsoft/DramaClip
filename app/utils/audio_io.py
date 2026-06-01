"""Safe audio write helpers — closes silent-corruption risk.

Reference-aligned with OmniVoice-Studio ``backend/services/audio_io.py``.

All audio-write call sites should converge on the helpers in this module:

* ``_safe_torchaudio_save`` — wraps ``torchaudio.save``. 4-layer defence:
    1. CUDA / MPS tensor → CPU
    2. Non-float32 dtype → float32
    3. Out-of-range values → clamp(-1.0, 1.0)
    4. Non-contiguous tensor → contiguous()
  Plus explicit ``encoding`` + ``bits_per_sample`` to prevent backend drift.

* ``_safe_soundfile_write`` — numpy / soundfile variant with the same
  sanity checks (dtype / contiguity / shape / range).

* ``atomic_save_wav`` — writes to a sibling temp file then
  ``os.replace()`` into place so the target either holds a complete WAV
  or its previous contents — never a truncated one.
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import Any, BinaryIO, Union

import numpy as np
import torch
from loguru import logger

PathOrBuf = Union[str, "os.PathLike[str]", BinaryIO, io.IOBase]


def _safe_torchaudio_save(
    path_or_buf: PathOrBuf,
    tensor: torch.Tensor,
    sample_rate: int,
    *,
    format: str = "wav",
    bits_per_sample: int = 16,
) -> None:
    """Audited ``torchaudio.save`` wrapper with 4-layer defence.

    Raises:
        ValueError: if the tensor is empty.
        TypeError: if *tensor* is not a ``torch.Tensor``.
    """
    import torchaudio

    if not torch.is_tensor(tensor):
        raise TypeError(
            f"_safe_torchaudio_save expects torch.Tensor, got {type(tensor).__name__}"
        )
    if tensor.numel() == 0:
        raise ValueError(
            "_safe_torchaudio_save refuses to write an empty audio tensor"
        )

    # 1. CUDA / MPS → CPU
    if tensor.device.type != "cpu":
        tensor = tensor.cpu()

    # 2. dtype → float32
    if tensor.dtype != torch.float32:
        tensor = tensor.to(torch.float32)

    # 3. Range clamp
    tensor = tensor.clamp(-1.0, 1.0)

    # Normalize shape to (channels, samples)
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0)
    elif tensor.ndim != 2:
        raise ValueError(
            f"Expected 1D or 2D tensor, got shape {tuple(tensor.shape)}"
        )

    # 4. Contiguous
    if not tensor.is_contiguous():
        tensor = tensor.contiguous()

    encoding = "PCM_F" if bits_per_sample == 32 else "PCM_S"
    fmt = (format or "wav").lower()

    try:
        if fmt == "wav":
            torchaudio.save(
                path_or_buf, tensor, sample_rate,
                format=fmt, encoding=encoding, bits_per_sample=bits_per_sample,
            )
        else:
            try:
                torchaudio.save(
                    path_or_buf, tensor, sample_rate,
                    format=fmt, encoding=encoding, bits_per_sample=bits_per_sample,
                )
            except (TypeError, RuntimeError, ValueError) as e:
                if hasattr(path_or_buf, "seek") and hasattr(path_or_buf, "truncate"):
                    try:
                        path_or_buf.seek(0)
                        path_or_buf.truncate(0)
                    except (OSError, io.UnsupportedOperation):
                        pass
                logger.debug(f"torchaudio.save(format={fmt}) rejected encoding kwargs ({e}), retrying without")
                torchaudio.save(path_or_buf, tensor, sample_rate, format=fmt)
    except Exception:
        raise


def _safe_soundfile_write(
    path: PathOrBuf,
    samples: np.ndarray,
    sample_rate: int,
    *,
    subtype: str = "PCM_16",
) -> None:
    """Audited ``soundfile.write`` wrapper with the same sanity checks.

    Args:
        path: Filesystem path or file-like object.
        samples: 1D ``(samples,)`` or 2D ``(samples, channels)`` numpy array.
        sample_rate: WAV sample rate in Hz.
        subtype: Soundfile subtype (``PCM_16``, ``PCM_24``, ``FLOAT``, etc.).

    Raises:
        ValueError: if the array is empty.
    """
    import soundfile as sf

    if not isinstance(samples, np.ndarray):
        samples = np.asarray(samples)

    if samples.size == 0:
        raise ValueError(
            "_safe_soundfile_write refuses to write an empty array"
        )

    # Coerce to soundfile-friendly dtype
    if samples.dtype not in (np.float32, np.float64, np.int16, np.int32):
        samples = samples.astype(np.float32)

    # Range protection for float inputs
    if samples.dtype in (np.float32, np.float64):
        samples = np.ascontiguousarray(samples)
        np.clip(samples, -1.0, 1.0, out=samples)
    else:
        samples = np.ascontiguousarray(samples)

    sf.write(path, samples, sample_rate, subtype=subtype)


def atomic_save_wav(
    target_path: str,
    audio: torch.Tensor,
    sample_rate: int,
    **kwargs: Any,
) -> None:
    """Write a WAV to *target_path* atomically.

    Writes to a sibling temp file in the same directory, then
    ``os.replace()`` into place. Delegates the encode to
    ``_safe_torchaudio_save`` so atomicity and correctness compose.

    Args:
        target_path: Final destination. Parent directory must exist.
        audio: ``(channels, samples)`` or ``(samples,)`` tensor.
        sample_rate: WAV sample rate in Hz.
        **kwargs: Forwarded to ``_safe_torchaudio_save``.
    """
    target_dir = os.path.dirname(target_path) or "."
    target_base = os.path.basename(target_path)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target_base}.",
        suffix=".wav",
        dir=target_dir,
    )
    os.close(fd)
    try:
        safe_kwargs: dict[str, Any] = {}
        if "format" in kwargs:
            safe_kwargs["format"] = kwargs["format"]
        if "bits_per_sample" in kwargs:
            safe_kwargs["bits_per_sample"] = kwargs["bits_per_sample"]
        _safe_torchaudio_save(tmp_path, audio, sample_rate, **safe_kwargs)
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
