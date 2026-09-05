"""W5 模式编排：交叉解说（原案 6.3）与超短悬念版（原案 6.9）。

文案均为模板降级（LLM 文案精修随 P1 后续接入）；
旁白段时长在导出阶段由 TTS 音频实际时长回填（同 intro 机制）。
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

# 旁白串联文案池（按位置取用；LLM 接入后替换）
_CROSS_NARRATIONS: tuple[str, ...] = (
    "故事，从这里开始变得不对劲。",
    "然而事情远没有这么简单。",
    "接下来的这一幕，让所有人都没想到。",
    "真正的好戏，现在才刚刚开场。",
    "命运的转折，就藏在这个决定里。",
    "所有的铺垫，都是为了这一刻。",
)


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
        narration_text = _CROSS_NARRATIONS[index % len(_CROSS_NARRATIONS)]
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(anchor.start, 3),
                end=round(anchor.start + narration_seconds, 3),
                audio="narration",
                subtitle_text=narration_text,
            )
        )
        texts.append(NarrationText(id=f"cross-{index + 1}", text=narration_text))
        used += narration_seconds
    return PlanData(
        mode="cross_narration", timeline=segments, narration_texts=texts, strategy=strategy
    )


def build_ultra_short(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
    project_name: str,
) -> PlanData:
    """超短悬念版（10-20s）：TTS 钩子 → 最高冲突原声画面 → TTS 收尾引导。

    三段画面均来自冲突分最高的场景（信息密度最高的几秒）。
    """
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    best = max(scenes, key=lambda s: s.score)
    scene_span = min(best.end - best.start, _ULTRA_CONFLICT_S)
    hook_text = f"{project_name}最炸裂的一段，看完整个人都是懵的"
    cta_text = "结局更狠，点下方看全集"

    timeline = [
        TimelineSegment(
            episode_id=episode_id,
            start=round(best.start, 3),
            end=round(best.start + _HOOK_TTS_FALLBACK_S, 3),
            audio="narration",
            subtitle_text=hook_text,
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
            subtitle_text=cta_text,
        ),
    ]
    texts = [
        NarrationText(id="hook-1", text=hook_text),
        NarrationText(id="cta-1", text=cta_text),
    ]
    return PlanData(
        mode="ultra_short_hook", timeline=timeline, narration_texts=texts, strategy=strategy
    )
