"""TTS 引擎抽象与音频时长探测。"""

from __future__ import annotations

import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe

DEFAULT_VOICE = "zh-CN-YunxiNeural"

SpeedControl = Literal["native", "ssml", "none"]


@dataclass(frozen=True)
class EngineCaps:
    """A3 引擎能力声明——值必须来自引擎真实属性（量出来的，不许编）。

    默认值是保守档：什么都不支持、采样率未知（0）、可用性未探测。
    speed_control: native=引擎参数原生变速；ssml=只能靠标记语言；none=不可控。
    reason 是人话（「缺模型」「需要隔离 venv」「云端可达」），直接上引擎卡。
    """

    sample_rate: int = 0
    supports_cloning: bool = False
    supports_emotion: bool = False
    speed_control: SpeedControl = "none"
    available: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_rate": self.sample_rate,
            "supports_cloning": self.supports_cloning,
            "supports_emotion": self.supports_emotion,
            "speed_control": self.speed_control,
            "available": self.available,
            "reason": self.reason,
        }


class TtsEngine(Protocol):
    @property
    def name(self) -> str: ...

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """合成语音到 out_path（wav/mp3），返回文件路径；失败抛异常。

        长文本切分/分块拼接是各引擎的内部实现细节（B7）：对调用方永远透明——
        返回的仍是**单个** out_path 落盘文件。批次一的缓存 key 用整段原文
        （切分前），改一字整段 hash 变、重合成，这个契约不因切分而改变。
        """
        ...

    def capabilities(self) -> EngineCaps:
        """能力声明；未实现的引擎按保守默认值回答。"""
        return EngineCaps()

    def is_available(self) -> tuple[bool, str]:
        """(可用, 人话原因)；未实现的引擎默认 (True, '')。"""
        return True, ""


def audio_duration_s(path: Path) -> float:
    """探测音频时长（秒）。"""
    return float(_ffprobe(path, "format=duration"))


def audio_container(path: Path) -> str:
    """探测落盘字节真实的容器名（ffprobe format_name）。

    各引擎写各自的原生容器（Edge=MP3，Kokoro=WAV），文件名按扩展名决定
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
