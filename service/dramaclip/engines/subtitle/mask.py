"""原片字幕遮罩（原案 6B）：半透明遮罩自动覆盖底部字幕区，纯原片模式禁用。

固定参数：y_offset=0.88 / height=0.12 / opacity=0.6（针对 1080x1920 输出）。
"""

from __future__ import annotations

_Y_OFFSET = 0.88
_HEIGHT = 0.12
_OPACITY = 0.6


def drawbox_filter(enabled: bool) -> str:
    """返回 FFmpeg drawbox 滤镜串；禁用（纯原片模式）返回空串。"""
    if not enabled:
        return ""
    y = int(1920 * _Y_OFFSET)
    height = int(1920 * _HEIGHT)
    return f"drawbox=x=0:y={y}:w=1080:h={height}:color=black@{_OPACITY}:t=fill"
