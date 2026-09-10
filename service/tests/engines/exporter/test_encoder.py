"""engines.exporter.encoder：命令构建（真实 ffmpeg 执行由 DoD 端到端覆盖）。"""

from __future__ import annotations

import random

from dramaclip.engines.exporter.encoder import cut_segment_args
from dramaclip.engines.subtitle.mask import drawbox_filter


def test_drawbox_filter_toggle() -> None:
    assert drawbox_filter(True).startswith("drawbox=x=0:y=1689")
    assert drawbox_filter(False) == ""


def test_cut_segment_args_original_audio() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=1.5,
        end=8.25,
        audio="original",
        mask=True,
        tts_audio=None,
        rng=random.Random(42),
    )
    joined = " ".join(args)
    assert "-ss 1.500" in joined and "-to 8.250" in joined
    assert "scale=1080:1920" in joined, "竖屏输出"
    assert "drawbox" in joined, "遮罩开启"
    assert "eq=contrast=" in joined, "消重色彩抖动"
    assert "atempo=" in joined, "微变速"
    assert "-map_metadata -1" in joined, "元数据擦除"
    assert "-ar 48000" in joined, "采样率统一（concat 流复制防语速失真）"
    assert "amix" not in joined


def test_cut_segment_args_narration_mixes_tts() -> None:
    args = cut_segment_args(
        "src.mp4",
        "seg.mp4",
        start=0,
        end=10,
        audio="narration",
        mask=True,
        tts_audio="intro.mp3",
        rng=random.Random(7),
    )
    joined = " ".join(args)
    assert "amix=inputs=2" in joined
    assert "volume=0.2" in joined, "旁白段原声压低"
    assert "intro.mp3" in joined
