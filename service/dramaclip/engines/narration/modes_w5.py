"""W5 模式编排：交叉解说（原案 6.3）与超短悬念版（原案 6.9）。

编排只产出画面结构与旁白槽位，文案一律由 narration.copywriter 生成（无模板兜底）。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import ConflictScore

_CROSS_SCENE_S = 8.0        # 交叉解说单场景原声段基准时长
_CROSS_MAX_S = 120.0
_HOOK_TTS_FALLBACK_S = 4.0  # TTS 时长回填前的保守估算
_ULTRA_CONFLICT_S = 8.0     # 超短版冲突画面时长


def build_cross(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """交叉解说：场景原声与旁白交替；旁白压住下一场景开头，承担串联与悬念。

    时间轴：场景1(原声) → 旁白1 → 场景2(原声) → 旁白2 → …（旁白段画面延续下一场景）。
    """
    ranked = sorted(scenes, key=lambda s: -s.score)
    picked = sorted(ranked[:6], key=lambda s: s.start)  # 取 top 6 按时间线
    if not picked:
        return PlanData(mode="cross_narration", strategy=strategy)

    segments: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    budget = min(strategy.max_duration_s, _CROSS_MAX_S)
    used = 0.0
    for index, scene in enumerate(picked):
        duration = min(scene.end - scene.start, _CROSS_SCENE_S)
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=round(scene.start + duration, 3),
                audio="original",
            )
        )
        used += duration
        if used >= budget:
            break
        # 场景间插入旁白段（画面延续到下一场景开头；末尾场景后用本场景尾部）
        anchor = picked[index + 1] if index + 1 < len(picked) else scene
        narration_seconds = _HOOK_TTS_FALLBACK_S
        slot_id = f"cross-{index + 1}"
        texts.append(
            NarrationText(
                id=slot_id,
                brief="原声片段之间的串联：承接上一幕，给下一幕留半句钩",
            )
        )
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(anchor.start, 3),
                end=round(anchor.start + narration_seconds, 3),
                audio="narration",
                narration_id=slot_id,
            )
        )
        used += narration_seconds
    return PlanData(
        mode="cross_narration", timeline=segments, narration_texts=texts, strategy=strategy
    )


def build_ultra_short(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """超短悬念版（10-20s）：钩子旁白 → 最高冲突原声画面 → 收尾引导。"""
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    best = max(scenes, key=lambda s: s.score)
    scene_span = min(best.end - best.start, _ULTRA_CONFLICT_S)
    texts = [
        NarrationText(id="hook-1", brief="开场钩子：一句，最大反差或最狠的悬念，不超过 20 字"),
        NarrationText(
            id="cta-1",
            brief="收尾引导：一句，指向「结局更狠」并引导点击，不超过 15 字",
        ),
    ]
    timeline = [
        TimelineSegment(
            episode_id=episode_id,
            start=round(best.start, 3),
            end=round(best.start + _HOOK_TTS_FALLBACK_S, 3),
            audio="narration",
            narration_id=texts[0].id,
        ),
        TimelineSegment(
            episode_id=episode_id,
            start=round(best.start, 3),
            end=round(best.start + scene_span, 3),
            audio="original",
        ),
        TimelineSegment(
            episode_id=episode_id,
            start=round(best.end - _HOOK_TTS_FALLBACK_S, 3),
            end=round(best.end, 3),
            audio="narration",
            narration_id=texts[1].id,
        ),
    ]
    return PlanData(
        mode="ultra_short_hook", timeline=timeline, narration_texts=texts, strategy=strategy
    )
