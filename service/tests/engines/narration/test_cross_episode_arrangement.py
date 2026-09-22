"""六个规则编排器的跨集取材（规格 §1「每模式产出 1..K 条…跨集方案」）。

单集行为由各 `test_modes*.py` 守着；本文件只钉**跨集才存在**的那些性质。
每一条都对应一个真实的坏法，且每条都做过变异检查（见 Step 9）：

① 段的集号必须来自**它自己的场景**，不来自某个"这一条片属于哪一集"的入参
   ——否则渲染会去另一集的同一秒取画面（`export_plan` 按 `segment.episode_id`
   查 `episode_paths`），出错片而不报错；
② 叙事顺序是播出序（集号 → 集内起点），不是钟表序——活库实测十集的场景起点
   全部从 `0.0` 开始，按 start 排会把十集交错；
③ `_fit_duration` 的预算不得被末场景豁免顶穿——单集时代够不到预算（活库最大
   单集 204.2 场景秒 < `strategy.max_duration_s` 300），跨集两集就到 405.8；
④ `scene_index` 只在**一集内**唯一，跨集时用它做身份比较会认错场景；
⑤ `subtitle_flow` 的金句必须取自该场景**自己那一集**的台词表。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes import build_intro, build_raw_clip
from dramaclip.engines.narration.modes_p2 import build_dual_host, build_monologue
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.narration.modes_w9 import build_subtitle_flow
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

# 预算刻意给小：让"顶穿预算"这条在两三个场景上就能观察到，不必造几十集夹具
_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=30)
# intro 要另给一档：`_fit_duration` 在 intro_first 时会从预算里**预留** _INTRO_MAX_S=30s
# 给引子槽位（段长要等 TTS 回填才知道），30s 的预算会被预留吃光、只剩首场景。
_STRATEGY_INTRO = StrategySpec(min_duration_s=10, max_duration_s=90)


def _scene(index: int, start: float, score: int) -> ConflictScore:
    return ConflictScore(scene_index=index, start=start, end=start + 6.0, score=score)


def _two_episodes() -> list[casting.EpisodeScene]:
    """两集，**集内起点完全重合**（都从 0.0 开始）：这是活库的真实形状，不是刁钻构造。"""
    return stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 60), _scene(1, 10.0, 90)]),
            (2, "ep2", [_scene(0, 0.0, 95), _scene(1, 10.0, 40)]),
        ]
    )


def _material() -> casting.MaterialByEpisode:
    return {
        "ep1": casting.EpisodeMaterial(number=1, asr=[]),
        "ep2": casting.EpisodeMaterial(number=2, asr=[]),
    }


def test_every_builder_stamps_the_episode_of_each_segment() -> None:
    """六个编排器逐段盖自己场景的集号；两集都必须在时间轴上出现。"""
    scenes = _two_episodes()
    plans = {
        "raw_clip": build_raw_clip(scenes, [], _STRATEGY),
        "intro_narration": build_intro(scenes, _STRATEGY_INTRO),
        "cross_narration": build_cross(scenes, _STRATEGY),
        "ultra_short_hook": build_ultra_short(scenes, _STRATEGY),
        "full_narration": build_full(scenes, _STRATEGY),
        "dual_host_chat": build_dual_host(scenes, _STRATEGY),
        "inner_monologue": build_monologue(scenes, _STRATEGY),
        "subtitle_flow": build_subtitle_flow(scenes, _material(), _STRATEGY),
    }
    for mode, plan in plans.items():
        assert plan.timeline, f"{mode} 出了个空时间轴"
        used = {segment.episode_id for segment in plan.timeline}
        assert used <= {"ep1", "ep2"}, f"{mode} 盖了个不存在的集号：{used}"
        if mode == "ultra_short_hook":
            continue  # 单场景片，恒为一集；它自己的用例钉"取的是全剧最高分那一集"
        assert "ep2" in used, (
            f"{mode} 的时间轴里没有第 2 集——那不是跨集方案，是单集方案换了个说法"
        )


def test_ultra_short_is_a_single_scene_film_and_says_which_episode() -> None:
    """超短悬念版三个段压在同一个场景上，故恒为一集——但那一集必须是**全剧**最高分那集。

    规格 §1 要的是一条方案**可以**跨集取画面，不是每条方案**必须** ≥2 集。
    为跨集而把 15 秒的悬念版拆成两集，会毁掉这个模式的全部卖点（一个镜头一个反差）。
    """
    plan = build_ultra_short(_two_episodes(), _STRATEGY)
    assert {segment.episode_id for segment in plan.timeline} == {"ep2"}, (
        "95 分在 ep2，取的却是别的集"
    )
    assert len(plan.timeline) == 3


def test_ultra_short_breaks_a_cross_episode_score_tie_by_episode_number() -> None:
    """同分取**集号小**的那一集，而不是取输入顺序里的第一个。

    夹具把 ep2 排在输入的第一位、两集同为 95 分：`max(scenes, key=lambda s: s.score)`
    会返回输入顺序里的第一个（ep2），于是"整组重规划"两次可能取到不同的集——
    而输入顺序来自 `episodes_repo.list_by_project`，那个顺序没有契约。
    活库实测 333 个场景只有 19 个不同分值，同分不是边角情况。
    """
    tied = stamp(
        [
            (2, "ep2", [_scene(0, 0.0, 95)]),
            (1, "ep1", [_scene(0, 0.0, 95)]),
        ]
    )
    plan = build_ultra_short(tied, _STRATEGY)
    assert {segment.episode_id for segment in plan.timeline} == {"ep1"}, (
        "同分该按集号定序（取 ep1），实取的是输入顺序里的第一个"
    )


def test_segments_follow_broadcast_order_not_clock_order() -> None:
    """两集的 0.0s 是两段不同画面：先按集号、再按集内起点。

    按 start 排会得到 ep1@0、ep2@0、ep1@10、ep2@10 —— 十集这么交错出来的时间线
    谁也不是，而它不报错、不降级，成片看着像"剪得很碎"。
    """
    plan = build_full(_two_episodes(), _STRATEGY)
    assert [(segment.episode_id, segment.start) for segment in plan.timeline] == [
        ("ep1", 0.0),
        ("ep1", 10.0),
        ("ep2", 0.0),
        ("ep2", 10.0),
    ]


def test_fit_duration_keeps_story_past_budget() -> None:
    """片长服从故事：不再按 max_duration 砍轴。"""
    scenes = stamp(
        [
            (
                number,
                f"ep{number}",
                [_scene(index, index * 8.0, 90) for index in range(20)],
            )
            for number in (1, 2, 3)
        ]
    )
    strategy = StrategySpec(min_duration_s=10, max_duration_s=30)
    for mode, plan in (
        ("raw_clip", build_raw_clip(scenes, [], strategy)),
        ("intro_narration", build_intro(scenes, strategy)),
    ):
        total = sum(segment.end - segment.start for segment in plan.timeline)
        assert total > strategy.max_duration_s, f"{mode} 仍在按预算砍片：{total}s"


def test_intro_still_caps_the_hook_slot() -> None:
    """引子槽位画面仍钳在 _INTRO_MAX_S，但不为此丢掉后面的冲突。"""
    scenes = stamp(
        [
            (number, f"ep{number}", [_scene(index, index * 8.0, 90) for index in range(20)])
            for number in (1, 2, 3)
        ]
    )
    strategy = StrategySpec(min_duration_s=10, max_duration_s=300)
    plan = build_intro(scenes, strategy)
    assert plan.timeline[0].end - plan.timeline[0].start <= 30
    assert len(plan.timeline) == 61
    assert plan.timeline[-1].narration_id == "cta-1"


def test_intro_keeps_its_slot_when_the_first_scene_alone_exceeds_the_budget() -> None:
    """首场景仍然无条件保留：`intro_narration` 的旁白槽位挂在它上面，丢了就没有解说。"""
    scenes = stamp([(1, "ep1", [ConflictScore(scene_index=0, start=0.0, end=90.0, score=90)])])
    plan = build_intro(scenes, StrategySpec(min_duration_s=10, max_duration_s=30))
    assert len(plan.timeline) == 2
    assert plan.timeline[0].narration_id == "intro-1"
    assert plan.timeline[-1].narration_id == "cta-1"
    assert_slots_paired(plan, "intro_narration")


def test_raw_clip_best_first_swap_survives_a_scene_index_collision() -> None:
    """`scene_index` 只在一集内唯一：跨集时按 index 判"开场是不是最高分"会认错场景。

    夹具让两集都有一个 `scene_index=1` 的场景，且最高分那个在 ep2：
    按 index 比较的实现会认定"开场已经是最高分"而不前置，按身份比较才会换。
    """
    scenes = stamp(
        [
            (1, "ep1", [_scene(1, 0.0, 72), _scene(2, 10.0, 75)]),
            (2, "ep2", [_scene(1, 0.0, 99)]),
        ]
    )
    plan = build_raw_clip(scenes, [], _STRATEGY)
    first = plan.timeline[0]
    assert first.episode_id == "ep2" and first.start == 0.0, (
        f"开场应为全剧最高冲突（ep2@0.0，99 分），实得 {first.episode_id}@{first.start}"
    )


def test_cross_narration_segment_carries_the_anchor_episode() -> None:
    """旁白段的画面延续到**下一个场景**，故它的集号必须是锚点的集号。

    沿用上一个原声段的集号会让渲染去另一集的同一秒取画面——`export_plan` 按
    `segment.episode_id` 查 `episode_paths`，查得到、只是查错了，于是不报错地出错片。
    """
    scenes = stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 95)]),
            (2, "ep2", [_scene(0, 0.0, 90)]),
        ]
    )
    plan = build_cross(scenes, _STRATEGY)
    narration_segments = [s for s in plan.timeline if s.audio == "narration"]
    assert narration_segments, "夹具前提塌了：交叉解说必须有旁白段"
    for segment in narration_segments:
        assert segment.episode_id in {"ep1", "ep2"}
    # picked 按播出序是 [ep1@0, ep2@0]，故第一个旁白段的锚点是 ep2
    assert narration_segments[0].episode_id == "ep2", (
        f"旁白段该盖锚点（ep2）的画面，实得 {narration_segments[0].episode_id}"
    )


def test_subtitle_flow_takes_each_line_from_its_own_episode() -> None:
    """金句必须取自该场景**自己那一集**的台词表：两集秒轴重合时会捞到别集的句子。"""
    scenes = stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 95)]),
            (2, "ep2", [_scene(0, 0.0, 90)]),
        ]
    )
    material: casting.MaterialByEpisode = {
        "ep1": casting.EpisodeMaterial(
            number=1, asr=[AsrSegment(start=1.0, end=4.0, text="第一集的金句")]
        ),
        "ep2": casting.EpisodeMaterial(
            number=2, asr=[AsrSegment(start=1.0, end=4.0, text="第二集的金句")]
        ),
    }
    plan = build_subtitle_flow(scenes, material, _STRATEGY)
    # 按**段序号**取值，不按集号：末尾还有一个 CTA 卡片段复用最后一集的尾部画面，
    # 用 {episode_id: text} 收会把两个 ep2 段压成一个，断言就在读错的对象。
    lines = [(segment.episode_id, segment.subtitle_text) for segment in plan.timeline]
    assert lines == [
        ("ep1", "第一集的金句"),
        ("ep2", "第二集的金句"),
        ("ep2", "后面更狠——点进去看全集"),
    ], lines
