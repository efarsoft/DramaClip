"""成片 AI 生成标注（settings `export.ai_label`，默认关闭）。

业主裁决（2026-10-15）：AI 标注从「强制合规声明」改为「用户开关、默认关闭」——
各平台对 AI 合成内容的标注要求不一，是否标注由使用者按发布平台自行决定，
软件不强制、不代决。开启后在成片右上角烧「AI 生成」字样。

实现要点：
- drawtext + textfile：CJK 文本不进滤镜串（Windows 命令行与 ffmpeg 滤镜解析的
  转义坑全部绕开），与 `infra/ffmpeg/cover.py` 封面标题字层同款方案；
- 独立后处理遍（loudness 之后）：`-c:a copy` 保住响度归一成果，只重编视频。
  关闭时不进这条路径，零额外开销；
- 烧制失败**硬失败**（AiLabelError 上抛，导出记失败）：用户开了标注却静默交付
  无标注成片，比导出失败更糟——那条路至少看得见、可重试。封面/自检那种「增强
  项降级」的惯例不适用这里：标注是用户明示要买的东西，不是锦上添花。
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover
from dramaclip.infra.ffmpeg import runner

_LOGGER = logging.getLogger(__name__)

#: 标注文案：平台规则通行的最短声明（抖音/视频号/小红书均要求明示 AI 生成）。
LABEL_TEXT = "AI 生成"

#: 右上角定位：横/纵各 3% 边距（避开平台 UI 常驻的顶部通栏与底部互动区）。
_MARGIN_RATIO = 0.03
#: 字号按画布高度 1/34（1080×1920 → 56px）；下限 24 防小画布糊成一片。
_FONTSIZE_DIVISOR = 34
_FONTSIZE_MIN = 24
#: 后处理遍是整片重编：超时按 concat 重编码同档（loudness 那遍 600s 是滤镜内
# 192kHz 重采样的账，这边纯 x264 编码，给足 3600s）。
_TIMEOUT_S = 3600.0


class AiLabelError(RuntimeError):
    """AI 标注烧制失败（用户已开启标注，不能静默交付无标注成片）。"""


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


def apply(out_path: Path, work_dir: Path, out_size: tuple[int, int]) -> None:
    """在成片右上角烧「AI 生成」标注（原地替换）。失败抛 AiLabelError。"""
    face = ffmpeg_cover.bundled_font_face()
    if face is None:
        raise AiLabelError("随包字体不可用，无法烧制 AI 生成标注")
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ai-label-", suffix=".txt", dir=work_dir)
    os.close(fd)
    textfile = Path(name)
    staged = work_dir / "ai_label_stage.mp4"
    try:
        textfile.write_text(LABEL_TEXT, encoding="utf-8")
        args = [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(out_path),
            "-vf",
            label_vf(face, textfile, out_size),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            "-map_metadata",
            "-1",
            str(staged),
        ]
        try:
            runner.run(args, timeout_s=_TIMEOUT_S)
        except runner.FfmpegError as exc:
            raise AiLabelError(f"AI 标注烧制失败：{exc}") from exc
        os.replace(staged, out_path)
        _LOGGER.info("AI 生成标注已烧制：%s", out_path.name)
    finally:
        # Windows 上 ffmpeg 刚退出时句柄可能未释放：清理尽力而为，不许炸掉已成功的替换
        with contextlib.suppress(OSError):
            textfile.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            staged.unlink(missing_ok=True)
