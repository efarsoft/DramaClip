"""engines.narration.modes：编排纯函数。"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes import build_intro, build_raw_clip
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from tests.engines.narration.conftest import assert_slots_paired

_STRATEGY = StrategySpec()


def _scenes() -> list[ConflictScore]:
    return [
        ConflictScore(scene_index=0, start=0, end=6, score=80),
        ConflictScore(scene_index=1, start=6, end=12, score=40),
        ConflictScore(scene_index=2, start=12, end=18, score=85),
        ConflictScore(scene_index=3, start=18, end=24, score=50),
        ConflictScore(scene_index=4, start=24, end=30, score=90),
        ConflictScore(scene_index=5, start=30, end=36, score=45),
        ConflictScore(scene_index=6, start=36, end=42, score=72),
    ]


def test_raw_clip_opens_with_highest_conflict() -> None:
    plan = build_raw_clip(stamp([(1, "ep1", _scenes())]), [], _STRATEGY)
    assert plan.mode == "raw_clip"
    assert plan.timeline[0].start == 24 and plan.timeline[0].end == 30, "开场应为冲突最高场景"
    starts = [seg.start for seg in plan.timeline[1:]]
    assert starts == sorted(starts), "开场预告式前置，其余按原片时间线"
    total = sum(seg.end - seg.start for seg in plan.timeline)
    assert total >= 24, "冲突够的场景要讲完，不再按 30s 预算腰斩"


def test_raw_clip_all_original_audio() -> None:
    plan = build_raw_clip(stamp([(1, "ep1", _scenes())]), [], _STRATEGY)
    assert all(seg.audio == "original" for seg in plan.timeline)


def test_intro_marks_first_segment_as_narration() -> None:
    plan = build_intro(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert plan.mode == "intro_narration"
    assert_slots_paired(plan, "intro_narration")
    assert plan.timeline[0].narration_id == "intro-1"
    assert plan.timeline[0].audio == "narration"
    assert plan.timeline[0].end - plan.timeline[0].start <= 30
    assert plan.timeline[-1].narration_id == "cta-1"
    assert plan.timeline[-1].audio == "narration"
    assert all(seg.audio == "original" for seg in plan.timeline[1:-1])


def test_intro_opens_with_highest_conflict() -> None:
    """B 项：片头画面=最高冲突镜（与 raw_clip 同构的预告式开场）。

    信息流里用户先看到画面：旁白讲「最大冲突」而画面是时间序的平淡开场
    就是音画各说各话。_scenes() 最高分 90 在 24-30s。
    """
    plan = build_intro(stamp([(1, "ep1", _scenes())]), _STRATEGY)
    assert plan.timeline[0].start == 24 and plan.timeline[0].end == 30
    # 其余段保持时间序（预告式开场：先闪高潮、再回叙事）
    starts = [seg.start for seg in plan.timeline[1:-1]]
    assert starts == sorted(starts)


def test_intro_keeps_order_when_first_scene_is_already_the_best() -> None:
    """最高冲突镜本就是时间序第一镜：不重排（`is` 身份比较，与 raw_clip 同判据）。"""
    scenes = [
        ConflictScore(scene_index=0, start=0, end=6, score=95),
        ConflictScore(scene_index=1, start=6, end=12, score=40),
        ConflictScore(scene_index=2, start=12, end=18, score=85),
    ]
    plan = build_intro(stamp([(1, "ep1", scenes)]), _STRATEGY)
    assert plan.timeline[0].start == 0


def test_intro_teaser_swap_survives_a_scene_index_collision() -> None:
    """跨集 `scene_index` 碰撞：最高分在 ep2 且 index 与 ep1 首镜相同，
    按 index 比较会误认「开场已是最高分」而不前置——必须按身份前置。"""
    scenes = stamp(
        [
            (1, "ep1", [ConflictScore(scene_index=1, start=0.0, end=8.0, score=60)]),
            (2, "ep2", [ConflictScore(scene_index=1, start=30.0, end=40.0, score=95)]),
        ]
    )
    plan = build_intro(scenes, _STRATEGY)
    assert plan.timeline[0].episode_id == "ep2"
    assert plan.timeline[0].start == 30


def test_intro_empty_scenes() -> None:
    """无素材 ⇒ 无槽位：否则等于叫编剧对着空时间轴凭空写。"""
    plan = build_intro([], _STRATEGY)
    assert plan.timeline == [] and plan.narration_texts == []


def test_highlights_not_required() -> None:
    plan = build_raw_clip(
        stamp([(1, "ep1", _scenes())]),
        [HighlightSegment(start=0, end=6, score=80)],
        _STRATEGY,
    )
    assert plan.timeline


def test_build_plan_refuses_dialogue_rule_arrangement() -> None:
    """剧情解说只走剧本链：规则编排这条路已封死，误闯必须当场报错而不是出一版。"""
    with pytest.raises(ValueError, match="剧本驱动"):
        pipeline.build_plan(
            "dialogue_narration", stamp([(1, "ep1", _scenes())]), [], {}, {}
        )


def test_highlight_cut_uniform_clips_chronological_best_first() -> None:
    """高光混剪（预告形态）：冲突分头部 × 5 秒快切，时间序叙事、最高分前置。

    零解说零 TTS，BGM 床由 selector 按主导情绪选曲（should_add_bgm 默认开）。
    """
    from dramaclip.engines.narration.modes import build_highlight_cut

    scenes = stamp([(1, "ep1", _scenes()), (2, "ep2", _scenes())])
    plan = build_highlight_cut(scenes, _STRATEGY)
    assert plan.mode == "highlight_cut"
    assert plan.narration_texts == [], "预告形态零解说零 TTS"
    assert len(plan.timeline) == 14, "条数上限 15（夹具 14 场全取）"
    episodes_order = [s.episode_id for s in plan.timeline]
    assert episodes_order == sorted(episodes_order), "跨集按时间序（预告叙事）"
    first = plan.timeline[0]
    assert (first.start, first.end) == (24.5, 29.5), "score=90 场景居首，取中点 5 秒"
    assert all(
        s.end - s.start <= 5.0 + 1e-6 for s in plan.timeline
    ), "单条 ≤5 秒（短场景取全长）"


def test_highlight_cut_via_build_plan_dispatches() -> None:
    """build_plan 分发冒烟：apply_transitions 后保结构（条数可为转场后处理值）。"""
    plan = pipeline.build_plan(
        "highlight_cut",
        stamp([(1, "ep1", _scenes()), (2, "ep2", _scenes())]),
        [],
        {},
        {},
    )
    assert plan.mode == "highlight_cut"
    assert len(plan.timeline) >= 12, "快切预告形态：≥12 条高能切片"
    assert plan.narration_texts == []


def test_highlight_cut_skips_degenerate_scenes() -> None:
    """零长度场景跳过，不产出负/零长段。"""
    from dramaclip.engines.semantic.models import ConflictScore

    plan = pipeline.build_plan(
        "highlight_cut",
        stamp([(1, "ep1", [ConflictScore(scene_index=0, start=5.0, end=5.0, score=90)])]),
        [],
        {},
        {},
    )
    assert plan.timeline == []
