"""随包字幕字体：字面由包里的文件决定，不由安装机装了什么决定。

一处真相，三处引用：ASS 样式的 Fontname、`line_char_cap` 标定每字步进用的那个字面、
以及 ffmpeg `ass` 滤镜实际加载的字体目录。三者不同源时，界面上看不出任何异常，只有
成片里字幕越界或换了字形——所以族名从字体文件自己的 name 表里读，不另写一份声明。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from dramaclip.infra.paths import resolve_resources_dir

FACE_SUFFIXES = (".otf", ".ttf")


@dataclass(frozen=True)
class CaptionFont:
    """随包字面：`family` 是文件自报的族名，`files_dir` 给渲染端当 `fontsdir`。"""

    family: str
    files_dir: Path


def _read(handle: BinaryIO, offset: int, size: int) -> bytes:
    handle.seek(offset)
    chunk = handle.read(size)
    if len(chunk) != size:
        raise ValueError(f"字体文件在 {offset}+{size} 处截断")
    return chunk


def _family_from_font(path: Path) -> str:
    """读 sfnt `name` 表里的 Family（nameID 1）。

    族名必须取自文件：随包换字体时，样式行跟着换，拆行上限重标也有对应的设计依据；
    手抄一份声明迟早和包里的文件对不上，而那正是「静默换字面」的形状。
    """
    with path.open("rb") as handle:
        if struct.unpack(">I", _read(handle, 0, 4))[0] not in (0x00010000, 0x4F54544F):
            raise ValueError(f"{path.name} 不是 sfnt 字体（'ttcf' 集合不在随包支持范围内）")
        count = struct.unpack(">H", _read(handle, 4, 2))[0]
        tables = {}
        for index in range(count):
            record = _read(handle, 12 + index * 16, 16)
            tables[record[:4]] = struct.unpack(">II", record[8:16])
        if b"name" not in tables:
            raise ValueError(f"{path.name} 没有 name 表，读不出族名")
        offset, length = tables[b"name"]
        blob = _read(handle, offset, length)
        record_count, string_offset = struct.unpack(">HH", blob[2:6])
        best: tuple[int, str] | None = None
        for index in range(record_count):
            platform, _enc, _lang, name_id, size, start = struct.unpack(
                ">HHHHHH", blob[6 + index * 12 : 18 + index * 12]
            )
            if name_id != 1:
                continue
            raw = blob[string_offset + start : string_offset + start + size]
            value = raw.decode("utf-16-be" if platform in (0, 2, 3) else "latin-1").strip()
            # 平台优先级：Windows(3) > Unicode(0) > Mac(1)——DirectWrite 认前两者
            rank = {3: 0, 0: 1, 1: 2}.get(platform, 3)
            if value and (best is None or rank < best[0]):
                best = (rank, value)
        if best is None:
            raise ValueError(f"{path.name} 的 name 表里没有 Family（nameID 1）")
        return best[1]


@lru_cache(maxsize=4)
def _caption_font(files_dir: str) -> CaptionFont:
    faces = sorted(
        path for path in Path(files_dir).glob("*") if path.suffix.lower() in FACE_SUFFIXES
    )
    if not faces:
        raise FileNotFoundError(
            f"随包字幕字体缺失：{files_dir}（resources/fonts）下没有 {'/'.join(FACE_SUFFIXES)}"
            "；缺了它，字幕字面由安装机装了什么决定，而拆行上限是按随包那份标定的"
        )
    return CaptionFont(family=_family_from_font(faces[0]), files_dir=Path(files_dir))


def caption_font(fonts_dir: Path | None = None) -> CaptionFont:
    """随包字面；`fonts_dir` 仅为测试注入，缺省指向 resources/fonts。"""
    if fonts_dir is None:
        return _caption_font((resolve_resources_dir() / "fonts").as_posix())
    return _caption_font(fonts_dir.as_posix())


def fontsdir_option(font: CaptionFont) -> str:
    """ffmpeg `ass` 滤镜的 `fontsdir=` 片段（真机验证的形状：单引号包住、盘符冒号转义）。

    不这么给的话 libass 只按族名去系统字体里找，找不到就换一个**且不报错**：实测同一
    份 ASS 在随包字面下每字步进 0.691em，落到系统兜底是 0.789em。
    """
    return f"fontsdir='{font.files_dir.as_posix().replace(':', chr(92) + ':')}'"
