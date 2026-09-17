"""原片字幕遮罩（原案 6B）：半透明遮罩自动覆盖底部字幕区，纯原片模式禁用。
"""

from __future__ import annotations

_Y_OFFSET = 0.88
_HEIGHT = 0.12
_OPACITY = 0.6


def drawbox_filter(
    enabled: bool,
    out_size: tuple[int, int],
    band: tuple[float, float] | None = None,
) -> str:
    """返回 FFmpeg drawbox 滤镜串；禁用（纯原片模式）返回空串。

    band = (top, bottom) 归一化字幕带（来自 OCR 探测）；缺省回退静态底部区域。
    """
    if not enabled:
        return ""
    width, frame_height = out_size
    if band is not None:
        top = max(band[0] - 0.02, 0.0)
        height = min(band[1] + 0.02, 1.0) - top
    else:
        top = _Y_OFFSET
        height = _HEIGHT
    y = int(frame_height * top)
    height_px = int(frame_height * height)
    return f"drawbox=x=0:y={y}:w={width}:h={height_px}:color=black@{_OPACITY}:t=fill"
