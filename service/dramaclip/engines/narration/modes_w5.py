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
    SceneCandidate,
    StrategySpec,
    TimelineSegment,
)

_HOOK_TTS_FALLBACK_S = 4.0  # TTS 时长回填前的保守估算

# 超短钩子的画面预算（2026-10-06 业主裁决「保障素材时长，不裁」）：钩子/CTA 的
# 文案在规划期还没生成，窗口按预算预留整段画面；文案实测比预算长时由回填的
# 「起点前伸」吸收，短则硬切进下一拍——已选素材一秒不裁、一秒不重播。
_HOOK_BUDGET_S = 30.0  # ≈90 字 @ IndexTTS 实测 ~3 字/秒（真机 61 字 ≈ 20s）
_CTA_BUDGET_S = 15.0  # CTA 是公式句（真机 25 字 ≈ 8s），留 ~1.9× 余量
# 候选池深度：出片时按实测旁白时长从池里做最终选景（业主裁决「先出语音、再选画面」）
_ULTRA_POOL_SIZE = 6
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
    source_durations: dict[str, float] | None = None,
) -> PlanData:
    """超短悬念版：钩子旁白 → 最高冲突原声画面 → 收尾引导（时长由内容讲完为止，不设上限）。

    `material`（B9）只为节拍吸附而来，可选，降级同 `build_cross`。冲突窗口
    end=起点+8s 是任意点，有拍点就吸附；钩子/CTA 是旁白段，段长由 TTS 实测回填。

    三拍互不重叠、已选素材全保留（2026-10-06 业主裁决「保障素材时长，不裁」）：
    - 钩子压在冲突场景**之前**的素材上，尾锚在场景开头——讲完正好进正片；
    - 冲突原声拍原地不动：音画同源，挪了就对不上口型；
    - CTA 排在原声拍之后，按公式句长度预算预留画面。
    文案实测比预算长时由回填的「起点前伸」吸收，短则留硬切空隙，素材一秒不裁。

    `source_durations` 提供时做**可行性选景**：按分值序取第一个「场景前放得下
    钩子预算、集尾放得下 CTA 预算」的场景；全都放不下时退回最高分场景——
    回填守卫会给出如实的失败原因，不静默出坏片。
    """
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    # `min(score_order)` 而不是 `max(key=score)`：后者在同分时取**输入顺序**的第一个，
    # 而输入顺序来自 episodes_repo.list_by_project，没有契约（活库实测 333 个场景只有
    # 19 个不同分值）。score_order 已带 (集号, 起点, scene_index) 三个次键。
    ranked = sorted(scenes, key=score_order)

    def _conflict_window(scene: EpisodeScene) -> tuple[float, float]:
        """场景 → 冲突窗（最强台词 span 收缩 + 节拍吸附）。布局与候选池共用一处真相。"""
        span = fit_scene_window(scene.end - scene.start, strongest_span_of(material, scene))
        start = round(scene.start, 3)
        end = round(
            snap_window_end(
                start,
                round(scene.start + span, 3),
                beats_of(material, scene.episode_id),
                min_len=_SNAP_MIN_LEN_S,
            ),
            3,
        )
        return start, end

    best = next(
        (
            scene
            for scene in ranked
            if source_durations is not None
            and scene.start >= _HOOK_BUDGET_S
            and source_durations.get(scene.episode_id, 0.0)
            >= scene.end + _CTA_BUDGET_S
        ),
        ranked[0],
    )
    conflict_start, conflict_end = _conflict_window(best)
    # 吸引力是唯一标准（业主裁决：时长让位，不为短而短）——brief 只描述要达成
    # 的效果，不设字数锚。爆款节奏锚（抖音/快手公开复盘）：0-3s 生死线上第一句
    # 必须是身份反差/生死/数字冲击；4-8s 冲突递进；结尾撕新缺口不剧透最大反转。
    # 讲到「非点进去看不可」为止，长一点比薄一点强一百倍（薄 = 6 秒残件，实测）。
    texts = [
        NarrationText(
            id="hook-1",
            brief=(
                "开场钩子：把最炸的反差放在第一句（身份错位/生死局/具体数字冲击，"
                "如「花几百万两杀妻」），随后每一句都把冲突往前推一层——句句有"
                "信息增量，禁止背景铺垫、概括性形容与同一句式复读；讲到冲突完全"
                "立住为止"
            ),
        ),
        NarrationText(
            id="cta-1",
            brief=(
                "收尾引导：先半句撕开新的缺口（绝不剧透最大反转），再行动引导"
                "「点击左下角，免费观看全集」或「立即观看全集」（可带剧名）；"
                "禁止空喊关注/点赞/收藏"
            ),
        ),
    ]
    timeline = [
        TimelineSegment(
            episode_id=best.episode_id,
            # 钩子尾锚在冲突场景开头：文案实测比预算长→回填起点前伸，短→硬切进正片。
            # 场景贴着集头、前面凑不出最小铺垫时退回旧占位形状（可行性选景会在
            # 有集时长时避开这种场景，这里是无时长兜底）。
            start=(
                round(conflict_start - _HOOK_BUDGET_S, 3)
                if conflict_start >= _HOOK_TTS_FALLBACK_S
                else conflict_start
            ),
            end=(
                conflict_start
                if conflict_start >= _HOOK_TTS_FALLBACK_S
                else round(conflict_start + _HOOK_TTS_FALLBACK_S, 3)
            ),
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
            start=conflict_end,
            end=round(conflict_end + _CTA_BUDGET_S, 3),
            audio="narration",
            narration_id=texts[1].id,
        ),
    ]
    # 候选池 = 分值序前 N 个场景的冲突窗（含已选那个）：出片时 TTS 实测旁白时长
    # 到手，布局阶段从这里挑第一个放得下的——「先出语音、再选画面」（业主裁决）。
    pool_scenes = ranked[:_ULTRA_POOL_SIZE]
    return PlanData(
        mode="ultra_short_hook",
        timeline=timeline,
        narration_texts=texts,
        strategy=strategy,
        scene_pool=[
            SceneCandidate(episode_id=scene.episode_id, start=start, end=end)
            for scene, (start, end) in (
                (scene, _conflict_window(scene)) for scene in pool_scenes
            )
        ],
    )
