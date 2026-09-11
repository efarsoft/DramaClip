"""解说管线：分析结果 → 编排方案（raw_clip/intro/cross/ultra_short/dialogue）+ TTS 合成。

编排层只产出画面结构与旁白槽位；文案由 narration.copywriter 生成，TTS 由本模块回填。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures
from dramaclip.engines.narration import (
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

MODE_LABELS = {
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
        return modes.build_intro(episode_id, conflict_scores, strategy)
    if mode == "cross_narration":
        return modes_w5.build_cross(episode_id, conflict_scores, strategy)
    if mode == "ultra_short_hook":
        return modes_w5.build_ultra_short(episode_id, conflict_scores, strategy)
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return modes_w8.build_full(episode_id, conflict_scores, strategy)
    if mode == "subtitle_flow":
        return modes_w9.build_subtitle_flow(
            episode_id, conflict_scores, asr_segments, strategy
        )
    if mode == "dual_host_chat":
        return modes_p2.build_dual_host(episode_id, conflict_scores, strategy)
    if mode == "inner_monologue":
        return modes_p2.build_monologue(episode_id, conflict_scores, strategy)
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


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

    def narration_span(
        number: int, text: str, start: float, *, narration_id: str
    ) -> TimelineSegment:
        limit = durations.get(number, 0.0) + 5
        return TimelineSegment(
            episode_id=episode_map[number][0],
            start=round(start, 2),
            end=round(min(start + estimate_duration(text), limit), 2),
            audio="narration",
            subtitle_text=text,
            narration_id=narration_id,
        )

    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    cursors: dict[int, float] = {}

    first = script.segments[0]
    hook_start = snap(first.episode, first.start)
    hook_id = "n0"
    timeline.append(
        narration_span(first.episode, script.hook, hook_start, narration_id=hook_id)
    )
    texts.append(
        NarrationText(id=hook_id, text=script.hook, brief="开场钩子：抛出全片最大悬念")
    )
    cursors[first.episode] = hook_start + estimate_duration(script.hook)

    for order, segment in enumerate(script.segments, start=1):
        ep = segment.episode
        limit = durations.get(ep, 0.0) + 5
        start = max(snap(ep, segment.start), cursors.get(ep, 0.0))
        end = min(max(snap(ep, segment.end), start + 0.5), limit)
        if end <= start:
            continue
        body_id = f"n{order}"
        timeline.append(
            TimelineSegment(
                episode_id=episode_map[ep][0],
                start=round(start, 2),
                end=round(end, 2),
                audio="narration",
                subtitle_text=segment.text,
                narration_id=body_id,
            )
        )
        texts.append(NarrationText(id=body_id, text=segment.text))
        cursors[ep] = end

    if script.cta != "":
        last_ep = script.segments[-1].episode
        cta_id = f"n{len(script.segments) + 1}"
        timeline.append(
            narration_span(
                last_ep, script.cta, cursors.get(last_ep, 0.0), narration_id=cta_id
            )
        )
        texts.append(NarrationText(id=cta_id, text=script.cta))

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


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    降级禁止（规格 §3.3.1）：任一段没有合格音频，整条方案失败——
    半条旁白的片子不可交付。段↔文案只认 id，绝不按位置推断。
    """
    if not plan.narration_texts:
        return plan
    engine = create_tts(settings.get("tts.engine", "edge"), models_dir)
    default_voice = settings.get("tts.voice", "")
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    for item in plan.narration_texts:
        if not item.text.strip():
            raise RuntimeError(
                f"旁白 {item.id} 文案为空——编剧链未执行，这条方案不该往下走配音"
            )
        # 段级 voice 优先（双人对谈的双音色），缺省用全局设置
        voice = item.voice or default_voice
        try:
            audio_path = engine.synthesize(item.text, voice, work_dir / f"{item.id}.mp3")
            duration = tts_base.audio_duration_s(audio_path)
        except Exception as exc:  # noqa: BLE001 - 任何配音失败都是方案失败，原因要原样带出
            raise RuntimeError(
                f"旁白 {item.id} 合成失败（引擎={settings.get('tts.engine', 'edge')}）："
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not duration or duration <= 0:
            raise RuntimeError(f"旁白 {item.id} 合成后音频时长无效（{duration}s）")
        voiced[item.id] = (str(audio_path), item.text, float(duration))

    timeline = [segment.model_dump() for segment in plan.timeline]
    for segment in timeline:
        # ducked（全片解说全程压底旁白）与 narration 同权：两者都要回填时长与解说字幕
        if segment["audio"] not in ("narration", "ducked"):
            continue
        key = segment.get("narration_id")
        if key not in voiced:
            raise RuntimeError(
                f"编排自相矛盾：旁白段 {segment['episode_id']}@{segment['start']} "
                f"的 narration_id={key!r} 在文案表里不存在"
            )
        _audio_path, text, duration = voiced[key]
        segment["end"] = round(segment["start"] + duration, 3)
        segment["subtitle_text"] = text
    updated = [
        item.model_copy(
            update={"audio_path": voiced[item.id][0], "duration": voiced[item.id][2]}
        )
        for item in plan.narration_texts
    ]
    # 校验回模型：model_copy 会把裸 dict 塞进 timeline，导出层按属性读段就会炸
    return PlanData.model_validate(
        {**plan.model_dump(), "narration_texts": updated, "timeline": timeline}
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
