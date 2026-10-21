"""成片 AI 生成标注（settings `export.ai_label`，默认关闭）。

业主裁决（2026-10-15）：AI 标注从「强制合规声明」改为「用户开关、默认关闭」——
各平台对 AI 合成内容的标注要求不一，是否标注由使用者按发布平台自行决定，
软件不强制、不代决。开启后在每段画面右上角烧「AI 生成」字样。

实现要点：
- 段滤镜而非整片后处理：标注随 Phase A 每段烧一次，Phase B `-c copy` 拼接，
  硬编成果不再被一遍 libx264 整片重编吃掉；内容摘要进段签名，改文案/字体/画布会重编；
- drawtext + textfile：CJK 文本不进滤镜串（Windows 命令行与 ffmpeg 滤镜解析的
  转义坑全部绕开），与 `infra/ffmpeg/cover.py` 封面标题字层同款方案；
- 字体缺失**硬失败**（AiLabelError 上抛，导出记失败）：用户开了标注却静默交付
  无标注成片，比导出失败更糟——那条路至少看得见、可重试。标注是用户明示要买的
  东西，不是锦上添花的增强项。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover

#: 标注文案：平台规则通行的最短声明（抖音/视频号/小红书均要求明示 AI 生成）。
LABEL_TEXT = "AI 生成"

#: 右上角定位：横/纵各 3% 边距（避开平台 UI 常驻的顶部通栏与底部互动区）。
_MARGIN_RATIO = 0.03
#: 字号按画布高度 1/34（1080×1920 → 56px）；下限 24 防小画布糊成一片。
_FONTSIZE_DIVISOR = 34
_FONTSIZE_MIN = 24


class AiLabelError(RuntimeError):
    """AI 标注准备失败（用户已开启标注，不能静默交付无标注成片）。"""


@dataclass(frozen=True)
class AiLabelSpec:
    """一次导出共用的标注：滤镜串、段签名摘要与共享 textfile。"""

    vf: str
    fingerprint: str
    textfile: Path


def enabled(settings: config.Settings) -> bool:
    """读取开关（默认 false；DEFAULTS 缺键时 get_bool 同样判假）。"""
    return config.get_bool(settings, "export.ai_label")


def label_vf(face: Path, textfile: Path, out_size: tuple[int, int]) -> str:
    """拼 drawtext 滤镜串（纯函数：入参齐了就不碰 IO，便于单测钉形状）。"""
    _, height = out_size
    fontsize = max(_FONTSIZE_MIN, round(height / _FONTSIZE_DIVISOR))
    opts = [
        f"fontfile={ffmpeg_cover.filter_path(face)}",
        f"textfile={ffmpeg_cover.filter_path(textfile)}",
        f"fontsize={fontsize}",
        "fontcolor=white",
        "borderw=3",
        "bordercolor=black@0.9",
        f"x=w-text_w-w*{_MARGIN_RATIO:g}",
        f"y=h*{_MARGIN_RATIO:g}",
    ]
    return "drawtext=" + ":".join(opts)


def prepare(work_dir: Path, out_size: tuple[int, int]) -> AiLabelSpec:
    """准备标注滤镜与内容摘要（字体缺失抛 AiLabelError）。

    摘要覆盖文案 + 画布派生的字号/边距 + 字体文件内容；textfile 路径不进摘要
    （它随 work_dir 变化，进签名会让每次续跑都判不可复用）。
    """
    face = ffmpeg_cover.bundled_font_face()
    if face is None:
        raise AiLabelError("随包字体不可用，无法烧制 AI 生成标注")
    work_dir.mkdir(parents=True, exist_ok=True)
    textfile = work_dir / ".ai-label.txt"
    textfile.write_text(LABEL_TEXT, encoding="utf-8")
    vf = label_vf(face, textfile, out_size)
    payload = [LABEL_TEXT, vf, hashlib.sha256(face.read_bytes()).hexdigest()]
    fingerprint = hashlib.sha256("\0".join(payload).encode("utf-8")).hexdigest()
    return AiLabelSpec(vf=vf, fingerprint=fingerprint, textfile=textfile)
