"""高光综合排序（原案 4.3 简化版）：

高光分 = 0.5×冲突分 + 0.3×音频能量 + 0.2×台词情绪密度
画质维度（原案 γ）待 engines/analysis/quality.py（P1）后并入。
产出排序后的高光片段列表（供前端看板与 W4 编排消费）。
"""

from __future__ import annotations

from collections.abc import Callable

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment

_W_CONFLICT = 0.5
_W_ENERGY = 0.3
_W_EMOTION = 0.2

SpanScorer = Callable[[float, float], float]

_EMOTION_WORDS: tuple[str, ...] = (
    "哭", "笑", "怒", "恨", "爱", "怕", "求", "滚", "杀", "死", "天哪", "疯了", "不敢", "竟然",
)


def rank_highlights(
    conflict_scores: list[ConflictScore],
    audio: AudioFeatures,
    segments: list[AsrSegment],
    *,
    top_ratio: float = 0.3,
    min_score: float = 45.0,
) -> list[HighlightSegment]:
    """综合排序并取 Top-N（至少保留 1 个非零分场景）。"""
    if not conflict_scores:
        return []
    energy_fn = _energy_lookup(audio)
    emotion_fn = _emotion_lookup(segments)

    scored: list[tuple[float, ConflictScore]] = []
    for item in conflict_scores:
        combined = (
            _W_CONFLICT * (item.score / 100.0)
            + _W_ENERGY * energy_fn(item.start, item.end)
            + _W_EMOTION * emotion_fn(item.start, item.end)
        )
        scored.append((combined * 100.0, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].scene_index))

    keep = max(1, int(round(len(scored) * top_ratio)))
    return [
        HighlightSegment(
            start=item.start,
            end=item.end,
            score=round(value, 1),
            reason=item.reason or f"综合分 {value:.0f}",
        )
        for value, item in scored[:keep]
        if value >= min_score or value > 0
    ][:keep]


def _energy_lookup(audio: AudioFeatures) -> SpanScorer:
    """返回 (start,end)→[0,1] 能量均值的查表函数。"""
    points = audio.energy_curve
    if not points:
        return lambda _start, _end: 0.5  # 无曲线时给中性值，不拖垮综合分

    def lookup(start: float, end: float) -> float:
        window = [value for t, value in points if start <= t <= end]
        if not window:
            window = [value for _t, value in points]
        mean = sum(window) / len(window)
        return max(0.0, min(mean * 8.0, 1.0))  # RMS≈0.125 即满格（语音正常范围）

    return lookup


def _emotion_lookup(segments: list[AsrSegment]) -> SpanScorer:
    def lookup(start: float, end: float) -> float:
        texts = [seg.text for seg in segments if seg.start < end and seg.end > start]
        if not texts:
            return 0.0
        joined = "".join(texts)
        hits = sum(joined.count(word) for word in _EMOTION_WORDS)
        return min(hits / 5.0, 1.0)

    return lookup
