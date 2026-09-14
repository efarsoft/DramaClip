"""解说管线：分析结果 → 规则编排（除剧情解说外的八模式）+ 剧本驱动装配 + TTS 合成回填。

编排层只产出画面结构与旁白槽位；文案由 narration.copywriter 生成，TTS 由本模块回填。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
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


def _assert_voiceable(plan: PlanData) -> None:
    """配音前的上游契约校验：文案非空、每个旁白段都按 id 配到文案。

    这两条违约都来自编排/编剧链，不是 TTS 结果，故一律排在合成之前——第三个槽位
    为空时不该先为前两个槽位付两轮真实合成。段↔文案只认 `narration_id`，绝不按位置推断。

    扫段而非只看文案表是否为空：`narration_texts` 为空只说明"没有文案"，不说明
    "没有段要文案"。带着旁白段的空表是静音片，必须在这里就炸。
    """
    for item in plan.narration_texts:
        if not item.text.strip():
            raise RuntimeError(
                f"旁白 {item.id} 文案为空——编剧链未执行，这条方案不该往下走配音"
            )
    voiced_ids = {item.id for item in plan.narration_texts}
    for segment in plan.timeline:
        # ducked（全片解说全程压底旁白）与 narration 同权：两者都必须配到文案
        if segment.audio not in ("narration", "ducked"):
            continue
        if segment.narration_id not in voiced_ids:
            raise RuntimeError(
                f"编排自相矛盾：旁白段 {segment.episode_id}@{segment.start} "
                f"的 narration_id={segment.narration_id!r} 在文案表里不存在"
            )


def _content_addressed_audio(
    work_dir: Path, slot_id: str, text: str, voice: str, engine: str
) -> Path:
    """音频文件名内容寻址：影响成品的输入 (text, voice, engine) 全部进哈希。

    槽位 id 按模式确定性生成（full-1…、intro-1、n0…），只作前缀便于溯源，
    不再单独决定路径——`{id}.mp3` 会让同模式的两份方案必然互相覆盖，而
    audio_path 随 plan_data 落库、export.retry 之后还按 stored path 渲染：
    文件被覆盖等于旧方案的字幕配上新方案的旁白，无声出错。同名 ⟺ 同内容，
    内容相同的两轮合成复用同一文件也就安全（缓存优先，docs/service/02 §6）。
    """
    digest = hashlib.sha1(
        f"{text}|{voice}|{engine}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return work_dir / f"{slot_id}-{digest}.mp3"


def _synthesize_into(
    engine: tts_base.TtsEngine, text: str, voice: str, final_path: Path
) -> None:
    """缓存优先 + 暂存落位：命中即复用，未命中先写临时名、成功后原子搬进最终路径。

    临时名把两种脏产物挡在最终路径之外：合成失败留下的半截 mp3（当场清掉，
    否则下一轮会把它当缓存命中）与并发写同名文件（`_run_generation_parallel`
    双线程、produce 与 generate_plans 重叠）——os.replace 原子换入，读者
    永远只见完整文件。
    """
    if final_path.is_file() and final_path.stat().st_size > 0:
        return
    staging = final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex}.part")
    try:
        engine.synthesize(text, voice, staging)
        os.replace(staging, final_path)
    finally:
        staging.unlink(missing_ok=True)


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    降级禁止（规格 §3.3.1）：任一段没有合格音频，整条方案失败——
    半条旁白的片子不可交付。上游契约由 `_assert_voiceable` 先一次性验完，
    本函数只管合成与回填。音频路径由本层内容寻址（见 `_content_addressed_audio`），
    调用方传哪个目录都不可能让两份方案踩到同一个文件。
    """
    _assert_voiceable(plan)
    if not plan.narration_texts:
        return plan
    engine_name = settings.get("tts.engine", "edge")
    engine = create_tts(engine_name, models_dir)
    default_voice = settings.get("tts.voice", "")
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    for item in plan.narration_texts:
        # 段级 voice 优先（双人对谈的双音色），缺省用全局设置
        voice = item.voice or default_voice
        audio_path = _content_addressed_audio(work_dir, item.id, item.text, voice, engine_name)
        try:
            _synthesize_into(engine, item.text, voice, audio_path)
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
        _audio_path, text, duration = voiced[str(segment["narration_id"])]
        segment["end"] = round(segment["start"] + duration, 3)
        segment["subtitle_text"] = text
    updated = [
        item.model_copy(
            update={"audio_path": voiced[item.id][0], "duration": voiced[item.id][2]}
        )
        for item in plan.narration_texts
    ]
    # timeline 是裸 dict，必须过 model_validate 才是模型实例，导出层按属性读段
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
