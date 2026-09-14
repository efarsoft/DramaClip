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
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    material: MaterialByEpisode,
    settings: dict[str, str],
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。

    场景表带集身份（`casting.EpisodeScene`），故一条方案的时间轴可以含多集的段
    （规格 §1「每模式产出 1..K 条卖点角度互异的**跨集**方案」）；段的 `episode_id`
    由场景自己带，不再有"这一条片属于哪一集"这个入参。

    **原签名的 `episode_id: str` 与 `audio: AudioFeatures` 两个入参都随本次改写消失**：
    前者被逐场景的集身份取代；后者是**死参数**——原函数体从头到尾没有一处引用 `audio`
    （九个分派分支只往下传 conflict_scores / highlights / asr_segments / strategy），
    而它唯一的调用点为它专门调了一次 `parse_audio_features`。在一个刚被重写的签名里
    留着一个没人读的 `audio` 形参，等于告诉下一个人"音频特征参与编排"。
    """
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "120")),
    )
    if mode == "raw_clip":
        return modes.build_raw_clip(scenes, highlights, strategy)
    if mode == "intro_narration":
        return modes.build_intro(scenes, strategy)
    if mode == "cross_narration":
        return modes_w5.build_cross(scenes, strategy)
    if mode == "ultra_short_hook":
        return modes_w5.build_ultra_short(scenes, strategy)
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return modes_w8.build_full(scenes, strategy)
    if mode == "subtitle_flow":
        return modes_w9.build_subtitle_flow(scenes, material, strategy)
    if mode == "dual_host_chat":
        return modes_p2.build_dual_host(scenes, strategy)
    if mode == "inner_monologue":
        return modes_p2.build_monologue(scenes, strategy)
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


def top_conflict_windows(
    episodes: list[tuple[int, list[ConflictScore]]],
    limit: int,
) -> list[tuple[int, ConflictScore]]:
    """全剧 top-K 冲突窗，**按集去重**（每集只留它排名最高的那一窗），按窗口名次返回。

    规格 §4.3 ④：「条数按模式族分别算：解说类 = K，规则类 = 全剧 top-K 冲突窗
    （两者不同源，已由用户定案）」。规则类两模式（`raw_clip` / `subtitle_flow`）
    不经选题模型（规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」），
    它们的条数因此必须另有一个来源，就是这个榜单。**本函数不发任何网络请求。**

    为什么按集去重：`build_raw_clip` 与 `build_subtitle_flow` 都是**确定性纯函数**——
    同一组的两个不同窗口喂进去会得到逐字节相同的方案。那不是 K 条互异，是 1 条复制 K 份，
    而且会被 `overlap` 判成 100% 重叠、把 K-1 条报成失败。所以"窗"在这里的作用是把
    **集**排出名次；排完由下面的 `deal_windows` 轮转发成 K 手，一手一条方案。

    **仍然做不到的那一半，写在这里而不是藏在代码里**：让每条方案的内容真的等于它那一窗。
    原先的理由是技术的（`ConflictScore` 不带集身份、`_fit_duration` 按单集截断），
    **那个前提已经被 Task 3c 拆掉了**：集身份有了（`casting.EpisodeScene`），预算也重分了
    （末场景豁免删掉、引子槽位预留 `_INTRO_MAX_S`）。剩下的理由是**产品**的：一个窗是
    3-25s，"内容 = 一窗"会让 `raw_clip` 的每条方案掉到 3-25 秒，而活库实测今天它是
    15.13s（三个场景）。所以本函数交付的是"用全剧冲突榜决定**条数与每条的取材集组合**"，
    不是"每条方案就是一窗"。这个差别记在计划《定案四》末段与《开放问题》#1，不藏在这里。

    排序键 `(-score, 集号, scene_index)`：分析层给的是 0-100 的**整数**分，同分在全剧
    尺度上是常态；只按 -score 排时结果稳定于**输入顺序**，而输入顺序来自
    `episodes_repo.list_by_project`，那个顺序没有契约。补两个次键才有"整组重规划可复现"。

    返回条数可以少于 limit（集不够）。规格 §1 的原话是「每模式产出 **1..K** 条」，
    少出是合法形状；**但调用方必须留痕**（规格 §3.3 静默禁止），见 `api/narration.py`
    的 `_rule_variants`。本函数自己不发明错误语义：空榜就返回空表。

    `limit < 1` 抛 ValueError：与 `angles.select_angles` 的 `k < 1` 同一口径——
    条数是调用方的契约，不该在这里静默变成空表。
    """
    if limit < 1:
        raise ValueError(f"窗口数 limit 必须 ≥ 1，实得 {limit}")
    ranked = sorted(
        ((number, scene) for number, scenes in episodes for scene in scenes),
        key=lambda item: (-item[1].score, item[0], item[1].scene_index),
    )
    picked: list[tuple[int, ConflictScore]] = []
    seen: set[int] = set()
    for number, scene in ranked:
        if number in seen:
            continue
        seen.add(number)
        picked.append((number, scene))
        if len(picked) == limit:
            break
    return picked


def deal_windows(
    windows: list[tuple[int, ConflictScore]], hands: int
) -> list[list[int]]:
    """把排名后的冲突窗**轮转**发成 hands 手，每手是它拿到的集号（升序、手间互不相交）。

    规格 §4.3 ④ 定的是**条数**（「规则类 = 全剧 top-K 冲突窗」），规格 §1 定的是
    **每条方案的形状**（「跨集方案」）。一集一条满足前者、违反后者；把窗轮转发成 K 手
    同时满足两者，而且手与手拿到的是**互不相交的集**，于是取材重叠恒为 0——不必等
    `overlap` 事后拦（《定案四》第 2 点原本靠"按集去重"换来的那条性质，跨集之后由
    "手间不共集"接着保证）。

    轮转（第 j 手拿排名 j, j+hands, j+2·hands …）而不是切块（前几集全给第 1 手）：
    切块会让第 1 手独占全剧最狠的几集，三条片的强弱差一个量级；轮转让每手都拿到
    一个高分窗，强弱可比。**实测**（活库十集、K=3）：排名 `[6,7,8,2,3,4,9,10,1,5]`
    → `[[2,5,6,9],[3,7,10],[1,4,8]]`。

    返回条数可以少于 hands（集不够）：规格 §1 允许「每模式产出 1..K 条」，
    少出由调用方留痕（`api/narration.py::_rule_variants`），不在这里发明错误语义。
    **集数 < 2 × hands 时每手会退化成一集**（3 集发 3 手就是 1/1/1），
    那不是缺陷是算术：互不相交的多集手至少需要 2 × hands 集。调用方必须留痕。
    `hands < 1` 抛，与 `top_conflict_windows` 的 `limit < 1` 同一口径。
    """
    if hands < 1:
        raise ValueError(f"手数 hands 必须 ≥ 1，实得 {hands}")
    dealt: list[list[int]] = [[] for _ in range(min(hands, len(windows)))]
    for rank, (number, _scene) in enumerate(windows):
        dealt[rank % len(dealt)].append(number)
    return [sorted(hand) for hand in dealt]


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
    否则下一轮会把它当缓存命中）与并发写同名文件（同模式的 K 条变体、以及执行池里
    并行的多个规划作业都可能同时写一个 slot_id，hardware.max_parallel_jobs 默认 2）
    ——os.replace 原子换入，读者永远只见完整文件。
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
