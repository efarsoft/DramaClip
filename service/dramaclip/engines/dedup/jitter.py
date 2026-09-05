"""切点安全抖动（Smart Jitter）：台词保护区避让 + 静音间隙抖动。

语音区来自第一层分析产出的 audio_features.speech_zones（无字幕时能量法降级，
W2 已实现；SRT 保护区双路在 W8 补全）。
"""

from __future__ import annotations

import random

from dramaclip.engines.analysis.models import SpeechZone

# docs/06-经验参数表 §1
_PROTECT_BEFORE_S = 0.2
_PROTECT_AFTER_S = 0.15
_JITTER_MIN_S = 0.08
_JITTER_MAX_S = 0.3
_MIN_SEGMENT_S = 0.45


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
    # 命中保护区：外移到最近保护区起点之前
    for begin, _end in sorted(spans):
        if begin <= start <= _end:
            return max(0.0, begin)
    return start


def safe_end(
    end: float,
    zones: list[SpeechZone],
    *,
    rng: random.Random | None = None,
) -> float:
    """出点安全化：命中保护区则回收至保护区结束之后（不吞字尾）。"""
    spans = _protected_spans(zones)
    if not _in_protection(end, spans):
        return end
    for begin, stop in sorted(spans):
        if begin <= end <= stop:
            return stop
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
