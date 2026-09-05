"""解说管线：分析结果 → 编排方案（raw_clip/intro）+ intro 的 TTS 引子合成。

LLM 文案未配置时用模板降级（W3 同策略）；TTS 用 edge（云端免费，无需本地模型）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines.narration import modes, modes_w5
from dramaclip.engines.narration.models import PlanData, StrategySpec
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.engines.tts import base as tts_base
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.infra.ffmpeg import probe

_MODE_LABELS = {"raw_clip": "纯原片剪辑", "intro_narration": "片头解说"}


def build_plan(
    mode: str,
    episode_id: str,
    conflict_scores: list[ConflictScore],
    highlights: list[HighlightSegment],
    audio_features_json: str | None,
    settings: dict[str, str],
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。"""
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "120")),
    )
    if mode == "raw_clip":
        return modes.build_raw_clip(episode_id, conflict_scores, highlights, strategy)
    if mode == "intro_narration":
        text = intro_text(conflict_scores, settings)
        return modes.build_intro(episode_id, conflict_scores, strategy, text)
    if mode == "cross_narration":
        return modes_w5.build_cross(episode_id, conflict_scores, strategy)
    if mode == "ultra_short_hook":
        return modes_w5.build_ultra_short(
            episode_id, conflict_scores, strategy, settings.get("_project_name", "这部剧")
        )
    raise ValueError(f"模式暂未支持: {mode}（{_MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


def intro_text(conflict_scores: list[ConflictScore], settings: dict[str, str]) -> str:
    """片头钩子文案：LLM 未配置时用模板降级（原案 6.4 引子 + 悬念收尾）。"""
    project_name = settings.get("_project_name", "这部剧")
    peak = max((scene.score for scene in conflict_scores), default=60)
    if peak >= 80:
        hook = f"{project_name}这段剧情，直接把冲突拉满了"
    else:
        hook = f"{project_name}的故事，从一场爆发开始"
    return f"{hook}。三分钟带你看完全过程，看到最后你绝对想不到。"


def synthesize_intro_tts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
) -> PlanData:
    """合成片头旁白音频并回填时长与首段结束时间（TTS 时长决定片头长度）。"""
    if not plan.narration_texts:
        return plan
    engine = create_tts(settings.get("tts.engine", "edge"))
    voice = settings.get("tts.voice", "")
    text_item = plan.narration_texts[0]
    audio_path = engine.synthesize(text_item.text, voice, work_dir / "intro_tts.mp3")
    duration = tts_base.audio_duration_s(audio_path)
    updated_texts = [dict(text_item.model_dump(), audio_path=str(audio_path), duration=duration)]
    timeline = [seg.model_dump() for seg in plan.timeline]
    if timeline:
        first = timeline[0]
        timeline[0]["end"] = round(min(first["end"], first["start"] + duration), 3)
    return plan.model_copy(
        update={"narration_texts": updated_texts, "timeline": timeline},
    )


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
) -> PlanData:
    """逐段合成旁白音频并回填 audio_path/duration；narration 段时长随 TTS 回填。"""
    if not plan.narration_texts:
        return plan
    engine = create_tts(settings.get("tts.engine", "edge"))
    voice = settings.get("tts.voice", "")
    updated: list[dict[str, Any]] = []
    for order, item in enumerate(plan.narration_texts):
        audio_path = engine.synthesize(item.text, voice, work_dir / f"{item.id}.mp3")
        duration = tts_base.audio_duration_s(audio_path)
        updated.append(dict(item.model_dump(), audio_path=str(audio_path), duration=duration))
        _ = order
    timeline = [segment.model_dump() for segment in plan.timeline]
    narration_order = 0
    for segment in timeline:
        if segment["audio"] != "narration" or narration_order >= len(updated):
            continue
        duration = float(updated[narration_order]["duration"] or 0)
        if duration > 0:
            segment["end"] = round(segment["start"] + duration, 3)
        narration_order += 1
    return plan.model_copy(update={"narration_texts": updated, "timeline": timeline})


def segment_source_map(episodes: list[dict[str, Any]]) -> dict[str, str]:
    """episode_id → 源文件路径。"""
    return {str(ep["id"]): str(ep["source_path"]) for ep in episodes}


def probe_segment_ok(path: str) -> bool:
    try:
        probe.probe(Path(path))
    except (ValueError, OSError):
        return False
    return True
