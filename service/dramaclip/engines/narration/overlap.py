"""取材重叠度量：两条方案共用了多少秒的同一批画面。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData

# 规格 §4.3：超阈值直接不出该角度。不是设置项——改它就是改规格。
OVERLAP_LIMIT = 0.60

# episode_id → 已合并的升序区间列表
Spans = dict[str, list[tuple[float, float]]]


def source_spans(plan: PlanData) -> Spans:
    """方案取材 → 每集的**已合并**区间列表（升序、互不重叠）。
    """
    grouped: dict[str, list[tuple[float, float]]] = {}
    for segment in plan.timeline:
        if segment.end <= segment.start:
            continue
        grouped.setdefault(segment.episode_id, []).append((segment.start, segment.end))
    return {episode_id: _merge(spans) for episode_id, spans in grouped.items()}


def overlap(left: PlanData, right: PlanData) -> float:
    """Jaccard：共用秒数 / 两者并集秒数。0=取材全异，1=同一部片。
    """
    a = source_spans(left)
    b = source_spans(right)
    shared = _intersect(a, b)
    union = _total(a) + _total(b) - shared
    if union <= 0:
        return 0.0
    return shared / union


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _total(spans: Spans) -> float:
    return sum(end - start for group in spans.values() for start, end in group)


def _intersect(left: Spans, right: Spans) -> float:
    """两组已合并区间的交集秒数：逐集双指针，两侧各自有序故线性。"""
    shared = 0.0
    for episode_id, a in left.items():
        b = right.get(episode_id)
        if not b:
            continue
        i = 0
        j = 0
        while i < len(a) and j < len(b):
            start = max(a[i][0], b[j][0])
            end = min(a[i][1], b[j][1])
            if end > start:
                shared += end - start
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
    return shared
