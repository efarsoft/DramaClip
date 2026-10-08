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
_CTA_SLOT_ID = "cta-1"
_CTA_FALLBACK_S = 2.0


_HIGHLIGHT_CLIP_S = 5.0   # 高光混剪的单条时长（真机参考：13×5s ≈ 65s 预告）
_HIGHLIGHT_MAX_CLIPS = 15  # 条数上限：时长让位≠无限堆料，预告形态 75s 内最猛


def build_highlight_cut(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """高光混剪（预告形态）：全剧最高冲突场景 × 5 秒快切 + 配乐床，零解说。

    参考真机混剪流程：选段=冲突分头部、时长=统一 5 秒快切、顺序=时间序
    （预告叙事），冲突分最高的场景前置做开场；零 TTS 零字幕加工，
    BGM 床由 selector 按主导情绪选曲（should_add_bgm 默认开）。
    """
    if not scenes:
        return PlanData(mode="highlight_cut", strategy=strategy)
    ranked = sorted(scenes, key=score_order)[:_HIGHLIGHT_MAX_CLIPS]
    ordered = sorted(ranked, key=episode_order)
    best = max(ordered, key=lambda s: s.score)
    if ordered[0] is not best:
        ordered.remove(best)
        ordered.insert(0, best)
    timeline: list[TimelineSegment] = []
    for scene in ordered:
        span = scene.end - scene.start
        if span <= 0:
            continue
        if span <= _HIGHLIGHT_CLIP_S:
            start, end = scene.start, scene.end
        else:
            mid = (scene.start + scene.end) / 2
            start, end = mid - _HIGHLIGHT_CLIP_S / 2, mid + _HIGHLIGHT_CLIP_S / 2
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(start, 3),
                end=round(end, 3),
                audio="original",
            )
        )
    return PlanData(mode="highlight_cut", timeline=timeline, strategy=strategy)


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
    """片头解说编排（原案 6.4）：引子旁白段（画面为**最高冲突镜**）+ 正片高光（原声）。

    首帧选镜与 `build_raw_clip` 同构：信息流里用户先看到画面，片头旁白讲「最大冲突」
    而画面却是时间序的平淡开场就是音画各说各话（B 项）。故把冲突最高镜前置做首帧，
    其余按 `episode_order` 时间序——这是「预告式开场」（先闪高潮、再回叙事），与
    raw_clip 同款。前置用 `is` 身份比较不用 `scene_index`：scene_index 只在一集内
    唯一，跨集时按 index 判会误认「开场已是最高冲突」而不前置（见 build_raw_clip 注释）。
    全等分（max 取首个）时不前置，保持原时间序。
    """
    ordered = sorted(body_scenes, key=episode_order)
    if ordered:
        best = max(ordered, key=lambda s: s.score)
        if ordered[0] is not best:
            ordered.remove(best)
            ordered.insert(0, best)
    timeline = _fit_duration(ordered, strategy, intro_first=True)
    if not timeline:
        return PlanData(mode="intro_narration", timeline=timeline, strategy=strategy)
    timeline[0] = timeline[0].model_copy(update={"narration_id": _INTRO_SLOT_ID})
    last = timeline[-1]
    cta_start = round(max(last.start, last.end - _CTA_FALLBACK_S), 3)
    timeline.append(
        TimelineSegment(
            episode_id=last.episode_id,
            start=cta_start,
            end=round(last.end, 3),
            audio="narration",
            narration_id=_CTA_SLOT_ID,
        )
    )
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[
            NarrationText(
                id=_INTRO_SLOT_ID,
                brief="片头钩子：两三句把最大冲突抛出来，不要复述剧情梗概",
            ),
            NarrationText(
                id=_CTA_SLOT_ID,
                brief="收尾引导：一句，留缺口并指向看全集，不超过 15 字，禁止关注/点赞",
            ),
        ],
        strategy=strategy,
    )


def _fit_duration(
    ordered: list[EpisodeScene],
    strategy: StrategySpec,
    *,
    intro_first: bool = False,
) -> list[TimelineSegment]:
    """保留编排器已选出的场景；片长服从故事，不再按 max_duration 截断。

    片头解说仍把首段画面钳到 `_INTRO_MAX_S`（TTS 槽位估计，不是成片门禁）。
    """
    del strategy  # 软参考，编排器挑选场景时可读；这里不再用来砍轴
    segments = [
        TimelineSegment(
            episode_id=scene.episode_id,
            start=round(scene.start, 3),
            end=round(scene.end, 3),
            audio="narration" if intro_first and index == 0 else "original",
        )
        for index, scene in enumerate(ordered)
    ]
    if intro_first and segments:
        first = segments[0]
        segments[0] = first.model_copy(
            update={"end": round(min(first.end, first.start + _INTRO_MAX_S), 3)}
        )
    return segments
