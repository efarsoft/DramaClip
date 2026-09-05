"""解说管线：分析结果 → 编排方案（raw_clip/intro/cross/ultra_short/dialogue）+ TTS 合成。

LLM 文案未配置时用模板降级（W3 同策略）；TTS 用 edge（云端免费，无需本地模型）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures
from dramaclip.engines.narration import (
    dialogue_selector,
    modes,
    modes_p2,
    modes_w5,
    modes_w8,
    modes_w9,
)
from dramaclip.engines.narration.models import PlanData, StrategySpec
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.engines.tts import base as tts_base
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.infra.ffmpeg import probe

_MODE_LABELS = {
    "raw_clip": "纯原片剪辑",
    "intro_narration": "片头解说",
    "cross_narration": "交叉解说",
    "ultra_short_hook": "超短悬念版",
    "dialogue_narration": "剧情解说",
    "full_narration": "全片解说",
    "subtitle_flow": "字幕金句流",
    "dual_host_chat": "双人对谈",
    "inner_monologue": "内心独白",
}


def build_plan(
    mode: str,
    episode_id: str,
    conflict_scores: list[ConflictScore],
    highlights: list[HighlightSegment],
    asr_segments: list[AsrSegment],
    audio: AudioFeatures,
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
    if mode == "dialogue_narration":
        lines = dialogue_selector.select_dialogue_lines(asr_segments, audio)
        return dialogue_selector.build_dialogue(episode_id, lines, strategy)
    if mode == "full_narration":
        return modes_w8.build_full(
            episode_id,
            conflict_scores,
            strategy,
            settings.get("_project_name", "这部剧"),
            settings.get("_genre"),
        )
    if mode == "subtitle_flow":
        return modes_w9.build_subtitle_flow(
            episode_id, conflict_scores, asr_segments, strategy
        )
    if mode == "dual_host_chat":
        return modes_p2.build_dual_host(
            episode_id, conflict_scores, strategy, settings.get("_project_name", "这部剧")
        )
    if mode == "inner_monologue":
        return modes_p2.build_monologue(
            episode_id, conflict_scores, strategy, settings.get("_project_name", "这部剧")
        )
    raise ValueError(f"模式暂未支持: {mode}（{_MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


def parse_audio_features(audio_json: str | None) -> AudioFeatures:
    if not audio_json:
        return AudioFeatures()
    return AudioFeatures.model_validate_json(audio_json)


def parse_asr_segments(asr_json: str) -> list[AsrSegment]:
    return [AsrSegment.model_validate(item) for item in json.loads(asr_json)]


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
    """合成片头旁白并回填时长；TTS 失败时首段降级原声（不阻塞）。"""
    return synthesize_narration_texts(plan, settings, work_dir)


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
) -> PlanData:
    """逐段合成旁白音频并回填 audio_path/duration；narration 段时长随 TTS 回填。"""
    if not plan.narration_texts:
        return plan
    engine = create_tts(settings.get("tts.engine", "edge"), models_dir)
    default_voice = settings.get("tts.voice", "")
    updated: list[dict[str, Any]] = []
    for item in plan.narration_texts:
        # 段级 voice 优先（双人对谈的双音色），缺省用全局设置
        voice = item.voice or default_voice
        try:
            audio_path = engine.synthesize(item.text, voice, work_dir / f"{item.id}.mp3")
            duration: float | None = tts_base.audio_duration_s(audio_path)
        except Exception:  # 云端不可达等：该段降级为原声，不阻塞编排
            audio_path = work_dir / f"{item.id}.mp3"
            duration = None
        updated.append(dict(item.model_dump(), audio_path=str(audio_path), duration=duration))
    timeline = [segment.model_dump() for segment in plan.timeline]
    narration_order = 0
    for segment in timeline:
        if segment["audio"] != "narration" or narration_order >= len(updated):
            continue
        text = updated[narration_order]
        duration = text["duration"]
        if duration is not None and duration > 0:
            segment["end"] = round(segment["start"] + duration, 3)
            segment["subtitle_text"] = str(text["text"])
        else:
            segment["audio"] = "original"  # 无旁白音频 → 回退原声段（字幕一并取消）
            segment["subtitle_text"] = None
        narration_order += 1
    kept_texts = [text for text in updated if text["duration"] is not None]
    return plan.model_copy(update={"narration_texts": kept_texts, "timeline": timeline})


def segment_source_map(episodes: list[dict[str, Any]]) -> dict[str, str]:
    """episode_id → 源文件路径。"""
    return {str(ep["id"]): str(ep["source_path"]) for ep in episodes}


def probe_segment_ok(path: str) -> bool:
    try:
        probe.probe(Path(path))
    except (ValueError, OSError):
        return False
    return True
