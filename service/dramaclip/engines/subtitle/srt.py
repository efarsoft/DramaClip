"""SRT 产物格式：时间码与块写法的全仓唯一实现处。

消费方有两条链：工具箱的 `copy.srt`（ASR+OCR 融合结果）与成片的逐句时间轴
（`api/export.py` 按段偏移回填）。前端 `desktop/src/features/tools/srt.ts` 的
解析器按 `HH:MM:SS,mmm --> HH:MM:SS,mmm` 读，所以格式只能有一处写法。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SrtCue:
    """一条字幕：起止秒与正文。"""

    start: float
    end: float
    text: str


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hour, rem = divmod(ms, 3_600_000)
    minute, rem = divmod(rem, 60_000)
    sec, milli = divmod(rem, 1000)
    return f"{hour:02d}:{minute:02d}:{sec:02d},{milli:03d}"


def format_srt(cues: Sequence[SrtCue]) -> str:
    """空正文跳行，但序号按输入位置走（不回收跳过的编号）。"""
    blocks = []
    for index, cue in enumerate(cues, 1):
        text = cue.text.strip()
        if not text:
            continue
        blocks.append(f"{index}\n{stamp(cue.start)} --> {stamp(cue.end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
