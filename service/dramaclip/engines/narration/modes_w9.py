"""字幕金句流模式（原案 6.8）：原声保留 + 动态金句字幕为核心视觉元素。
"""

from __future__ import annotations

from dramaclip.engines.narration import casting
from dramaclip.engines.narration.beat_align import snap_window_end
from dramaclip.engines.narration.casting import (
    EpisodeScene,
    episode_order,
    has_dialogue,
    score_order,
    strongest_line,
)
from dramaclip.engines.narration.models import (
    PlanData,
    StrategySpec,
    TimelineSegment,
)

# 向后兼容的名字再导出：strongest_line 的实现搬进了 casting（A3 段长收缩要与
# 字幕选择看同一句话，口径只许有一处）。历史调用点 `from modes_w9 import
# strongest_line` 照常可用，但返回形状已扩展为 (text, span)。
__all__ = ["build_subtitle_flow", "strongest_line"]

_CTA_TEXT = "后面更狠——点进去看全集"
_CTA_FALLBACK_S = 3.0
_MAX_SCENES = 6
# B9 节拍吸附后的段长下限；与 A3 收缩下限（casting.SCENE_WINDOW_MIN_S）同口径。
_SNAP_MIN_LEN_S = casting.SCENE_WINDOW_MIN_S


def build_subtitle_flow(
    scenes: list[EpisodeScene],
    material: casting.MaterialByEpisode,
    strategy: StrategySpec,
    golden: dict[str, list[tuple[float, float]]] | None = None,
) -> PlanData:
    """金句流编排：top 场景按叙事顺序，每段字幕=该场景最强金句，结尾 CTA 卡片。

    A3 段长跟随台词：每段窗长 = `fit_scene_window`（台词 span + 0.5s 呼吸尾垫，
    收进 [2, 8]，不超场景边界；无台词保持 8s 满窗）。**B9 吸附排在收缩之后**——
    吸附是对最终 end 的微调，顺序颠倒会让卡点失效。
    """
    ranked = sorted(scenes, key=score_order)
    if material is not None:
        voiced = [scene for scene in ranked if has_dialogue(material, scene)]
        if len(voiced) >= 3:  # 金句流里混哑段=字幕放空炮；不足三条回退全候选
            ranked = voiced
    ranked = ranked[:_MAX_SCENES]
    picked = sorted(ranked, key=episode_order)

    segments: list[TimelineSegment] = []
    for scene in picked:
        dialogue = casting.dialogue_of(material, scene.episode_id)
        subtitle_text, span = strongest_line(scene, dialogue)
        # LLM 金句优先（2026-10-08 业主裁决「规则打分不可靠，LLM 提取」）：
        # 取与本场景窗口重叠最大的 LLM 金句行，字幕显示金句原文、窗长跟随它；
        # 无重叠金句 → 回退规则打分。LLM 原文来自台词编号回填，零编造。
        if golden is not None:
            episode_golden = golden.get(scene.episode_id) or []
            best: tuple[float, tuple[str, tuple[float, float]]] | None = None
            for g_start, g_end in episode_golden:
                overlap = min(g_end, scene.end) - max(g_start, scene.start)
                if overlap <= 0:
                    continue
                matched = next(
                    (
                        seg
                        for seg in dialogue
                        if seg.start == g_start and seg.end == g_end
                    ),
                    None,
                )
                if matched is None:
                    continue
                if best is None or overlap > best[0]:
                    best = (overlap, (matched.text.strip(), (g_start, g_end)))
            if best is not None:
                subtitle_text, span = best[1]
        # 窗长=场景自然边界，**不做台词收缩**（2026-10-27 业主实锤「27 秒的简直是
        # 垃圾」）：fit_scene_window 的收缩公式是给交叉原声拍治「台词说完画面空挂」
        # 的——金句流的画面里原声一直在播，不存在空挂；按台词长度收进 [2,8]s 的
        # 结果是每句 2-4 秒幻灯片快切，字幕读完就跳、原声对白被拦腰（真机
        # b88bc26f：六窗 2.0/2.0/2.5/2.9/4.1/7.5s，全片仅 26.7s）。
        # A3 锚定修正保留：起点跟台词走（最强台词在场景中后段时，旧实现锚镜头
        # 边界会让窗尾落在句中甚至句前——字幕放金句、原声里没这句）。
        head = (
            max(scene.start, min(span[0] - 0.4, scene.end - 2.0))
            if span is not None
            else scene.start
        )
        raw_start, raw_end = head, scene.end
        start = round(raw_start, 3)
        end = round(raw_end, 3)
        # B9 节拍吸附：end 是「起点+收缩后段长」的任意点（不是镜头边界），该集有
        # 拍点就微调到最近拍上（卡点优先质量线）。start 不动——它是镜头切换语义点。
        # 导出层 jitter.safe_times 为避台词还可能再挪 ±0.3s：台词保护 > 节拍，
        # 意图点被挪走是可接受代价（见 beat_align 模块 docstring）。
        end = round(
            snap_window_end(
                start,
                end,
                casting.beats_of(material, scene.episode_id),
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
                subtitle_text=subtitle_text,
            )
        )

    # 结尾 CTA 卡片段（复用最后场景尾部画面，climax 居中字幕）。
    # CTA 不吸附、不随台词收缩：收尾引导有自己的节奏（定长卡），不跟音乐拍走。
    # narration_id="cta-1" 是渲染期「重播白名单」标记（pipeline._patch_timeline）：
    # 设计语义=复用末场景尾帧压 CTA 字幕，占位重叠窗按原样保留、不被游标顶走。
    if picked:
        last = picked[-1]
        segments.append(
            TimelineSegment(
                episode_id=last.episode_id,
                start=round(max(last.end - _CTA_FALLBACK_S, last.start), 3),
                end=round(last.end, 3),
                audio="original",
                narration_id="cta-1",
                subtitle_text=_CTA_TEXT,
            )
        )
    return PlanData(mode="subtitle_flow", timeline=segments, strategy=strategy)
