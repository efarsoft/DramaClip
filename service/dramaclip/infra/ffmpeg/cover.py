"""项目封面：从视频截一帧生成缩略图（封面属增强项，失败不阻塞主流程）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.ffmpeg import runner


def extract_cover(video_path: Path, out_path: Path) -> bool:
    """先试 1s 处，短视频越界时回退到第一帧；均失败返回 False。"""
    base = [
        "-vframes",
        "1",
        "-vf",
        "scale=480:-2",
        "-q:v",
        "4",
        "-strict",
        "unofficial",
        str(out_path),
    ]
    for seek in (["-ss", "1"], []):
        try:
            runner.run(["-y", *seek, "-i", str(video_path), *base], timeout_s=30)
        except runner.FfmpegError:
            continue
        if out_path.is_file():
            return True
    return False
