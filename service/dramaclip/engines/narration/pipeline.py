"""解说管线：分析结果 → 规则编排（除剧情解说外的八模式）+ 剧本驱动装配 + TTS 合成回填。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
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
from dramaclip.engines.narration.conversion import structural_defects
from dramaclip.engines.narration.layout import (
    _assert_within_source,
    _layout_cross,
    _layout_ultra_short,
    _patch_timeline,
)
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.narration.scriptwriter import Script, estimate_duration
from dramaclip.engines.narration.synthesis import (
    _CACHE_MAX_BYTES,
    LogFn,
    _align_to_hook_slot,
    _assert_voiceable,
    _emit,
    _EnginePool,
    _evict_cache,
)
from dramaclip.engines.narration.transitions import apply as apply_transitions
from dramaclip.engines.semantic.models import HighlightSegment
from dramaclip.engines.tts import base as tts_base

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

#: 已下线模式登记表：下线的模式从标签表与白名单里**删干净**，只在这里留名，
# 供 AI 模式推荐净化历史缓存（老项目的推荐缓存/方案行里可能还带着）。
# 2026-10-27 业主裁决高光混剪并入纯原片剪辑（raw_clip 单入口），2026-11-12
# 业主裁决完全清除（生成/渲染/消费分支全删，存量方案行由迁移 027 删除）。
# 当前为空：九种模式全部在供应。
RETIRED_MODES: frozenset[str] = frozenset()


def build_plan(
    mode: str,
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    material: MaterialByEpisode,
    settings: dict[str, str],
    source_durations: dict[str, float] | None = None,
    golden_lines: dict[str, list[tuple[float, float]]] | None = None,
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。

    `source_durations`（{集 id: 源片秒数}）可选，供超短钩子做可行性选景——
    钩子/CTA 的画面预算要在规划期就知道放不放得下，不能等 TTS 实测才爆。
    """
    strategy = StrategySpec(platform="douyin")

    def _finish(plan: PlanData) -> PlanData:
        # 原声窗台词句边界吸附全模式收口（业主 2026-10-27 策略：对话必须自然说完
        # 再转场）：装得下收进整句、撞邻窗退到句前/句后。raw_clip 系在各自 build
        # 内已吸过（幂等）；旁白占位窗与金句流重播卡由函数内跳过。
        plan = plan.model_copy(
            update={"timeline": modes.snap_windows_to_dialogue(plan.timeline, material)}
        )
        return apply_transitions(plan)

    if mode == "raw_clip":
        return _finish(modes.build_raw_clip(scenes, highlights, strategy, material))
    if mode == "intro_narration":
        return _finish(modes.build_intro(scenes, strategy, material))
    if mode == "cross_narration":
        return _finish(modes_w5.build_cross(scenes, strategy, material))
    if mode == "ultra_short_hook":
        return _finish(
            modes_w5.build_ultra_short(scenes, strategy, material, source_durations)
        )
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return _finish(modes_w8.build_full(scenes, strategy))
    if mode == "subtitle_flow":
        return _finish(
            modes_w9.build_subtitle_flow(scenes, material, strategy, golden_lines)
        )
    if mode == "dual_host_chat":
        return _finish(modes_p2.build_dual_host(scenes, strategy))
    if mode == "inner_monologue":
        return _finish(modes_p2.build_monologue(scenes, strategy))
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


_NEAR_GAP_S = 1.0  # 近邻衔接阈值：段间隔小于此值视为同镜头连续推进
# 镜头切点外扩吸附容差：0.7s 内有切点就扩过去（start 前扩/end 后扩，只加余地不吞内容）；
# 更宽会把解说与画面的对应关系拉远，更窄则大部分切点够不着。
_SHOT_TOL_S = 0.7
# 接缝判定：段开口与切点距离小于此值视为「落在换镜头上」（转 fade→cut 的依据）。
_SHOT_JOINT_EPS_S = 0.2


def build_from_script_episodes(
    episode_map: dict[int, tuple[str, list[AsrSegment]]],
    durations: dict[int, float],
    script: Script,
    strategy: StrategySpec,
    *,
    scene_cuts: dict[int, list[float]] | None = None,
) -> PlanData:
    """跨集剧本驱动编排：每个剧本片段按集号取对应集的素材画面。

    剪口精度两级吸附：先吸台词边界（对齐叙事），再外扩到镜头切点（对齐画面）——
    外扩只加画面余地不吞内容，剪口落在换镜头处，接缝读作一次正常转场而不是撕裂。
    切点缺失（旧库没跑场景检测）时第二级原值返回，退回纯台词吸附。
    """
    bounds_by_ep = {
        number: sorted({round(b, 2) for seg in asr for b in (seg.start, seg.end)})
        for number, (_episode_id, asr) in episode_map.items()
    }
    cuts_by_ep = {
        number: sorted({round(float(c), 2) for c in cuts})
        for number, cuts in (scene_cuts or {}).items()
    }

    def snap(number: int, value: float) -> float:
        candidates = bounds_by_ep.get(number, [])
        near = [b for b in candidates if abs(b - value) <= 1.5]
        return min(near, key=lambda b: abs(b - value)) if near else value

    def snap_to_shot(number: int, value: float, *, forward: bool) -> float:
        """外扩吸附镜头切点：start 向前（earlier）、end 向后（later）。"""
        cuts = cuts_by_ep.get(number, [])
        if forward:
            near = [c for c in cuts if value <= c <= value + _SHOT_TOL_S]
        else:
            near = [c for c in cuts if value - _SHOT_TOL_S <= c <= value]
        return min(near, key=lambda c: abs(c - value)) if near else value

    def on_shot_cut(number: int, value: float) -> bool:
        return any(abs(c - value) <= _SHOT_JOINT_EPS_S for c in cuts_by_ep.get(number, []))

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
    shot_aligned: set[int] = set()

    first = script.segments[0]
    hook_start = snap_to_shot(first.episode, snap(first.episode, first.start), forward=False)
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
        start_candidate = snap_to_shot(ep, snap(ep, segment.start), forward=False)
        # 近邻衔接：与上一段结尾间隔 <1s 时贴合，消除微跳跃观感（≥1s 的
        # 场景跳转是叙事需要，保留）
        if 0.0 < start_candidate - cursor < _NEAR_GAP_S:
            start_candidate = cursor
        start = max(start_candidate, cursor)
        end = min(
            max(snap_to_shot(ep, snap(ep, segment.end), forward=True), start + 0.5),
            limit,
        )
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
        # 本段开口正落在镜头切点上：接缝是画面自身的换镜头，硬切比叠淡更干净
        # （fade 盖在真实 shot change 上反而发糊）；不足 1s 的贴缝本来就是 cut。
        if (
            len(timeline) > 1
            and timeline[-1].episode_id == timeline[-2].episode_id
            and on_shot_cut(ep, start)
        ):
            shot_aligned.add(len(timeline) - 1)
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
        ),
        prefer_cuts=frozenset(shot_aligned),
    )


def parse_asr_segments(asr_json: str) -> list[AsrSegment]:
    return [AsrSegment.model_validate(item) for item in json.loads(asr_json)]
def _rewrite_and_resynth(
    unplaced: list[dict[str, Any]],
    voiced: dict[str, tuple[str, str, float]],
    plan: PlanData,
    pool: _EnginePool,
    settings: dict[str, str],
    speed: str,
    work_dir: Path,
    cache_dir: Path,
    rewrite_for_fit: Callable[[str, int], str | None],
    log: LogFn | None,
) -> dict[str, int]:
    """对放不下的段做一轮定向收短＋重新合成；返回本轮统计（accepted=0 即无进展）。

    目标字数按本段实测语速推（字/秒 × 空隙秒），不另设语速常量。收短结果
    必须过长度验收（≤目标字数，#16）：删两三个字的「伪收短」重合成后大概率
    仍放不下，白付一轮 TTS+回排。重写或重合成单段失败都只留痕跳过（该段走
    弃段路径），绝不牵连整条方案。
    """
    stats = {"rewritten": 0, "accepted": 0, "rejected_same": 0, "rejected_long": 0,
             "resynth_fail": 0}
    items = {item.id: item for item in plan.narration_texts}
    for entry in unplaced:
        slot = str(entry["slot"])
        text = str(entry["text"])
        duration = float(entry["duration"])
        gap_s = float(entry["gap_s"])
        cps = len(text) / duration if duration > 0 else 4.0
        target_chars = max(8, int(gap_s * cps))
        try:
            new_text = rewrite_for_fit(text, target_chars)
        except Exception as exc:  # noqa: BLE001 - LLM 失败不致命：该段回退弃段路径
            _emit(log, f"旁白 {slot} 收短重写失败（{type(exc).__name__}: {exc}）", "warn")
            continue
        if not new_text or new_text.strip() == text.strip():
            stats["rejected_same"] += 1
            continue
        stats["rewritten"] += 1
        if len(new_text.strip()) > target_chars:
            stats["rejected_long"] += 1
            _emit(
                log,
                f"旁白 {slot} 收短稿 {len(new_text.strip())} 字仍超目标 "
                f"≤{target_chars}，弃用重写结果（免白付一轮 TTS）",
                "warn",
            )
            continue
        # 收短产出过全链同款两道零容忍出口：数字中文化（「2,000斤」配音全毁）与
        # 元叙述硬闸（「画面里」进 TTS=零容忍破防）。命中元叙述弃用重写结果，
        # 该段回退弃段路径——收短是增强，不能成为病灶入口。
        new_text = to_chinese_numerals(new_text.strip())
        from dramaclip.engines.narration.audit import (  # noqa: PLC0415 - 防 import 环
            _METANARRATIVE_RE,
        )

        if _METANARRATIVE_RE.search(new_text):
            _emit(log, f"旁白 {slot} 收短稿含元叙述字眼，弃用重写结果", "warn")
            continue
        item = items.get(slot)
        voice = (item.voice if item is not None else "") or pool.voice_for(settings)
        if item is not None and item.voice and not pool.accepts_voice(item.voice):
            voice = pool.voice_for(settings)
        try:
            audio_path = pool.synthesize_item(slot, new_text, voice, speed, work_dir, cache_dir)
            new_dur = tts_base.audio_duration_s(audio_path)
        except Exception as exc:  # noqa: BLE001 - 重合成失败不致命：该段回退弃段路径
            stats["resynth_fail"] += 1
            _emit(log, f"旁白 {slot} 收短后重新合成失败（{exc}），保留原音频", "warn")
            continue
        if not new_dur or new_dur <= 0:
            stats["resynth_fail"] += 1
            continue
        audio_path, new_dur = _align_to_hook_slot(slot, audio_path, float(new_dur), log)
        voiced[slot] = (str(audio_path), new_text, float(new_dur))
        stats["accepted"] += 1
        _emit(
            log,
            f"旁白 {slot} 实测 {duration:.2f}s 超出 {gap_s:.2f}s 空隙，已收短至 "
            f"{len(new_text)} 字（目标 ≤{target_chars}）重新合成，实测 {float(new_dur):.2f}s",
        )
    return stats


def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
    *,
    source_durations: dict[str, float],
    log: LogFn | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    data_dir: Path | None = None,
    rewrite_for_fit: Callable[[str, int], str | None] | None = None,
    scene_cuts: dict[str, list[float]] | None = None,
    dialogue_spans: dict[str, list[tuple[float, float]]] | None = None,
    cancel: threading.Event | None = None,
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    `cancel`（稳定收尾批）：段循环头逐段检查——IndexTTS CPU 档单段 2~3 分钟，
    此前取消只在导出入口查一次、配音循环内无效，取消一个几十段的配音导出
    会白跑小时级（白占 worker 与云端费用）。取消异常上抛由外层按
    cancel_event 判 cancelled 落账。

    `source_durations` 是 {集 id: 源片秒数}，必填而非可选：回填会把段尾改成
    `start + 实测音频时长`，只有拿到源长才知道这个窗口还在不在素材里。给默认值
    就等于给「跳过检查」开门，而跳过检查的代价是成片把旁白说到一半掐掉（见
    `_assert_within_source`）。

    `log` 是可选的 (level, message) 回调（api 侧接 notifier.log），每段合成都会
    留下 engine_requested/engine_used/fallback_used/fallback_reason 溯源记录；
    不传则只写模块级 logger。引擎纪律见 `_EnginePool`：显式不回退，auto 才回退。

    `data_dir` 是设备解析入口（给工厂读运行环境安装态），没有它引擎按自身的 auto
    语义走。不从 `models_dir.parent` 反推：`models_dir` 是调用方给的，测试里常是
    tmp_path，猜出来的目录读 marker 会把「测试目录没装运行环境」读成「本机没装」。

    `rewrite_for_fit(text, target_chars) -> 新文案 | None`：实测时长装不进画面空隙时
    的定向收短出口（api 层接 LLM）。不传或重写无效时，放不下的段两轮后直接弃段
    留痕——业主裁决 2026-10-26：素材时长不够或太长应重新选取判断，而不是整条
    方案判失败。`_assert_within_source` 收窄为最终防线：重排与弃段消化后仍越界
    只可能是代码不变量被破坏。
    """
    _assert_voiceable(plan)
    if not plan.narration_texts:
        return plan
    engine_setting = settings.get("tts.engine", "")
    pool = _EnginePool(
        engine_setting,
        models_dir,
        log,
        api_key=settings.get("tts.api_key", ""),
        model=settings.get("tts.model", ""),
        device=str(settings.get("tts.device") or "auto"),
        data_dir=data_dir,
    )
    # 音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库。
    # auto 链下每段可能落在不同引擎上，段级 voice 缺省时逐引擎取键。
    speed = str(settings.get("tts.speed", "") or "")
    cache_dir = work_dir / "cache"
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    total_segments = len(plan.narration_texts)
    for item in plan.narration_texts:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("导出已取消：配音在段间中断")
        # 段级 voice 优先（双人对谈的双音色）——但仅当它对当前引擎有意义：
        # 双人/独白槽位硬编码的是 Edge 音色名，引擎切到克隆系后名字不再是文件，
        # 必须回退引擎默认音色（voice_for），否则克隆引擎拿名字当路径报错。
        voice = item.voice or pool.voice_for(settings)
        if item.voice and not pool.accepts_voice(item.voice):
            voice = pool.voice_for(settings)
        try:
            audio_path = pool.synthesize_item(
                item.id, item.text, voice, speed, work_dir, cache_dir
            )
            duration = tts_base.audio_duration_s(audio_path)
        except Exception as exc:  # noqa: BLE001 - 任何配音失败都是方案失败，原因要原样带出
            raise RuntimeError(
                f"旁白 {item.id} 合成失败（engine={pool.label}）："
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not duration or duration <= 0:
            raise RuntimeError(f"旁白 {item.id} 合成后音频时长无效（{duration}s）")
        # hook 槽位对齐策略机（批次二）：只对硬槽位段（intro-1）可能变速，
        # 其余段原样通过。失败保留原音频，不影响下面的回填与越界守卫。
        audio_path, duration = _align_to_hook_slot(item.id, audio_path, float(duration), log)
        voiced[item.id] = (str(audio_path), item.text, float(duration))
        if on_progress is not None:
            on_progress(len(voiced), total_segments)
    _evict_cache(cache_dir, _CACHE_MAX_BYTES)

    # 布局分发（2026-10-06 业主裁决「先出语音、再选画面」）：超短（带候选池）与
    # 交叉的时间轴在编排期只是占位（超短三拍互相重叠、交叉桥段叠在下个场景开头），
    # 实测时长到手后按模式规则**整体重铺**；其余模式（intro/full/ducker/对谈/
    # 独白/剧本驱动）时间轴承载语义（闪前预告、ASR 吸附、台词对位），走下方的
    # 游标修补——修补的头部扩展/尾部收口对所有模式仍是兜底。
    #
    # 装不下的段不再判死（业主裁决 2026-10-26「素材时长不够，或者太长，应该重新
    # 选取判断，而不是失败」）：重排 → 定向收短重写 → 重合成 → 重回排，至多两轮；
    # 仍放不下的段弃用留痕，成片继续。超短模式自带候选池全量重选与如实报错语义，
    # 不进重写循环。
    timeline: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    # 跨轮最大空隙账（#16）：桥段改锚后空隙变化，本轮首选空隙小于历史最大时
    # 收短目标会被压得过狠——按每槽历史最大空隙定目标，改锚腾出的空间用得上。
    gap_best: dict[str, float] = {}
    fit_stats = {"rewritten": 0, "accepted": 0, "rejected_same": 0, "rejected_long": 0,
                 "resynth_fail": 0, "rounds": 0}
    for attempt in range(3):
        if plan.mode == "ultra_short_hook" and plan.scene_pool:
            timeline = _layout_ultra_short(plan, voiced, source_durations, log)
            unplaced = []
            break
        if plan.mode == "cross_narration":
            timeline, unplaced = _layout_cross(
                plan, voiced, source_durations, log, scene_cuts, dialogue_spans
            )
        else:
            timeline, unplaced = _patch_timeline(
                plan, voiced, source_durations, scene_cuts, dialogue_spans
            )
        if not unplaced or rewrite_for_fit is None or attempt >= 2:
            break
        for entry in unplaced:
            gap_best[str(entry["slot"])] = max(
                gap_best.get(str(entry["slot"]), 0.0), float(entry["gap_s"])
            )
        enriched = [
            {
                **entry,
                "gap_s": max(float(entry["gap_s"]), gap_best.get(str(entry["slot"]), 0.0)),
            }
            for entry in unplaced
        ]
        fit_stats["rounds"] += 1
        stats = _rewrite_and_resynth(
            enriched,
            voiced,
            plan,
            pool,
            settings,
            speed,
            work_dir,
            cache_dir,
            rewrite_for_fit,
            log,
        )
        for key in ("rewritten", "accepted", "rejected_same", "rejected_long", "resynth_fail"):
            fit_stats[key] += stats[key]
        if stats["accepted"] == 0:
            break
    for entry in unplaced:
        _emit(
            log,
            f"旁白 {entry['slot']} 实测 {entry['duration']:.2f}s，最大可用空隙只有 "
            f"{entry['gap_s']:.2f}s，收短重写后仍放不下——该段弃用，成片继续"
            f"（不裁音、不重播）：{entry['text'][:24]}…",
            "warn",
        )
    if unplaced:
        _emit(log, f"共 {len(unplaced)} 段旁白放不进画面空隙被弃用", "warn")
    # fit 遥测（#17）：空转与否不再靠翻日志——一轮汇总进任务详情，喂持续优化。
    if fit_stats["rounds"] > 0:
        _emit(
            log,
            "fit 重排循环：{rounds} 轮，重写 {rewritten} 段（采纳 {accepted}，"
            "原文打回 {rejected_same}，超目标打回 {rejected_long}，合成失败 "
            "{resynth_fail}），最终弃段 {dropped}".format(dropped=len(unplaced), **fit_stats),
        )
    _assert_within_source(timeline, source_durations)
    updated = [
        item.model_copy(
            update={
                "audio_path": voiced[item.id][0],
                "duration": voiced[item.id][2],
                # 定向重写后文案已换血（voiced 里存的是实际配音文本），方案里的
                # narration_texts 必须同步，否则详情页展示的还是收短前的旧稿。
                "text": voiced[item.id][1],
            }
        )
        for item in plan.narration_texts
    ]
    # timeline 是裸 dict，必须过 model_validate 才是模型实例，导出层按属性读段
    laid = PlanData.model_validate(
        {
            **plan.model_dump(),
            "narration_texts": updated,
            "timeline": timeline,
            "compute": [report.to_dict() for report in pool.compute_reports()],
        }
    )
    # 转场判定按最终窗口重算：此前只有超短/交叉重铺后重算，走游标修补的模式
    # 段界被挪后 fade/cut 判定失真（该 cut 处叠 fade，2026-10-27 审计）。
    laid = apply_transitions(laid)
    # 结构最终防线：重铺产物不回写 plan_data，export 门的 defects 查的还是
    # 占位时间轴——负起点/非正窗若不在这一步拦下就直接进 ffmpeg（静默截断或
    # 坏片）。与「素材不 fit 重新选取而非失败」不冲突：那是间隙预算问题（上面
    # 已由重写循环+弃段留痕消化），这里是布局代码必须保证的硬不变量。
    structural = structural_defects(laid)
    if structural:
        raise RuntimeError(
            "配音后重铺产出结构缺陷（布局 bug，请反馈日志）："
            + "；".join(structural)
        )
    return laid

