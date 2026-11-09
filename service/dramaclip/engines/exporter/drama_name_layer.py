"""成片剧名常驻层（settings ``export.drama_name_layer``，默认关闭）。

业主裁决（2026-11-09）：默认关、用户可开。出品方要求推广切片全程带剧名；
开启后每段左上角烧剧名（项目名）——与右上角 AI 标注（ai_label）避让，
两者可同时开。实现镜像 ai_label：段滤镜 + textfile + 内容摘要进段签名；
字体缺失/剧名为空硬失败——用户明示要的东西不能静默缺席。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover

_MARGIN_RATIO = 0.03
#: 比 AI 标注（/34）小一号：剧名可长达十余字，48px 视觉更克制。
_FONTSIZE_DIVISOR = 40
_FONTSIZE_MIN = 24


class DramaNameLayerError(RuntimeError):
    """剧名层准备失败（用户已开启，不能静默交付无剧名成片）。"""


@dataclass(frozen=True)
class DramaNameSpec:
    """一次导出共用的剧名层：滤镜串、段签名摘要与共享 textfile。"""

    vf: str
    fingerprint: str
    textfile: Path


def enabled(settings: config.Settings) -> bool:
    return config.get_bool(settings, "export.drama_name_layer")


def layer_vf(face: Path, textfile: Path, out_size: tuple[int, int]) -> str:
    """左上角 drawtext（纯函数）；x=w*3% 与 AI 标注的右上角镜像避让。"""
    _, height = out_size
    fontsize = max(_FONTSIZE_MIN, round(height / _FONTSIZE_DIVISOR))
    opts = [
        f"fontfile={ffmpeg_cover.filter_path(face)}",
        f"textfile={ffmpeg_cover.filter_path(textfile)}",
        f"fontsize={fontsize}",
        "fontcolor=white",
        "borderw=3",
        "bordercolor=black@0.9",
        f"x=w*{_MARGIN_RATIO:g}",
        f"y=h*{_MARGIN_RATIO:g}",
    ]
    return "drawtext=" + ":".join(opts)


def prepare(work_dir: Path, out_size: tuple[int, int], drama_name: str) -> DramaNameSpec:
    """准备剧名层（空剧名/缺字体抛 DramaNameLayerError）。

    摘要覆盖剧名 + 滤镜串 + 字体内容。
    """
    name = drama_name.strip()
    if not name:
        raise DramaNameLayerError("剧名为空，无法烧制剧名常驻层")
    face = ffmpeg_cover.bundled_font_face()
    if face is None:
        raise DramaNameLayerError("随包字体不可用，无法烧制剧名常驻层")
    work_dir.mkdir(parents=True, exist_ok=True)
    textfile = work_dir / ".drama-name.txt"
    textfile.write_text(name, encoding="utf-8")
    vf = layer_vf(face, textfile, out_size)
    payload = [name, vf, hashlib.sha256(face.read_bytes()).hexdigest()]
    fingerprint = hashlib.sha256("\0".join(payload).encode("utf-8")).hexdigest()
    return DramaNameSpec(vf=vf, fingerprint=fingerprint, textfile=textfile)
