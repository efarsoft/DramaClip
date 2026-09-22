"""项目封面：从视频截一帧生成缩略图（封面属增强项，失败不阻塞主流程）。

可选标题字层：给了 `title` 时在截帧上烧标题（drawtext）。转义方案选 `textfile=`——
标题内容写临时 UTF-8 文件，drawtext 的 `:` `'` `\\` 文本转义坑全部绕开；滤镜串里
只剩两处路径值，用与 `caption_font.fontsdir_option` 同款（真机验证过）的
「单引号包住 + 盘符冒号 `\\:`」转义。字层任何一步失败都降级无字层截帧，永不 raise。
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import tempfile
from pathlib import Path

from dramaclip.infra.ffmpeg import runner

_LOGGER = logging.getLogger(__name__)

_COVER_WIDTH = 480  # 与 scale=480:-2 同源：字号按宽反推，不按高（9:16 下 h/12 会横向爆宽）
_WRAP_AT_CHARS = 14  # 超过则拆两行（drawtext 不自动折行）
_MAX_TITLE_CHARS = 28  # 超过则截断加「…」
_SPLIT_PUNCTUATION = "，。！？；：、,.!?;:"


def extract_cover(
    video_path: Path, out_path: Path, *, seek_s: float = 1.5, title: str | None = None
) -> bool:
    """先试钩子帧（默认成片 1.5s），越界回退 1s、再回退第一帧；均失败返回 False。

    给了 title（非空白）时先试烧标题字层；字层失败（drawtext 不支持/字体缺失）
    降级为无字层截帧并 warn，仍失败才返回 False。
    """
    lines = _wrap_title(title) if title is not None else None
    if lines is not None:
        face = _bundled_font_face()
        if face is None:
            _LOGGER.warning("随包字体不可用，封面标题字层降级为无字层截帧：%r", title)
        else:
            try:
                if _try_titled_cover(video_path, out_path, seek_s, face, lines):
                    return True
            except OSError:
                pass  # 连临时 textfile 都写不出：同样降级
            _LOGGER.warning("封面标题字层烧制失败，降级无字层截帧：%r", title)
    return _seek_and_grab(video_path, out_path, seek_s, "scale=480:-2")


def _seek_and_grab(video_path: Path, out_path: Path, seek_s: float, vf: str) -> bool:
    base = [
        "-vframes",
        "1",
        "-vf",
        vf,
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


def _wrap_title(title: str) -> list[str] | None:
    """空白标题→None（等同不烧字层）；>28 字截断加「…」；>14 字拆两行。

    拆行优先按标点（标点留上行行尾、离中点最近），无可用标点则中点硬拆；
    两行经 textfile 里的 `\\n` 交给同一个 drawtext（比两个滤镜串联少一层坐标计算）。
    """
    flat = " ".join(title.split())  # 折叠空白/换行：标题不该带原始换行进 drawtext
    if not flat:
        return None
    if len(flat) > _MAX_TITLE_CHARS:
        flat = flat[:_MAX_TITLE_CHARS] + "…"
    if len(flat) <= _WRAP_AT_CHARS:
        return [flat]
    mid = math.ceil(len(flat) / 2)
    best_cut: int | None = None
    for index, char in enumerate(flat):
        if char not in _SPLIT_PUNCTUATION:
            continue
        cut = index + 1  # 标点归上行行尾
        if cut < 3 or len(flat) - cut < 3:  # 不放 1-2 字的孤行
            continue
        if best_cut is None or abs(cut - mid) < abs(best_cut - mid):
            best_cut = cut
    cut_at = mid if best_cut is None else best_cut
    return [flat[:cut_at], flat[cut_at:]]


def _fontsize_for(lines: list[str]) -> int:
    """按 480 宽反推字号：CJK 全角字宽≈fontsize，留 10% 边距，钉在 20–64。"""
    longest = max(len(line) for line in lines)
    return max(20, min(64, int(_COVER_WIDTH * 0.9 / longest)))


def _bundled_font_face() -> Path | None:
    """随包字体文件（drawtext 要 fontfile= 具体文件，CaptionFont 只给 files_dir）。"""
    # 惰性导入：infra→engines 仅此一处，且只在真的要烧字层时才付出导入成本
    from dramaclip.engines.subtitle import caption_font as caption_font_mod

    try:
        font = caption_font_mod.caption_font()
    except (OSError, ValueError):
        return None
    faces = sorted(
        path
        for path in font.files_dir.glob("*")
        if path.suffix.lower() in caption_font_mod.FACE_SUFFIXES
    )
    return faces[0] if faces else None


def _filter_path(path: Path) -> str:
    """滤镜串内路径转义：同 fontsdir_option 的真机验证形状（单引号 + 盘符 \\:）。"""
    return "'" + path.as_posix().replace(":", "\\:") + "'"


def _drawtext_vf(font_face: Path, textfile: Path, lines: list[str]) -> str:
    opts = [
        f"fontfile={_filter_path(font_face)}",
        f"textfile={_filter_path(textfile)}",
        f"fontsize={_fontsize_for(lines)}",
        "fontcolor=white",
        "borderw=3",
        "bordercolor=black@0.9",
        "x=(w-text_w)/2",
        "y=h-text_h-h/16",
        "line_spacing=8",
    ]
    return "scale=480:-2,drawtext=" + ":".join(opts)


def _try_titled_cover(
    video_path: Path, out_path: Path, seek_s: float, font_face: Path, lines: list[str]
) -> bool:
    """标题写 out_path 同目录临时 textfile，三段 seek 试烧字层；finally 删临时文件。"""
    fd, name = tempfile.mkstemp(prefix=".cover-title-", suffix=".txt", dir=out_path.parent)
    os.close(fd)
    textfile = Path(name)
    try:
        textfile.write_text("\n".join(lines), encoding="utf-8")
        vf = _drawtext_vf(font_face, textfile, lines)
        return _seek_and_grab(video_path, out_path, seek_s, vf)
    finally:
        # Windows 上 ffmpeg 刚退出时句柄可能未释放：清理尽力而为，不许炸掉已成功的返回值
        with contextlib.suppress(OSError):
            textfile.unlink(missing_ok=True)
