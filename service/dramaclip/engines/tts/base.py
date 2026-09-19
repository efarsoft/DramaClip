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
    return float(_ffprobe(path, "format=duration"))


def audio_container(path: Path) -> str:
    """探测落盘字节真实的容器名（ffprobe format_name）。

    三个引擎各写各的原生容器（Edge=MP3，Kokoro/sherpa=WAV），文件名按扩展名决定
    浏览器收到的 Content-Type——按 `.mp3` 猜等于给 WAV 挂个 MP3 的牌子。
    """
    return _ffprobe(path, "format=format_name")


def _ffprobe(path: Path, entries: str) -> str:
    result = subprocess.run(  # noqa: S603
        [
            resolve_ffprobe(),
            "-v", "error", "-show_entries", entries,
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return result.stdout.strip()
