"""九种解说模式的编排器（原案第六章）。W4：raw_clip + intro_narration。"""

from __future__ import annotations

from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment

# raw_clip 筛选（原案 6.7）：冲突≥70、单场景 3-25s
RAW_CLIP_MIN_SCORE = 70
_RAW_CLIP_MIN_S = 3.0
_RAW_CLIP_MAX_S = 25.0
_INTRO_MAX_S = 30.0  # 片头段保守时长（TTS 实际时长在导出时回填）


def build_raw_clip(
    episode_id: str,
    scenes: list[ConflictScore],
    highlights: list[HighlightSegment],
    strategy: StrategySpec,
) -> PlanData:
    """纯原片剪辑编排（原案 6.7）：开场最高冲突 → 时间线 → 截断。零加工（不遮罩）。"""
    candidates = [
        scene
        for scene in scenes
        if scene.score >= RAW_CLIP_MIN_SCORE
        and _RAW_CLIP_MIN_S <= scene.end - scene.start <= _RAW_CLIP_MAX_S
    ]
    # 分数不足时放宽到全部场景（按冲突分取头部，保证可用性）
    if len(candidates) < 3:
        ranked = sorted(scenes, key=lambda s: -s.score)[: max(3, len(highlights))]
        candidates = ranked

    ordered = sorted(candidates, key=lambda s: s.start)
    best = max(ordered, key=lambda s: s.score)
    if ordered[0].scene_index != best.scene_index:
        ordered.remove(best)
        ordered.insert(0, best)

    timeline = _fit_duration(episode_id, ordered, strategy)
    return PlanData(mode="raw_clip", timeline=timeline, strategy=strategy)


def build_intro(
    intro_episode_id: str,
    body_scenes: list[ConflictScore],
    strategy: StrategySpec,
    narration_text: str,
) -> PlanData:
    """片头解说编排（原案 6.4）：TTS 引子段（原声压低）+ 正片高光（原声）。

    片头段时长在导出阶段由 TTS 音频实际时长回填；此处先按保守值估算。
    """
    ordered = sorted(body_scenes, key=lambda s: s.start)
    timeline = _fit_duration(intro_episode_id, ordered, strategy, intro_first=True)
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[NarrationText(id="intro-1", text=narration_text)],
        strategy=strategy,
    )


def _fit_duration(
    episode_id: str,
    ordered: list[ConflictScore],
    strategy: StrategySpec,
    *,
    intro_first: bool = False,
) -> list[TimelineSegment]:
    """按时长目标截断：保留首尾场景，中间按时间线填充（叙事连贯：不打乱顺序）。"""
    budget = strategy.max_duration_s
    kept: list[ConflictScore] = []
    used = 0.0
    for index, scene in enumerate(ordered):
        is_edge = index == 0 or index == len(ordered) - 1
        duration = scene.end - scene.start
        if not is_edge and used + duration > budget:
            continue
        kept.append(scene)
        used += duration

    segments = [
        TimelineSegment(
            episode_id=episode_id,
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
