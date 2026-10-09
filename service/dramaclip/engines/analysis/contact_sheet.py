"""逐集 contact sheet：每集均匀抽 16 帧 4x4 拼图（视觉轨的输入与预览资产）。

抽样帧的时间码按格序算术推导（第 i 格 ≈ (i + 0.5) × 集时长 / 16），图上不烙字——
时间码进视觉提示词由格序换算，图像保持干净。单条 ffmpeg（fps→scale→tile），
经 runner 受控执行（超时/取消/进度），与 OCR 采样共用同一受控封装不自造第二套。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from dramaclip.infra.ffmpeg import runner

GRID = "4x4"        # 4 列 4 行；视觉提示词按格序（先行后列）换算时间码
FRAMES = 16         # 每集抽样帧数 = 格数：与集长无关的常数成本，弱机友好
TILE_WIDTH = 320    # 单格宽：拼图约 1280 宽，视觉模型输入友好
_TIMEOUT_S = 300.0


def contact_sheet_args(video: str, out_png: str, *, duration_s: float) -> list[str]:
    """拼图 ffmpeg 参数（纯函数）：fps=帧数/集时长 → 缩放 → 4x4 tile → 单帧输出。"""
    if duration_s <= 0:
        raise ValueError(f"集时长非法: {duration_s}")
    fps = FRAMES / duration_s
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video,
        "-vf",
        f"fps={fps:.6f},scale={TILE_WIDTH}:-2,tile={GRID}",
        "-frames:v",
        "1",
        out_png,
    ]


def build_contact_sheet(
    video: Path,
    out_png: Path,
    *,
    duration_s: float,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """生成一集的 contact sheet；产出缺失按 FfmpegError 上抛（不静默）。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    runner.run(
        contact_sheet_args(str(video), str(out_png), duration_s=duration_s),
        total_duration_s=duration_s,
        timeout_s=_TIMEOUT_S,
        cancel=cancel,
        on_progress=on_progress,
    )
    if not out_png.is_file():
        raise runner.FfmpegError(f"拼图未产出: {out_png}")
    return out_png
