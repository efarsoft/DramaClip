"""ffprobe 元信息：时长/分辨率/帧率/音轨。"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra.ffmpeg.binaries import resolve_ffprobe


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: Path) -> MediaInfo:
    """探测媒体文件；无法解析时抛 ValueError。"""
    result = subprocess.run(  # noqa: S603
        [
            resolve_ffprobe(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe 失败({path.name})：{result.stderr.strip()[:200]}")
    payload = json.loads(result.stdout)
    return _parse(payload, path)


def _parse(payload: dict, path: Path) -> MediaInfo:  # type: ignore[type-arg]
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if video is None:
        raise ValueError(f"无视频轨：{path.name}")
    duration = _duration(payload, video)
    return MediaInfo(
        duration_s=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=_fps(video),
        has_audio=has_audio,
    )


def _duration(payload: dict, video: dict) -> float:  # type: ignore[type-arg]
    candidates = (payload.get("format", {}).get("duration"), video.get("duration"))
    for source in candidates:
        if source is None:
            continue
        try:
            return float(source)
        except (TypeError, ValueError):
            continue
    raise ValueError("无法确定时长")


def _fps(video: dict) -> float:  # type: ignore[type-arg]
    raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    numerator, _, denominator = raw.partition("/")
    try:
        den = float(denominator) if denominator else 1.0
        value = float(numerator) / den if den else 0.0
    except ValueError:
        return 0.0
    return value
