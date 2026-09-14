"""字幕金句流模式（原案 6.8）：原声保留 + 动态金句字幕为核心视觉元素。

双通道信息传递——有声听对白，静音看字幕。每入选场景取最强一句金句作为该段字幕
（高潮句触发 climax 居中大字 + 情绪配色），结尾追加 CTA 卡片段。
原片字幕遮罩自动施加（非零加工模式）。
场景表带集身份（`casting.EpisodeScene`），台词表按集分开（`casting.MaterialByEpisode`）。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.line_scoring import score_line
from dramaclip.engines.narration.models import (
    PlanData,
    StrategySpec,
    TimelineSegment,
)

_CTA_TEXT = "结局太爽了！点下方看全集 →"
_FLOW_SCENE_S = 8.0
_CTA_FALLBACK_S = 3.0
_MAX_SCENES = 6


def strongest_line(
    scene: EpisodeScene,
    segments: list[AsrSegment],
) -> str | None:
    """场景内最强金句：冲突/情绪词密度最高的对白；无对白返回 None。

    `segments` 必须是**这一集**的台词表：start/end 是集内相对秒，活库实测十集的场景
    起点全部从 0.0 开始，拿摊平的表按秒过滤会捞到别的集的句子——字幕上出现一句
    这一集没人说过的话，而它逐字来自本剧，肉眼与耳朵都查不出来。
    """
    inside = [
        segment
        for segment in segments
        if segment.start < scene.end and segment.end > scene.start
    ]
    if not inside:
        return None
    best_text, best_score = None, -1
    for segment in inside:
        duration = segment.end - segment.start
        score = score_line(segment.text, duration)
        if score > best_score:
            best_text, best_score = segment.text, score
    return best_text


def build_subtitle_flow(
    scenes: list[EpisodeScene],
    material: casting.MaterialByEpisode,
    strategy: StrategySpec,
) -> PlanData:
    """金句流编排：top 场景按叙事顺序，每段字幕=该场景最强金句，结尾 CTA 卡片。"""
    ranked = sorted(scenes, key=score_order)[:_MAX_SCENES]
    picked = sorted(ranked, key=episode_order)

    segments: list[TimelineSegment] = []
    for scene in picked:
        duration = min(scene.end - scene.start, _FLOW_SCENE_S)
        segments.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=round(scene.start + duration, 3),
                audio="original",
                subtitle_text=strongest_line(
                    scene, casting.dialogue_of(material, scene.episode_id)
                ),
            )
        )

    # 结尾 CTA 卡片段（复用最后场景尾部画面，climax 居中字幕）
    if picked:
        last = picked[-1]
        segments.append(
            TimelineSegment(
                episode_id=last.episode_id,
                start=round(max(last.end - _CTA_FALLBACK_S, last.start), 3),
                end=round(last.end, 3),
                audio="original",
                subtitle_text=_CTA_TEXT,
            )
        )
    return PlanData(mode="subtitle_flow", timeline=segments, strategy=strategy)
