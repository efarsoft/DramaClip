"""TTS 引擎抽象与音频时长探测。"""

from __future__ import annotations

import subprocess  # noqa: S404 - 参数为受控列表
from pathlib import Path
from typing import Protocol

from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe

DEFAULT_VOICE = "zh-CN-YunxiNeural"


class TtsEngine(Protocol):
    @property
    def name(self) -> str: ...

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """合成语音到 out_path（wav/mp3），返回文件路径；失败抛异常。"""
        ...


def audio_duration_s(path: Path) -> float:
    """探测音频时长（秒）。"""
    result = subprocess.run(  # noqa: S603
        [
            resolve_ffprobe(),
            "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return float(result.stdout.strip())
