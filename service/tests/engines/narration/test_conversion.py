"""转化门禁：无 CTA / 空喊关注的方案进不了作品库。"""

from __future__ import annotations

from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment


def _plan(*, mode: str = "full_narration", last: str, first_end: float = 3.0) -> PlanData:
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=first_end, audio="ducked", narration_id="a"
            ),
            TimelineSegment(
                episode_id="ep1",
                start=first_end,
                end=first_end + 2.0,
                audio="ducked",
                narration_id="b",
            ),
        ],
        narration_texts=[
            NarrationText(id="a", text="开场钩子"),
            NarrationText(id="b", text=last),
        ],
    )


def test_cta_pointing_at_full_series_passes() -> None:
    assert defects(_plan(last="后面更狠——点进去看全集")) == []


def test_missing_cta_is_a_defect() -> None:
    assert "收尾没有指向看全集" in defects(_plan(last="今天就讲到这里"))


def test_banned_follow_cta_is_a_defect() -> None:
    issues = defects(_plan(last="关注我看全集"))
    assert "收尾禁止关注/点赞/二维码" in issues


def test_raw_clip_skips_cta_copy() -> None:
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    assert defects(plan) == []


def test_empty_timeline_fails() -> None:
    assert defects(PlanData(mode="full_narration")) == ["空时间轴"]


def test_grade_is_ready_only_when_defects_empty() -> None:
    from dramaclip.engines.narration.conversion import grade

    assert grade(_plan(last="后面更狠——点进去看全集")) == "ready"
    assert grade(_plan(last="今天就讲到这里")) == "draft"
    assert grade(PlanData(mode="raw_clip", timeline=[
        TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")
    ])) == "ready"


def test_intro_hook_cta_does_not_pass_for_the_ending() -> None:
    """片头写了看全集，不等于片尾有 CTA。"""
    plan = PlanData(
        mode="intro_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="narration", narration_id="intro"
            ),
            TimelineSegment(episode_id="ep1", start=3.0, end=20.0, audio="original"),
        ],
        narration_texts=[
            NarrationText(id="intro", text="开场钩子，后面更狠——点进去看全集"),
        ],
    )
    assert "收尾没有文案" in defects(plan)


def test_last_segment_subtitle_cta_passes() -> None:
    plan = PlanData(
        mode="subtitle_flow",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="original", subtitle_text="金句"
            ),
            TimelineSegment(
                episode_id="ep1",
                start=3.0,
                end=6.0,
                audio="original",
                subtitle_text="后面更狠——点进去看全集",
            ),
        ],
    )
    assert defects(plan) == []
