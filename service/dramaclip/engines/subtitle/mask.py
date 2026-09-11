"""原片字幕遮罩（原案 6B）：半透明遮罩自动覆盖底部字幕区，纯原片模式禁用。

本模块只拥有比例（y_offset=0.88 / height=0.12 / opacity=0.6）；
画幅由调用方传入（源是 infra.config，见 docs/04 §5.2），此处绝不写死像素。
"""

from __future__ import annotations

_Y_OFFSET = 0.88
_HEIGHT = 0.12
_OPACITY = 0.6


def drawbox_filter(enabled: bool, out_size: tuple[int, int]) -> str:
    """返回 FFmpeg drawbox 滤镜串；禁用（纯原片模式）返回空串。

    坐标按实际画幅算：drawbox 作用在 scale 到 out_size 之后的帧上，
    写死 1080×1920 会在画幅被 export.width/height 改动后盖到画面中部。
    """
    if not enabled:
        return ""
    width, frame_height = out_size
    y = int(frame_height * _Y_OFFSET)
    height = int(frame_height * _HEIGHT)
    return f"drawbox=x=0:y={y}:w={width}:h={height}:color=black@{_OPACITY}:t=fill"
