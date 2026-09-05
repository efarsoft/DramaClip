"""FFmpeg/FFprobe 二进制路径解析：resources/ffmpeg/ → PATH。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _resource_bin(name: str) -> Path | None:
    # infra/ffmpeg/binaries.py → 上四级为仓库根
    candidate = Path(__file__).resolve().parents[3] / "resources" / "ffmpeg" / name
    return candidate if candidate.is_file() else None


def resolve_ffmpeg() -> str:
    resource = _resource_bin("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if resource is not None:
        return str(resource)
    found = shutil.which("ffmpeg")
    if found is None:
        raise FileNotFoundError("找不到 ffmpeg（resources/ffmpeg/ 与 PATH 均无）")
    return found


def resolve_ffprobe() -> str:
    resource = _resource_bin("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if resource is not None:
        return str(resource)
    found = shutil.which("ffprobe")
    if found is None:
        raise FileNotFoundError("找不到 ffprobe（resources/ffmpeg/ 与 PATH 均无）")
    return found
