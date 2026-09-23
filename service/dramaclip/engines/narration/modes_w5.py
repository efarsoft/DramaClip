"""W5 模式编排：交叉解说（原案 6.3）与超短悬念版（原案 6.9）。
"""

from __future__ import annotations

from dramaclip.engines.narration.beat_align import snap_window_end
from dramaclip.engines.narration.casting import (
    EpisodeScene,
    MaterialByEpisode,
    beats_of,
    episode_order,
    fit_scene_window,
    score_order,
    strongest_span_of,
)
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)

_HOOK_TTS_FALLBACK_S = 4.0  # TTS 时长回填前的保守估算
# 节拍吸附后的段长下限（B9）；与 A3 收缩下限同口径（casting.SCENE_WINDOW_MIN_S）。
_SNAP_MIN_LEN_S = 2.0


def build_cross(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
    material: MaterialByEpisode | None = None,
) -> PlanData:
    """交叉解说：场景原声与旁白交替；旁白压住下一场景开头，承担串联与悬念。

    `material`（B9）只为节拍吸附而来，可选：不传 / 缺该集键 / beats 空时计划与
    之前逐字节一致。原声段 end=起点+8s 是任意点，有拍点就吸附；**旁白段不吸附**
    ——它的 end 是 TTS 实测回填前的占位（批次一逻辑），吸附它会被回填覆盖，
    没有意义。规划层吸附是意图点：导出层 jitter.safe_times 为避台词还可能再挪
    ±0.3s（台词保护 > 节拍，见 beat_align 模块 docstring）。
    """
    ranked = sorted(scenes, key=score_order)
    picked = sorted(ranked[:6], key=episode_order)  # 取 top 6 按叙事顺序
    if not picked:
        return PlanData(mode="cross_narration", strategy=strategy)

    segments: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        # A3：原声窗长跟随该场景最强金句的台词 span（+呼吸尾垫，收进 [2,8]，
        # 不超场景边界；无台词保持 8s 满窗）。**吸附排在收缩之后**——见 casting.fit_scene_window。
        duration = fit_scene_window(
            scene.end - scene.start, strongest_span_of(material, scene)
        )
        start = round(scene.start, 3)
        end = round(
            snap_window_end(
                start,
                round(scene.start + duration, 3),
                beats_of(material, scene.episode_id),
                min_len=_SNAP_MIN_LEN_S,
            ),
            3,
        )
        segments.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=start,
                end=end,
                audio="original",
            )
        )
        # 场景间插入旁白段（画面延续到下一场景开头；末尾场景后用本场景尾部）
        anchor = picked[index + 1] if index + 1 < len(picked) else scene
        narration_seconds = _HOOK_TTS_FALLBACK_S
        slot_id = f"cross-{index + 1}"
        texts.append(
            NarrationText(
                id=slot_id,
                brief="原声片段之间的串联：承接上一幕，给下一幕留半句钩"
                if index + 1 < len(picked)
                else "收尾：留缺口，一句指向看全集，禁止关注/点赞",
            )
        )
        segments.append(
            TimelineSegment(
                # 集号跟**锚点**走，不跟上一段的 scene 走：这一段画面就是 anchor 的开头。
                # 沿用 scene.episode_id 会让渲染去另一集的同一秒取画面（`export_plan`
                # 按 segment.episode_id 查 episode_paths），出错片而不报错。
                episode_id=anchor.episode_id,
                start=round(anchor.start, 3),
                end=round(anchor.start + narration_seconds, 3),
                audio="narration",
                narration_id=slot_id,
            )
        )
    return PlanData(
        mode="cross_narration", timeline=segments, narration_texts=texts, strategy=strategy
    )


def build_ultra_short(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
    material: MaterialByEpisode | None = None,
) -> PlanData:
    """超短悬念版（10-20s）：钩子旁白 → 最高冲突原声画面 → 收尾引导。

    `material`（B9）只为节拍吸附而来，可选，降级同 `build_cross`。冲突窗口
    end=起点+8s 是任意点，有拍点就吸附；**hook 段与 CTA 段不吸附**——两段都是
    旁白，段长由 TTS 实测回填，规划期的 end 只是占位。
    """
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    # `min(score_order)` 而不是 `max(key=score)`：后者在同分时取**输入顺序**的第一个，
    # 而输入顺序来自 episodes_repo.list_by_project，没有契约（活库实测 333 个场景只有
    # 19 个不同分值）。score_order 已带 (集号, 起点, scene_index) 三个次键。
    best = min(scenes, key=score_order)
    # A3：冲突窗长跟随该场景最强金句的台词 span；口径与 cross/金句流同一处真相
    # （casting.fit_scene_window）。**吸附排在收缩之后**。
    scene_span = fit_scene_window(
        best.end - best.start, strongest_span_of(material, best)
    )
    conflict_start = round(best.start, 3)
    conflict_end = round(
        snap_window_end(
            conflict_start,
            round(best.start + scene_span, 3),
            beats_of(material, best.episode_id),
            min_len=_SNAP_MIN_LEN_S,
        ),
        3,
    )
    texts = [
        NarrationText(id="hook-1", brief="开场钩子：一句，最大反差或最狠的悬念，不超过 20 字"),
        NarrationText(
            id="cta-1",
            brief="收尾引导：一句，留缺口并指向看全集，不超过 15 字，禁止关注/点赞",
        ),
    ]
    timeline = [
        TimelineSegment(
            episode_id=best.episode_id,
            start=conflict_start,
            end=round(best.start + _HOOK_TTS_FALLBACK_S, 3),
            audio="narration",
            narration_id=texts[0].id,
        ),
        TimelineSegment(
            episode_id=best.episode_id,
            start=conflict_start,
            end=conflict_end,
            audio="original",
        ),
        TimelineSegment(
            episode_id=best.episode_id,
            start=round(best.end - _HOOK_TTS_FALLBACK_S, 3),
            end=round(best.end, 3),
            audio="narration",
            narration_id=texts[1].id,
        ),
    ]
    return PlanData(
        mode="ultra_short_hook", timeline=timeline, narration_texts=texts, strategy=strategy
    )
