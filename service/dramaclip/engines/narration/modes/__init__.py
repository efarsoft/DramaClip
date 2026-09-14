"""九种解说模式的编排器（原案第六章）。W4：raw_clip + intro_narration。
"""

from __future__ import annotations

from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import HighlightSegment

# raw_clip 筛选（原案 6.7）：冲突≥70、单场景 3-25s
RAW_CLIP_MIN_SCORE = 70
_RAW_CLIP_MIN_S = 3.0
_RAW_CLIP_MAX_S = 25.0
_INTRO_MAX_S = 30.0  # 片头段保守时长（TTS 实际时长在导出时回填）
_INTRO_SLOT_ID = "intro-1"


def build_raw_clip(
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    strategy: StrategySpec,
) -> PlanData:
    """纯原片剪辑编排（原案 6.7）：开场最高冲突 → 时间线 → 截断。零加工（不遮罩）。"""
    if not scenes:
        return PlanData(mode="raw_clip", strategy=strategy)
    candidates = [
        scene
        for scene in scenes
        if scene.score >= RAW_CLIP_MIN_SCORE
        and _RAW_CLIP_MIN_S <= scene.end - scene.start <= _RAW_CLIP_MAX_S
    ]
    # 分数不足时放宽到全部场景（按冲突分取头部，保证可用性）
    if len(candidates) < 3:
        ranked = sorted(scenes, key=score_order)[: max(3, len(highlights))]
        candidates = ranked

    ordered = sorted(candidates, key=episode_order)
    best = max(ordered, key=lambda s: s.score)
    # 身份比较用 `is`，不用 `scene_index`：scene_index 只在**一集内**唯一，
    # 第 1 集的第 4 个场景与第 5 集的第 4 个场景 index 相同，跨集时按 index 判
    # 会认定"开场已经是最高冲突"而不前置。
    if ordered[0] is not best:
        ordered.remove(best)
        ordered.insert(0, best)

    timeline = _fit_duration(ordered, strategy)
    return PlanData(mode="raw_clip", timeline=timeline, strategy=strategy)


def build_intro(
    body_scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """片头解说编排（原案 6.4）：引子旁白段（画面为正文首镜）+ 正片高光（原声）。
    """
    ordered = sorted(body_scenes, key=episode_order)
    timeline = _fit_duration(ordered, strategy, intro_first=True)
    if not timeline:
        return PlanData(mode="intro_narration", timeline=timeline, strategy=strategy)
    timeline[0] = timeline[0].model_copy(update={"narration_id": _INTRO_SLOT_ID})
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[
            NarrationText(
                id=_INTRO_SLOT_ID,
                brief="片头钩子：两三句把最大冲突抛出来，收尾留悬念，不要复述剧情梗概",
            )
        ],
        strategy=strategy,
    )


def _fit_duration(
    ordered: list[EpisodeScene],
    strategy: StrategySpec,
    *,
    intro_first: bool = False,
) -> list[TimelineSegment]:
    """按时长目标截断：首场景无条件保留，其余在预算内按叙事顺序填充（不打乱顺序）。
    """
    # 片头解说要在预算里**预留**引子槽位的最坏长度：段长是 TTS 回填时才定的
    # （`pipeline.synthesize_narration_texts` 把段 end 改成 start + 实测音频时长），
    # 编排期只知道 `_INTRO_MAX_S` 这个保守估计。不预留就会两头都吃满预算：
    # 活库实测四集的一手给出 planned 298.80s，而 ep1 的引子实测音频 22.48s
    # （编排期只给它 5.17s），成片因此约 313s——顶穿 `strategy.max_duration_s`=300，
    # 而九模式门禁的时长断言正是 `duration_s > strategy.max_duration_s`。
    budget = strategy.max_duration_s - (_INTRO_MAX_S if intro_first else 0.0)
    kept: list[EpisodeScene] = []
    used = 0.0
    for index, scene in enumerate(ordered):
        duration = scene.end - scene.start
        if index != 0 and used + duration > budget:
            continue
        kept.append(scene)
        used += duration

    segments = [
        TimelineSegment(
            episode_id=scene.episode_id,
            start=round(scene.start, 3),
            end=round(scene.end, 3),
            audio="narration" if intro_first and index == 0 else "original",
        )
        for index, scene in enumerate(kept)
    ]
    if intro_first and segments:
        first = segments[0]
        segments[0] = first.model_copy(
            update={"end": round(min(first.end, first.start + _INTRO_MAX_S), 3)}
        )
    return segments
