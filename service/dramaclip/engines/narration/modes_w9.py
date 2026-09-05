"""字幕金句流模式（原案 6.8）：原声保留 + 动态金句字幕为核心视觉元素。

双通道信息传递——有声听对白，静音看字幕。每入选场景取最强一句金句作为该段字幕
（高潮句触发 climax 居中大字 + 情绪配色），结尾追加 CTA 卡片段。
原片字幕遮罩自动施加（非零加工模式）。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration.models import (
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import ConflictScore

_CTA_TEXT = "结局太爽了！点下方看全集 →"
_FLOW_SCENE_S = 8.0
_CTA_FALLBACK_S = 3.0
_MAX_SCENES = 6


def strongest_line(
    scene: ConflictScore,
    segments: list[AsrSegment],
) -> str | None:
    """场景内最强金句：冲突/情绪词密度最高的对白；无对白返回 None。"""
    from dramaclip.engines.narration.dialogue_selector import score_line

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
    episode_id: str,
    scenes: list[ConflictScore],
    asr_segments: list[AsrSegment],
    strategy: StrategySpec,
) -> PlanData:
    """金句流编排：top 场景按时间线，每段字幕=该场景最强金句，结尾 CTA 卡片。"""
    ranked = sorted(scenes, key=lambda s: -s.score)[:_MAX_SCENES]
    picked = sorted(ranked, key=lambda s: s.start)

    segments: list[TimelineSegment] = []
    for scene in picked:
        duration = min(scene.end - scene.start, _FLOW_SCENE_S)
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=round(scene.start + duration, 3),
                audio="original",
                subtitle_text=strongest_line(scene, asr_segments),
            )
        )

    # 结尾 CTA 卡片段（复用最后场景尾部画面，climax 居中字幕）
    if picked:
        last = picked[-1]
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(max(last.end - _CTA_FALLBACK_S, last.start), 3),
                end=round(last.end, 3),
                audio="original",
                subtitle_text=_CTA_TEXT,
            )
        )
    return PlanData(mode="subtitle_flow", timeline=segments, strategy=strategy)
