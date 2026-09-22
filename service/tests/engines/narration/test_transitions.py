"""时间轴转场赋值：连续镜头切、换场淡、跨集入黑。"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.engines.narration.transitions import apply, assign_transitions


def test_assign_transitions_by_jump() -> None:
    segments = [
        TimelineSegment(episode_id="ep1", start=0.0, end=5.0),
        TimelineSegment(episode_id="ep1", start=5.2, end=10.0),
        TimelineSegment(episode_id="ep1", start=20.0, end=25.0),
        TimelineSegment(episode_id="ep2", start=0.0, end=4.0),
    ]
    kinds = [seg.transition for seg in assign_transitions(segments)]
    assert kinds == ["cut", "cut", "fade", "black"]


def test_empty_timeline() -> None:
    assert assign_transitions([]) == []


def test_apply_stamps_emotion_from_copy() -> None:
    plan = PlanData(
        mode="dialogue_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, subtitle_text="你给我滚出去"
            ),
            TimelineSegment(
                episode_id="ep1",
                start=3.0,
                end=6.0,
                subtitle_text="今天天气不错",
                emotion_label="triumph",
            ),
        ],
    )
    out = apply(plan)
    assert out.timeline[0].emotion_label == "anger"
    assert out.timeline[1].emotion_label == "triumph", "已盖章的情绪不许被文案关键词覆盖"
