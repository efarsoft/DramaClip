"""解说管线：分析结果 → 规则编排（除剧情解说外的八模式）+ 剧本驱动装配 + TTS 合成回填。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import (
    modes,
    modes_p2,
    modes_w5,
    modes_w8,
    modes_w9,
)
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.narration.scriptwriter import Script, estimate_duration
from dramaclip.engines.narration.transitions import apply as apply_transitions
from dramaclip.engines.semantic.models import HighlightSegment
from dramaclip.engines.tts import base as tts_base
from dramaclip.engines.tts.factory import create as create_tts

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
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    material: MaterialByEpisode,
    settings: dict[str, str],
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。
    """
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "300")),
    )
    if mode == "raw_clip":
        return apply_transitions(modes.build_raw_clip(scenes, highlights, strategy))
    if mode == "intro_narration":
        return apply_transitions(modes.build_intro(scenes, strategy))
    if mode == "cross_narration":
        return apply_transitions(modes_w5.build_cross(scenes, strategy))
    if mode == "ultra_short_hook":
        return apply_transitions(modes_w5.build_ultra_short(scenes, strategy))
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return apply_transitions(modes_w8.build_full(scenes, strategy))
    if mode == "subtitle_flow":
        return apply_transitions(modes_w9.build_subtitle_flow(scenes, material, strategy))
    if mode == "dual_host_chat":
        return apply_transitions(modes_p2.build_dual_host(scenes, strategy))
    if mode == "inner_monologue":
        return apply_transitions(modes_p2.build_monologue(scenes, strategy))
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


_NEAR_GAP_S = 1.0  # 近邻衔接阈值：段间隔小于此值视为同镜头连续推进

# 越界判定放的余量。两端数字都不精确：`end` 与源长都按 3 位小数入库（源长由扫描时
# ffprobe 量得，见 api/project.py），而素材自己的帧栅格更粗——实测 6.00s 的窗口落出
# 6.0667s 的流时长。所以「段尾正好等于源长」必须是绿的，判红线得抬到百分位以上。
# 真越界是秒级的：库存量实测 +4.88s / +6.03s，2026-09-19 真机 dialogue_narration +5.23s。
_SOURCE_FIT_TOL_S = 0.05


def build_from_script_episodes(
    episode_map: dict[int, tuple[str, list[AsrSegment]]],
    durations: dict[int, float],
    script: Script,
    strategy: StrategySpec,
) -> PlanData:
    """跨集剧本驱动编排：每个剧本片段按集号取对应集的素材画面。
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
        cursor = cursors.get(ep, 0.0)
        start_candidate = snap(ep, segment.start)
        # 近邻衔接：与上一段结尾间隔 <1s 时贴合，消除微跳跃观感（≥1s 的
        # 场景跳转是叙事需要，保留）
        if 0.0 < start_candidate - cursor < _NEAR_GAP_S:
            start_candidate = cursor
        start = max(start_candidate, cursor)
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

    return apply_transitions(
        PlanData(
            mode="dialogue_narration",
            timeline=timeline,
            narration_texts=texts,
            strategy=strategy,
            planner="llm_script",
        )
    )


def parse_asr_segments(asr_json: str) -> list[AsrSegment]:
    return [AsrSegment.model_validate(item) for item in json.loads(asr_json)]


def _assert_voiceable(plan: PlanData) -> None:
    """配音前的上游契约校验：文案非空、每个旁白段都按 id 配到文案。
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
    """
    digest = hashlib.sha1(
        f"{text}|{voice}|{engine}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return work_dir / f"{slot_id}-{digest}.mp3"


def _synthesize_into(
    engine: tts_base.TtsEngine, text: str, voice: str, final_path: Path
) -> None:
    """缓存优先 + 暂存落位：命中即复用，未命中先写临时名、成功后原子搬进最终路径。
    """
    if final_path.is_file() and final_path.stat().st_size > 0:
        return
    # uuid 插进主干、保留最终扩展名：soundfile/edge 都靠扩展名推断音频格式，
    # 以 .part 结尾会让 sf.write 直接抛 TypeError。
    staging = final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex}{final_path.suffix}")
    try:
        engine.synthesize(text, voice, staging)
        os.replace(staging, final_path)
    finally:
        staging.unlink(missing_ok=True)


def _assert_within_source(
    timeline: list[dict[str, Any]],
    source_durations: dict[str, float],
) -> None:
    """回填后的画面窗口必须仍落在源集里，越界就是这条方案失败。

    查出问题的动作是回填：它把段尾改成 `start + 实测音频时长`。编排层自己也可能把窗
    口摆到源末尾之外——`build_from_script_episodes` 的预算写的是「源长 + 5s」，真机
    2026-09-19 那条 dialogue_narration 就是 192.20s 的集配 197.43s 的段（超 5.23s）。
    两处谁犯的错都在这里一并兜住：判据看的是最终要播的窗口，不是谁写的。

    源时长缺失或不大于 0 同样判失败：拿不到源长就等于「无法证明不越界」，把它当成
    「没有越界」是这套判据最省事的静默失效方式。

    真机实测（bundled ffmpeg 8.1.1，源 `6.mp4` = 76.86s，9s 旁白干音）：
    窗口 70.86→79.86 退码 **0**、产物视频 6.07s / 音频 6.03s，旁白被从中间掐掉；
    窗口 76.86→82.86（起点即 EOF）退码仍 0、产物 262 字节无流。渲染层既不报错也不
    警告，所以这里不拦就是静默出坏片（业主裁决：改所见所闻的一律失败，不做截断）。

    走到这里说明回填的尾部收口（`synthesize_narration_texts` 里那句「整段往前挪到贴着
    集尾」）已经让过位了：再往前就撞上同集的上一段。所以文案与长度都不动，判失败。
    """
    prev_end: dict[str, float] = {}
    for index, segment in enumerate(timeline):
        episode_id = str(segment["episode_id"])
        limit = source_durations.get(episode_id, 0.0)
        if limit <= 0:
            raise RuntimeError(
                f"无法核对画面窗口是否越过源集末尾：时间轴引用的集 {episode_id}"
                " 没有源集时长（未入库或为 0）——宁可不出这条方案，"
                "也不能拿「查不了」当「没问题」"
            )
        end = float(segment["end"])
        floor = prev_end.get(episode_id)
        prev_end[episode_id] = end
        if end <= limit + _SOURCE_FIT_TOL_S:
            continue
        slot = segment.get("narration_id")
        label = f"旁白段 {slot}" if slot else f"原声段 #{index}"
        # 为什么不挪了：往前贴集尾会撞上同集的上一段（画面重播=业主立案③），
        # 而这一集的第一段已经没有"上一段"可撞，说明旁白比整集素材还长。
        stuck = (
            f"往前挪到贴着集尾就会和上一段（止于 {floor:.2f}s）重叠，等于重播画面"
            if floor is not None and floor > 0
            else "这一段比整集素材还长，挪到集头也放不下"
        )
        raise RuntimeError(
            f"配音回填后画面窗口越过源集末尾：{episode_id} 的{label} 要播到 "
            f"{end:.2f}s，源集时长只有 {limit:.2f}s（超出 {end - limit:.2f}s）"
            f" —— {stuck}，这条方案判失败而不是把旁白截掉"
        )


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
    *,
    source_durations: dict[str, float],
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    `source_durations` 是 {集 id: 源片秒数}，必填而非可选：回填会把段尾改成
    `start + 实测音频时长`，只有拿到源长才知道这个窗口还在不在素材里。给默认值
    就等于给「跳过检查」开门，而跳过检查的代价是成片把旁白说到一半掐掉（见
    `_assert_within_source`）。
    """
    _assert_voiceable(plan)
    if not plan.narration_texts:
        return plan
    engine_name = settings.get("tts.engine", "edge")
    engine = create_tts(engine_name, models_dir)
    # 音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库
    default_voice = (
        settings.get(f"tts.voice.{engine_name}") or settings.get("tts.voice") or ""
    )
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
    # 实测音频时长 ≠ 编排期的估计时长：把 end 直接改成 start + 实测，前一段就会
    # 盖住后一段的源素材区间，成片演到第 6 秒又倒回第 1 秒重播同一段画面（业主
    # 立案③）。这里按集重走一遍编排层同款游标（`build_from_script_episodes` 的
    # `start = max(candidate, cursor)`）：只保证源时间单调不回退，旁白段长度
    # 仍等于实测音频，原声段只平移不压缩。
    cursor: dict[str, float] = {}
    for segment in timeline:
        episode_id = str(segment["episode_id"])
        floor = cursor.get(episode_id, 0.0)
        start = max(float(segment["start"]), floor)
        if segment["audio"] in ("narration", "ducked"):
            # ducked（全片解说全程压底旁白）与 narration 同权：两者都要回填时长与解说字幕
            _audio_path, text, duration = voiced[str(segment["narration_id"])]
            segment["subtitle_text"] = text
            length = duration
        else:
            length = float(segment["end"]) - float(segment["start"])
        # 尾部收口：实测比剩余素材长时，整段往前挪到贴着集尾——这段的文案与长度都不动，
        # 换的只是压在它下面的画面。挪不动（再往前就和上一段重叠=画面重播）就照原样
        # 交给 `_assert_within_source` 判死，不截音也不截画面。
        # 为什么"段尾正好等于源末尾"是安全的：真机实测（bundled ffmpeg 8.1.1，源
        # `1.mp4` 现量 192.200s，真 TTS 干音 6.350s，命令由 `cut_segment_args` 生成）
        # 窗口 185.85→192.20 出片视频 6.367s / 音频 6.371s，与同一干音在素材中段
        # 20.00→26.35 的产物逐毫秒一致；而起点即 EOF 的越界窗口退码仍 0、262 字节无流。
        # 收口损失的只有"这一段配哪几秒画面"，没有一帧声音被丢掉。
        limit = source_durations.get(episode_id, 0.0)
        if 0 < limit < start + length and limit - length >= floor:
            start = limit - length
        end = start + length
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        cursor[episode_id] = end
    _assert_within_source(timeline, source_durations)
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


