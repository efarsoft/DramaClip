"""切点安全抖动（Smart Jitter）：台词保护区避让 + 静音间隙抖动。
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from dramaclip.engines.analysis.models import SpeechZone

# docs/06-经验参数表 §1
_PROTECT_BEFORE_S = 0.2
_PROTECT_AFTER_S = 0.15
_JITTER_MIN_S = 0.08
_JITTER_MAX_S = 0.3
_MIN_SEGMENT_S = 0.45
# 边界顺延/回退上限：连续对白里 ASR 段可长达数十秒，无上限的贴边
# 会把 5s 切片扩成 40s+（真机回归实证），亚秒级足以覆盖"不吞字尾"
_MAX_ADJUST_S = 1.0

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(srt_path: Path) -> list[SpeechZone]:
    """解析 SRT 为语音区列表；解析失败返回空（降级能量法）。"""
    try:
        content = srt_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    zones: list[SpeechZone] = []
    matches = list(_SRT_TIME.finditer(content))
    for begin, end in zip(matches[::2], matches[1::2], strict=False):
        start = _srt_seconds(begin)
        stop = _srt_seconds(end)
        if stop > start:
            zones.append(SpeechZone(start=round(start, 3), end=round(stop, 3)))
    return zones


def srt_for_source(source_path: Path) -> Path | None:
    """同名 SRT 约定：<视频名>.srt；存在且非空才返回。"""
    candidate = source_path.with_suffix(".srt")
    return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


def _srt_seconds(match: re.Match) -> float:  # type: ignore[type-arg]
    hours, minutes, seconds, millis = (int(group) for group in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _protected_spans(zones: list[SpeechZone]) -> list[tuple[float, float]]:
    return [(z.start - _PROTECT_BEFORE_S, z.end + _PROTECT_AFTER_S) for z in zones]


def _in_protection(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(begin <= t <= end for begin, end in spans)


def safe_start(
    start: float,
    zones: list[SpeechZone],
    *,
    rng: random.Random | None = None,
) -> float:
    """入点安全化：命中台词保护区则外移到保护区之前；静音区则随机抖动。"""
    generator = rng or random
    spans = _protected_spans(zones)
    if not _in_protection(start, spans):
        gap = _gap_before(start, spans)
        if gap is not None and gap >= _JITTER_MIN_S:
            jitter = min(gap, generator.uniform(_JITTER_MIN_S, _JITTER_MAX_S))
            return max(0.0, start - jitter)
        return start
    # 命中保护区：外移到最近保护区起点之前（过远则保持原切点，防整段吞入）
    for begin, _end in sorted(spans):
        if begin <= start <= _end:
            if start - begin <= _MAX_ADJUST_S:
                return max(0.0, begin)
            break
    return start


def safe_end(
    end: float,
    zones: list[SpeechZone],
    *,
    rng: random.Random | None = None,
) -> float:
    """出点安全化：命中保护区则顺延至保护区结束之后（不吞字尾，距离有上限）。"""
    spans = _protected_spans(zones)
    if not _in_protection(end, spans):
        return end
    for begin, stop in sorted(spans):
        if begin <= end <= stop:
            if stop - end <= _MAX_ADJUST_S:
                return stop
            break
    return end


def safe_times(
    start: float,
    end: float,
    zones: list[SpeechZone],
    *,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """入/出点联合安全化；抖动后过短则回退原值。"""
    adjusted_start = safe_start(start, zones, rng=rng)
    adjusted_end = safe_end(end, zones, rng=rng)
    if adjusted_end - adjusted_start < _MIN_SEGMENT_S:
        return start, end
    return adjusted_start, adjusted_end


def _gap_before(t: float, spans: list[tuple[float, float]]) -> float | None:
    """t 与其左侧最近保护区终点之间的静音间隙宽度。"""
    left_edges = [stop for _begin, stop in spans if stop < t]
    if not left_edges:
        return t  # 左侧无保护区：可用间隙即 t 本身
    return t - max(left_edges)
