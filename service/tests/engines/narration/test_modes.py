"""engines.narration.modes：编排纯函数。"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes import build_highlight_cut, build_intro, build_raw_clip
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


def test_raw_clip_follows_episode_order() -> None:
    """真机 2026-10-20 业主否掉预告式前置：无解说模式里异集孤插开场=莫名其妙。

    纯时间序连播（邻接合并后），不再把最高冲突场景挪到最前——预告式开场需要
    旁白兜底（片头解说有），本模式卖点是「原声台词高光合集」。
    """
    plan = build_raw_clip(stamp([(1, "ep1", _scenes())]), [], _STRATEGY)
    assert plan.mode == "raw_clip"
    starts = [seg.start for seg in plan.timeline]
    assert starts == sorted(starts), "纯原片按原片时间线连播，无前置孤插"
    total = sum(seg.end - seg.start for seg in plan.timeline)
    assert total >= 24, "冲突够的场景要讲完，不再按 30s 预算腰斩"


def test_raw_clip_prefers_voiced_scenes_when_material_given() -> None:
    """「原声台词高光合集」不得选进哑段：material 可注入时过滤无台词场景。

    真机 2026-10-20：开场被排进 EP6 一段 3.6s 无台词动作戏（全剧最高分 78）。
    过滤后 voiced ≥3 才生效；不足三条回退全候选（可用性优先）。
    """
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=0.0, end=6.0, score=95),   # 哑段：应被过滤
        ConflictScore(scene_index=1, start=6.0, end=12.0, score=80),
        ConflictScore(scene_index=2, start=12.0, end=18.0, score=75),
        ConflictScore(scene_index=3, start=18.0, end=24.0, score=70),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[AsrSegment(start=6.0, end=24.0, text="有台词的段落")],
        )
    }
    plan = build_raw_clip(stamp([(1, "ep1", scenes)]), [], _STRATEGY, material)
    spans = [(seg.start, seg.end) for seg in plan.timeline]
    assert (0.0, 6.0) not in spans, "无台词的 95 分哑段不得入选"
    assert spans == [(6.0, 24.0)], "三条有声场景邻接合并成一个连续块"


def test_raw_clip_all_original_audio() -> None:
    plan = build_raw_clip(stamp([(1, "ep1", _scenes())]), [], _STRATEGY)
    assert all(seg.audio == "original" for seg in plan.timeline)


def test_raw_clip_window_boundaries_snap_to_sentence_bounds() -> None:
    """剪口不落在句子中间（业主 2026-10-27 立案：成品 14 窗 7 切句，还在说话就跳场）。

    止点切句收进整句（把话说完再跳）；起点切句退到句首（从话头听起）。
    """
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=6.0, end=12.0, score=90),
        ConflictScore(scene_index=1, start=18.0, end=24.0, score=85),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[
                AsrSegment(start=8.0, end=12.9, text="止点切句：收进整句"),
                AsrSegment(start=17.2, end=21.0, text="起点切句：退到句首"),
            ],
        )
    }
    plan = build_raw_clip(stamp([(1, "ep1", scenes)]), [], _STRATEGY, material)
    assert [(seg.start, seg.end) for seg in plan.timeline] == [
        (6.0, 12.9),  # 止点 12.0 切在 [8.0,12.9] 句中 → 延到句尾
        (17.2, 24.0),  # 起点 18.0 切在 [17.2,21.0] 句中 → 退到句首
    ]


def test_raw_clip_snap_yields_when_extension_hits_next_window() -> None:
    """收进整句会撞下一窗起点：止点退到句前（不切句也不侵占下一窗）。"""
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=6.0, end=12.0, score=90),
        ConflictScore(scene_index=1, start=14.2, end=19.0, score=85),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[AsrSegment(start=8.0, end=14.5, text="收进整句会撞下一窗")],
        )
    }
    plan = build_raw_clip(stamp([(1, "ep1", scenes)]), [], _STRATEGY, material)
    assert (plan.timeline[0].start, plan.timeline[0].end) == (6.0, 8.0)


def test_highlight_cut_filters_mutes_and_snaps_to_sentences() -> None:
    """高光混剪同款纪律（2026-10-27 审计）：哑段过滤 + 5 秒窗界吸附台词句边界。"""
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=0.0, end=6.0, score=95),  # 哑段
        ConflictScore(scene_index=1, start=6.0, end=12.0, score=80),
        ConflictScore(scene_index=2, start=12.0, end=18.0, score=75),
        ConflictScore(scene_index=3, start=18.0, end=24.0, score=70),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[
                AsrSegment(start=6.0, end=11.0, text="甲"),
                AsrSegment(start=11.5, end=17.0, text="乙"),
                AsrSegment(start=17.5, end=23.0, text="丙"),
            ],
        )
    }
    plan = build_highlight_cut(stamp([(1, "ep1", scenes)]), _STRATEGY, material)
    spans = [(seg.start, seg.end) for seg in plan.timeline]
    assert (0.0, 6.0) not in spans, "有声候选 ≥3 时哑段不得入选"
    # 几何取中窗 [6.5,11.5]… 起点 全部退到句首，剪口不切句
    assert spans == [(6.0, 11.5), (11.5, 17.5), (17.5, 23.5)]


def test_intro_filters_mute_body_scenes() -> None:
    """片头正片哑段过滤：最高冲突是无声动作戏也不得占黄金 3 秒后的第一段正片。"""
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=0.0, end=6.0, score=95),  # 哑段
        ConflictScore(scene_index=1, start=6.0, end=12.0, score=80),
        ConflictScore(scene_index=2, start=12.0, end=18.0, score=75),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[
                AsrSegment(start=6.0, end=11.0, text="甲"),
                AsrSegment(start=12.0, end=17.0, text="乙"),
            ],
        )
    }
    plan = build_intro(stamp([(1, "ep1", scenes)]), _STRATEGY, material)
    assert plan.timeline[0].audio == "narration"
    assert (plan.timeline[0].start, plan.timeline[0].end) == (6.0, 12.0), (
        "哑段被过滤后片头旁白落在第一个有声场景，不吸台词（渲染期实测重排）"
    )
    assert (plan.timeline[1].start, plan.timeline[1].end) == (12.0, 18.0)


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


def test_raw_clip_merges_adjacent_high_scores_into_one_block() -> None:
    """邻接合并：间隙 ≤1.5s 的相邻高分场景成连续块播放，块内不再跳场。

    跳场根源（真机 raw_clip 20 段 11 跳场）是纯冲突分排序让时间轴在相邻高分
    场景间横跳；合并后选中集不变、块边界只在真间隙处。
    """
    from dramaclip.engines.semantic.models import ConflictScore

    scenes = [
        ConflictScore(scene_index=0, start=0.0, end=6.0, score=85),   # ┐ 间隙 0：合并
        ConflictScore(scene_index=1, start=6.0, end=12.0, score=90),  # ┘
        ConflictScore(scene_index=2, start=20.0, end=26.0, score=88),  # 间隙 8s：独立成段
    ]
    plan = build_raw_clip(stamp([(1, "ep1", scenes)]), [], _STRATEGY)
    assert [(seg.start, seg.end) for seg in plan.timeline] == [
        (0.0, 12.0),  # 相邻两场景合成的连续块
        (20.0, 26.0),
    ], "相邻高分合并成块，块内零跳场；真间隙处保留分段节奏"
    assert len(plan.timeline) == 2, "三条候选合并为两块，选中集一秒不少"


def test_raw_clip_extends_openings_over_discourse_connectives() -> None:
    """因果接缝的剪辑版（业主 2026-10-28 实锤「没有原因，就到所以了么」）：
    下一窗首句以「所以」开头时，向前扩窗把前因句包进来，非连接词句即停。"""
    from dramaclip.engines.analysis.models import AsrSegment
    from dramaclip.engines.narration.casting import EpisodeMaterial

    scenes = [
        ConflictScore(scene_index=0, start=30.0, end=35.0, score=90),
        ConflictScore(scene_index=1, start=38.0, end=44.0, score=85),
    ]
    material = {
        "ep1": EpisodeMaterial(
            number=1,
            asr=[
                AsrSegment(start=30.7, end=31.5, text="首富之子汪大少要结婚了"),
                AsrSegment(start=31.6, end=34.5, text="我作为未婚妻，不该过来看看吗"),
                AsrSegment(start=35.0, end=36.5, text="你猜他为了谁悔婚"),
                AsrSegment(start=36.6, end=38.5, text="就是为了我们家的生意"),
                AsrSegment(
                    start=38.8, end=40.9,
                    text="所以，跟你这位江城第一总裁的婚约，也自动取消了",
                ),
            ],
        )
    }
    plan = build_raw_clip(stamp([(1, "ep1", scenes)]), [], _STRATEGY, material)
    windows = [(seg.start, seg.end) for seg in plan.timeline if seg.audio == "original"]
    assert windows[1][0] == 36.6, (
        f"「所以」窗该回溯前因到 36.6s（非连接词句「就是为了…」包进来即停），"
        f"实得 {windows}"
    )
    assert windows[1][1] == 44.0  # 窗尾=场景自然边界，不随台词收缩
