"""原片字幕遮罩（原案 6B）：半透明遮罩自动覆盖底部字幕区，纯原片模式禁用。
"""

from __future__ import annotations

_Y_OFFSET = 0.88
_HEIGHT = 0.12
_OPACITY = 0.6


def drawbox_filter(enabled: bool, out_size: tuple[int, int]) -> str:
    """返回 FFmpeg drawbox 滤镜串；禁用（纯原片模式）返回空串。
    """
    if not enabled:
        return ""
    width, frame_height = out_size
    y = int(frame_height * _Y_OFFSET)
    height = int(frame_height * _HEIGHT)
    return f"drawbox=x=0:y={y}:w={width}:h={height}:color=black@{_OPACITY}:t=fill"
