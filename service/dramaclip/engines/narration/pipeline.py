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
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.narration.scriptwriter import Script, estimate_duration
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


def build_from_script_dialogue(
    episode_id: str,
    script: Script,
    asr_segments: list[AsrSegment],
    strategy: StrategySpec,
) -> PlanData:
    """剧本驱动编排（对话解说试点）：钩子+分段解说+CTA，片段吸附台词边界。

    时长由文案决定：narration 段先按字数估算，合成阶段以 TTS 实际音频回填。
    """
    max_end = max((segment.end for segment in asr_segments), default=0.0)
    bounds = sorted(
        {round(bound, 2) for segment in asr_segments for bound in (segment.start, segment.end)}
    )

    def snap(value: float) -> float:
        candidates = [bound for bound in bounds if abs(bound - value) <= 1.5]
        return min(candidates, key=lambda bound: abs(bound - value)) if candidates else value

    def narration_span(text: str, start: float) -> TimelineSegment:
        return TimelineSegment(
            episode_id=episode_id,
            start=round(start, 2),
            end=round(min(start + estimate_duration(text), max_end + 30), 2),
            audio="narration",
            subtitle_text=text,
        )

    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    first = script.segments[0]
    hook_start = snap(first.start)
    timeline.append(narration_span(script.hook, hook_start))
    texts.append(NarrationText(id="n0", text=script.hook))

    order = 0
    cursor = hook_start + estimate_duration(script.hook)
    for segment in script.segments:
        start = max(snap(segment.start), cursor)
        end = max(snap(segment.end), start + 0.5)
        order += 1
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(start, 2),
                end=round(end, 2),
                audio="narration",
                subtitle_text=segment.text,
            )
        )
        texts.append(NarrationText(id=f"n{order}", text=segment.text))
        cursor = end

    if script.cta != "":
        order += 1
        timeline.append(narration_span(script.cta, min(cursor, max_end + 1)))
        texts.append(NarrationText(id=f"n{order}", text=script.cta))

    return PlanData(mode="dialogue_narration", timeline=timeline, narration_texts=texts,
                    strategy=strategy, planner="llm_script")


def build_from_script_episodes(
    episode_map: dict[int, tuple[str, list[AsrSegment]]],
    durations: dict[int, float],
    script: Script,
    strategy: StrategySpec,
) -> PlanData:
    """跨集剧本驱动编排：每个剧本片段按集号取对应集的素材画面。

    episode_map：集号 → (episode_id, 该集 asr_segments)；durations：集号 → 集时长。
    钩子挂在首个剧本片段所在集的画面开头；正文逐段吸附台词边界；CTA 接在末段之后。
    """
    bounds_by_ep = {
        number: sorted({round(b, 2) for seg in asr for b in (seg.start, seg.end)})
        for number, (_episode_id, asr) in episode_map.items()
    }

    def snap(number: int, value: float) -> float:
        candidates = bounds_by_ep.get(number, [])
        near = [b for b in candidates if abs(b - value) <= 1.5]
        return min(near, key=lambda b: abs(b - value)) if near else value

    def narration_span(number: int, text: str, start: float) -> TimelineSegment:
        limit = durations.get(number, 0.0) + 5
        return TimelineSegment(
            episode_id=episode_map[number][0],
            start=round(start, 2),
            end=round(min(start + estimate_duration(text), limit), 2),
            audio="narration",
            subtitle_text=text,
        )

    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    cursors: dict[int, float] = {}

    first = script.segments[0]
    hook_start = snap(first.episode, first.start)
    timeline.append(narration_span(first.episode, script.hook, hook_start))
    texts.append(NarrationText(id="n0", text=script.hook))
    cursors[first.episode] = hook_start + estimate_duration(script.hook)

    for order, segment in enumerate(script.segments, start=1):
        ep = segment.episode
        limit = durations.get(ep, 0.0) + 5
        start = max(snap(ep, segment.start), cursors.get(ep, 0.0))
        end = min(max(snap(ep, segment.end), start + 0.5), limit)
        if end <= start:
            continue
        timeline.append(
            TimelineSegment(
                episode_id=episode_map[ep][0],
                start=round(start, 2),
                end=round(end, 2),
                audio="narration",
                subtitle_text=segment.text,
            )
        )
        texts.append(NarrationText(id=f"n{order}", text=segment.text))
        cursors[ep] = end

    if script.cta != "":
        last_ep = script.segments[-1].episode
        timeline.append(narration_span(last_ep, script.cta, cursors.get(last_ep, 0.0)))
        texts.append(NarrationText(id=f"n{len(script.segments) + 1}", text=script.cta))

    return PlanData(
        mode="dialogue_narration",
        timeline=timeline,
        narration_texts=texts,
        strategy=strategy,
        planner="llm_script",
    )


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


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
) -> PlanData:
    """逐段合成旁白音频并回填 audio_path/duration。

    narration 与 ducked 段都按各自旁白实际时长回填时长与解说字幕，并把该条文案的
    id 记进 `segment.narration_id`；导出层据此取音（拿不到音的段回退原声并清 id）。
    """
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
        # ducked（全片解说全程压底旁白）与 narration 同权：两者都要回填时长与解说字幕
        if segment["audio"] not in ("narration", "ducked"):
            continue
        # 陈旧映射先抹掉：本轮没拿到音频的段必须回落到纯原声，导出侧才无从错取
        segment["narration_id"] = None
        if narration_order >= len(updated):
            segment["audio"] = "original"  # 旁白文案已用尽 → 无音可挂
            segment["subtitle_text"] = None
            continue
        text = updated[narration_order]
        narration_order += 1
        duration = text["duration"]
        if duration is not None and duration > 0:
            segment["end"] = round(segment["start"] + duration, 3)
            segment["subtitle_text"] = str(text["text"])
            segment["narration_id"] = str(text["id"])
        else:
            segment["audio"] = "original"  # 无旁白音频 → 回退原声段（字幕一并取消）
            segment["subtitle_text"] = None
    kept_texts = [text for text in updated if text["duration"] is not None]
    # 校验回模型：model_copy 会把裸 dict 塞进 timeline，导出层按属性读段就会炸
    return PlanData.model_validate(
        {**plan.model_dump(), "narration_texts": kept_texts, "timeline": timeline}
    )


def segment_source_map(episodes: list[dict[str, Any]]) -> dict[str, str]:
    """episode_id → 源文件路径。"""
    return {str(ep["id"]): str(ep["source_path"]) for ep in episodes}


def probe_segment_ok(path: str) -> bool:
    try:
        probe.probe(Path(path))
    except (ValueError, OSError):
        return False
    return True
