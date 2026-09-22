"""按跳距给时间轴赋转场：连续镜头切、换场浅淡、跨集入黑。"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.engines.subtitle.emotion_matcher import match_emotion

_NEIGHBOR_CUT_S = 1.0


def apply(plan: PlanData) -> PlanData:
    """给方案时间轴打好转场标记，并给未盖章的旁白段盖上情绪。"""
    return plan.model_copy(
        update={"timeline": _stamp_emotions(assign_transitions(plan.timeline))}
    )


def _stamp_emotions(segments: list[TimelineSegment]) -> list[TimelineSegment]:
    out: list[TimelineSegment] = []
    for segment in segments:
        if segment.emotion_label or not segment.subtitle_text:
            out.append(segment)
            continue
        out.append(
            segment.model_copy(update={"emotion_label": match_emotion(segment.subtitle_text)})
        )
    return out


def assign_transitions(segments: list[TimelineSegment]) -> list[TimelineSegment]:
    """片头钩子保持切；同集 <1s 贴着切；同集换场 fade；跨集 black。flash 不再赋。"""
    out: list[TimelineSegment] = []
    for index, segment in enumerate(segments):
        if index == 0:
            kind: str = "cut"
        else:
            prev = segments[index - 1]
            if segment.episode_id != prev.episode_id:
                kind = "black"
            else:
                gap = segment.start - prev.end
                kind = "cut" if 0.0 <= gap < _NEIGHBOR_CUT_S else "fade"
        out.append(segment.model_copy(update={"transition": kind}))
    return out
