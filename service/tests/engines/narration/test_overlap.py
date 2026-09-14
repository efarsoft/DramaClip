"""取材重叠度量：源素材秒的 Jaccard。规格 §4.3 的 60% 安全阀。

夹具全是手搓的 PlanData（不跑编排器）：本模块是纯函数，把编排器拉进来只会让
「重叠算错了」与「编排变了」两种失败混在一起。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import overlap
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _plan(spans: list[tuple[str, float, float]], mode: str = "full_narration") -> PlanData:
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(episode_id=ep, start=start, end=end, audio="ducked")
            for ep, start, end in spans
        ],
    )


def test_identical_material_is_one() -> None:
    a = _plan([("ep1", 0.0, 10.0), ("ep1", 20.0, 30.0)])
    assert overlap.overlap(a, a) == pytest.approx(1.0)


def test_disjoint_material_is_zero() -> None:
    a = _plan([("ep1", 0.0, 10.0)])
    b = _plan([("ep1", 10.0, 20.0)])
    assert overlap.overlap(a, b) == 0.0


def test_same_seconds_in_different_episodes_do_not_overlap() -> None:
    """集号是取材身份的一部分：第 3 集的 0-10s 与第 7 集的 0-10s 是两段不同画面。"""
    a = _plan([("ep1", 0.0, 10.0)])
    b = _plan([("ep2", 0.0, 10.0)])
    assert overlap.overlap(a, b) == 0.0


def test_half_shared_gives_one_third() -> None:
    """并集 0-30（30s）、交集 10-20（10s）→ 1/3。Jaccard 不是「占其中一条的比例」。"""
    a = _plan([("ep1", 0.0, 20.0)])
    b = _plan([("ep1", 10.0, 30.0)])
    assert overlap.overlap(a, b) == pytest.approx(10.0 / 30.0)


def test_containment_is_not_reported_as_identical() -> None:
    """短片完全落在长片里：包含率会说 100%，Jaccard 说 20%——后者才对应观感。"""
    long_plan = _plan([("ep1", 0.0, 100.0)])
    short_plan = _plan([("ep1", 10.0, 30.0)])
    assert overlap.overlap(long_plan, short_plan) == pytest.approx(20.0 / 100.0)


def test_touching_segments_are_merged_before_measuring() -> None:
    """相邻段不得被数成两倍素材：不合并时 a 的「总秒数」会是 20 而实际只有 10。"""
    a = _plan([("ep1", 0.0, 5.0), ("ep1", 5.0, 10.0)])
    b = _plan([("ep1", 0.0, 10.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 10.0)]}
    assert overlap.overlap(a, b) == pytest.approx(1.0)


def test_overlapping_segments_within_one_plan_are_merged() -> None:
    a = _plan([("ep1", 0.0, 8.0), ("ep1", 4.0, 12.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 12.0)]}


def test_zero_length_segments_are_ignored() -> None:
    a = _plan([("ep1", 5.0, 5.0), ("ep1", 0.0, 10.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 10.0)]}


def test_both_empty_gives_zero_not_a_division_error() -> None:
    """两条都没画面：无从比起，不该判成「同一部片」，更不该抛 ZeroDivisionError。"""
    empty = PlanData(mode="raw_clip")
    assert overlap.overlap(empty, empty) == 0.0


def test_original_audio_segments_count_as_material() -> None:
    """取材与音频角色无关：raw_clip 全是 original 段，它照样有取材。"""
    a = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=10.0, audio="original")],
    )
    b = _plan([("ep1", 0.0, 10.0)], mode="raw_clip")
    assert overlap.overlap(a, b) == pytest.approx(1.0)


def test_limit_is_the_spec_value() -> None:
    """阈值是规格写死的数，不是可调旋钮：改它就是改规格，必须在这里红一次。"""
    assert overlap.OVERLAP_LIMIT == 0.60
