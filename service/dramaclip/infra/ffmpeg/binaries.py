"""FFmpeg/FFprobe 二进制路径解析：resources/ffmpeg/ → PATH；外加版本探测。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from dramaclip.infra.paths import resolve_resources_dir

_VERSION_LINE = re.compile(r"ffmpeg version n?(\d+(?:\.\d+)+)")


def _resource_bin(name: str) -> Path | None:
    candidate = resolve_resources_dir() / "ffmpeg" / name
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


def version(force: bool = False) -> str:
    """这台机器上那个 ffmpeg 自述的版本号（如 ``8.1.1``）；拿不到即空串。

    就绪度条要说「渲染 8.1.1」，那只能是真探测的结果，不能是打包时记下的常量。
    空串是明确的「不可用」信号——前端据此报红，而不是假装这一格是绿的。
    ``force`` 换掉的是全机共用的那一份缓存，所以刷新之后所有调用方都看到新值。
    """
    if force:
        _probe.cache_clear()
    return _probe()


@lru_cache(maxsize=1)
def _probe() -> str:
    try:
        binary = resolve_ffmpeg()
    except FileNotFoundError:
        return ""
    completed = subprocess.run(  # noqa: S603
        [binary, "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    match = _VERSION_LINE.search(completed.stdout)
    return match.group(1) if match is not None else ""
