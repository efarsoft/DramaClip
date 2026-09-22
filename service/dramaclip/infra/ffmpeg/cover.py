"""项目封面：从视频截一帧生成缩略图（封面属增强项，失败不阻塞主流程）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.ffmpeg import runner


def extract_cover(video_path: Path, out_path: Path, *, seek_s: float = 1.5) -> bool:
    """先试钩子帧（默认成片 1.5s），越界回退 1s、再回退第一帧；均失败返回 False。"""
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
    seeks: list[list[str]] = [["-ss", f"{seek_s:g}"]]
    if abs(seek_s - 1.0) > 1e-6:
        seeks.append(["-ss", "1"])
    seeks.append([])
    for seek in seeks:
        try:
            runner.run(["-y", *seek, "-i", str(video_path), *base], timeout_s=30)
        except runner.FfmpegError:
            continue
        if out_path.is_file():
            return True
    return False
