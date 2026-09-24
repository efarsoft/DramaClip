"""解说管线：分析结果 → 规则编排（除剧情解说外的八模式）+ 剧本驱动装配 + TTS 合成回填。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
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
from dramaclip.infra.ffmpeg import runner as ffmpeg_runner

logger = logging.getLogger(__name__)

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
        return apply_transitions(modes_w5.build_cross(scenes, strategy, material))
    if mode == "ultra_short_hook":
        return apply_transitions(modes_w5.build_ultra_short(scenes, strategy, material))
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
    work_dir: Path, slot_id: str, text: str, voice: str, engine: str, speed: str = ""
) -> Path:
    """音频文件名内容寻址：影响成品的输入 (text, voice, engine, speed) 全部进哈希。"""
    digest = hashlib.sha1(
        f"{text}|{voice}|{engine}|{speed}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return work_dir / f"{slot_id}-{digest}.mp3"


def _synthesize_into(
    engine: tts_base.TtsEngine,
    engine_name: str,
    text: str,
    voice: str,
    speed: str,
    final_path: Path,
    cache_dir: Path,
) -> None:
    """缓存优先 + 暂存落位：命中即复用，未命中先写临时名、成功后原子搬进最终路径。

    两层缓存判据：
    1. 目标路径已存在且非空 → 直接跳过（既有判据，内容寻址文件名兜住参数变化）；
    2. 内容寻址缓存 `cache_dir/sha256(text|engine|voice|speed).<ext>` 命中 →
       copy 落位（改一句只重合成一段，未改的段落不二次付费）；
    3. 都未命中 → 真合成，成功后写入缓存再原子落位。
    """
    if _usable(final_path):
        return
    cache_entry = _cache_entry_for(cache_dir, text, engine_name, voice, speed)
    if cache_entry is not None:
        tmp = final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex}{final_path.suffix}")
        try:
            shutil.copyfile(cache_entry, tmp)
            os.replace(tmp, final_path)
            return
        finally:
            tmp.unlink(missing_ok=True)
    # uuid 插进主干、保留最终扩展名：soundfile/edge 都靠扩展名推断音频格式，
    # 以 .part 结尾会让 sf.write 直接抛 TypeError。
    staging = final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex}{final_path.suffix}")
    try:
        engine.synthesize(text, voice, staging)
        _store_in_cache(staging, cache_dir, text, engine_name, voice, speed)
        os.replace(staging, final_path)
    finally:
        staging.unlink(missing_ok=True)


def _usable(path: Path) -> bool:
    """非空文件才算数：0 字节占位残留（历史脏产物）不是缓存命中。"""
    return path.is_file() and path.stat().st_size > 0


# ---- A5 内容寻址合成缓存 -----------------------------------------------
# key = sha256(text|engine|voice|speed)。引擎没有可用的版本标识（TtsEngine 协议
# 只有 name，本地引擎也无从廉价取到模型版本），key 就是这四个量；日后引擎换代
# 需要整体作废旧缓存时，改 key 组成即等于换 schema。
_CACHE_MAX_BYTES = 2 * 1024**3  # 2GB 容量上限（治理是 best-effort，永不 raise）


def _cache_key(text: str, engine_name: str, voice: str, speed: str) -> str:
    return hashlib.sha256(f"{text}|{engine_name}|{voice}|{speed}".encode()).hexdigest()


def _cache_entry_for(
    cache_dir: Path, text: str, engine_name: str, voice: str, speed: str
) -> Path | None:
    """命中返回缓存文件路径，未命中返回 None。任何探测异常都当未命中。"""
    try:
        key = _cache_key(text, engine_name, voice, speed)
        for candidate in cache_dir.glob(f"{key}.*"):
            if _usable(candidate):
                return candidate
    except OSError:
        pass
    return None


def _store_in_cache(
    source: Path, cache_dir: Path, text: str, engine_name: str, voice: str, speed: str
) -> None:
    """合成成功后写入缓存条目；失败静默放弃（缓存是加速层，不是正确性层）。"""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _cache_key(text, engine_name, voice, speed)
        shutil.copyfile(source, cache_dir / f"{key}{source.suffix}")
    except OSError as exc:
        logger.debug("TTS 缓存写入失败（忽略）: %s", exc)


def _evict_cache(cache_dir: Path, max_bytes: int) -> None:
    """超上限按 mtime 淘汰最旧文件至上限内。best-effort：任何失败都不 raise。"""
    try:
        entries = [
            (p.stat().st_mtime, p.stat().st_size, p)
            for p in cache_dir.iterdir()
            if p.is_file()
        ]
    except OSError:
        return
    total = sum(size for _mtime, size, _p in entries)
    if total <= max_bytes:
        return
    for _mtime, size, path in sorted(entries, key=lambda item: item[0]):
        if total <= max_bytes:
            break
        try:
            path.unlink()
            total -= size
        except OSError as exc:  # 占用/只读/已消失：跳过这一条，继续淘汰别的
            logger.debug("TTS 缓存淘汰失败（忽略）: %s", exc)


# ---- B1 引擎解析：显式不回退，auto 才回退且留痕 ---------------------------
# auto 链首是 edge：与历史默认 settings.get("tts.engine", "edge") 行为一致。
_AUTO_CHAIN = ("edge", "kokoro", "indextts2")

LogFn = Callable[[str, str], None]


def _is_auto(engine_setting: str) -> bool:
    return engine_setting.strip().lower() in ("", "auto")


def _emit(log: LogFn | None, message: str, level: str = "info") -> None:
    (logger.warning if level == "warn" else logger.info)("%s", message)
    if log is not None:
        log(level, message)


# ---- 批次二：hook 槽位对齐策略机 ------------------------------------------
# DramaClip「时长服从故事」：narration 段长=实测音频时长，全片只有一个硬槽位——
# intro_narration 首段（narration_id=intro-1），编排层 `_fit_duration(intro_first)`
# 把它钳到 `modes._INTRO_MAX_S`。策略机只约束这一个槽位，其余段（含剧本驱动的
# n0 钩子，长度=实测音频，没有槽位）绝不变速。这是 hook 节奏优化（封面级增强），
# 不是正确性门禁：任何 ffmpeg 失败都保留原音频 + warn，绝不 raise。
_HOOK_SLOT_ID = modes._INTRO_SLOT_ID
_HOOK_SLOT_MAX_S = modes._INTRO_MAX_S
_RETIME_MAX_RATIO = 1.5  # 超过 1.5 倍拒绝自动变速：atempo 拉太狠听感会坏（业主质量线）
_SLOT_FIT_TOL_S = 0.05  # 复测收口容差：atempo=ratio 的产物理应≈槽位，留浮点/编码栅格余量


def _align_to_hook_slot(
    item_id: str, audio_path: Path, duration: float, log: LogFn | None
) -> tuple[Path, float]:
    """hook 槽位对齐：实测 vs 槽位上限，ratio 分档决策，每档都经 log 回调留痕。

    - ratio ≤ 1.0：不动（decision=keep）；
    - 1.0 < ratio ≤ 1.5：一次 ffmpeg atempo（变速不变调）压进槽位，复测定去留；
    - ratio > 1.5：拒绝自动变速（decision=reject），warn 带实测/槽位/ratio，
      让人知道该改文案或换音色。

    变速产物落 `目标路径-atempo.后缀`（work_dir 内的派生文件），**不回写内容寻址
    目标、也不进缓存**：缓存 key=sha256(text|engine|voice|speed) 没有变速维度，
    变速产物一旦入缓存就是同 key 不同字节，破坏「命中即等价重合成」的契约。
    原始干音仍是缓存里的那份，改文案重合成时策略机会对新实测重新决策。
    """
    if item_id != _HOOK_SLOT_ID:
        return audio_path, duration  # 非槽位段：时长服从故事，禁止任何 atempo
    ratio = duration / _HOOK_SLOT_MAX_S
    head = (
        f"旁白 {item_id} hook 槽位对齐: 实测={duration:.2f}s"
        f" 槽位={_HOOK_SLOT_MAX_S:.2f}s ratio={ratio:.2f}"
    )
    if ratio <= 1.0:
        _emit(log, f"{head} decision=keep（槽位内，不动）")
        return audio_path, duration
    if ratio > _RETIME_MAX_RATIO:
        _emit(
            log,
            f"{head} decision=reject —— 超 {_RETIME_MAX_RATIO} 倍拒绝自动变速"
            "（听感优先），请改短文案或换音色",
            level="warn",
        )
        return audio_path, duration
    derived = audio_path.with_name(f"{audio_path.stem}-atempo{audio_path.suffix}")
    try:
        # atempo ∈ [0.5, 100]，本档 ratio ≤ 1.5 恒在范围内，单 filter 一次变速即可
        ffmpeg_runner.run(
            [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(audio_path),
                "-filter:a",
                f"atempo={ratio:.6f}",
                str(derived),
            ]
        )
        retimed = tts_base.audio_duration_s(derived)
        if not _usable(derived) or retimed <= 0:
            raise RuntimeError(f"变速产物不可用（复测 {retimed}s）")
    except Exception as exc:  # noqa: BLE001 - 节奏优化失败不拦方案，诚实 warn 后保留原音频
        derived.unlink(missing_ok=True)
        _emit(
            log,
            f"{head} decision=atempo_failed —— atempo 变速失败"
            f"（{type(exc).__name__}: {exc}），保留原音频",
            level="warn",
        )
        return audio_path, duration
    if retimed <= _HOOK_SLOT_MAX_S + _SLOT_FIT_TOL_S:
        _emit(
            log,
            f"{head} decision=atempo atempo={ratio:.6f} 变速后={retimed:.2f}s（已入槽）",
        )
        return derived, retimed
    # 1.15 < ratio ≤ 1.5 档也可能落到这里（atempo 实际压缩不足）：接受变短了的
    # 产物但必须 warn——静默超槽等于把问题藏给下游渲染。
    _emit(
        log,
        f"{head} decision=retime_overrun atempo={ratio:.6f} 变速后={retimed:.2f}s"
        f" 仍超槽位 {_HOOK_SLOT_MAX_S:.2f}s，接受现状",
        level="warn",
    )
    return derived, retimed


class _EnginePool:
    """一次配音任务的引擎解析与逐段合成。

    显式引擎（`tts.engine` 是具体名字）：只此一个，构造失败当场抛（未知引擎的
    ValueError 原样透传），合成失败原样抛——绝不静默换引擎（JJYB 纪律：克隆
    音色失败落到 edge 默认音 = 人设声音变了还查不出来）。
    auto/未配置：按 _AUTO_CHAIN 顺序试，构造或合成失败就带着原因试下一个，
    每段成功后把 engine_requested/engine_used/fallback_used/fallback_reason
    写进溯源日志（log 回调 + 模块级 logger 双写）。
    """

    def __init__(
        self, setting: str, models_dir: Path | None, log: LogFn | None
    ) -> None:
        self._setting = setting
        self._explicit = not _is_auto(setting)
        self._requested = setting.strip() if self._explicit else "auto"
        self._names: tuple[str, ...] = (
            (self._requested,) if self._explicit else _AUTO_CHAIN
        )
        self._models_dir = models_dir
        self._log = log
        self._instances: dict[str, tts_base.TtsEngine] = {}
        if self._explicit:
            # 显式引擎构造失败必须当场炸（未知引擎名 = 配置错误，不许当 auto 兜走）
            self._instances[self._requested] = create_tts(self._requested, models_dir)

    @property
    def label(self) -> str:
        return self._requested

    def voice_for(self, settings: dict[str, str]) -> str:
        """音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库。"""
        return settings.get(f"tts.voice.{self._setting}") or settings.get("tts.voice") or ""

    def synthesize_item(
        self,
        item_id: str,
        text: str,
        voice: str,
        speed: str,
        work_dir: Path,
        cache_dir: Path,
    ) -> Path:
        """合成一段，返回落位后的音频路径；全链失败抛 RuntimeError（逐因带出）。"""
        reasons: list[str] = []
        for name in self._names:
            engine = self._instances.get(name)
            if engine is None:
                try:
                    engine = create_tts(name, self._models_dir)
                except Exception as exc:  # noqa: BLE001 - auto 链跳过构造不了的引擎
                    reasons.append(f"{name}: 构造失败 {type(exc).__name__}: {exc}")
                    continue
                self._instances[name] = engine
            target = _content_addressed_audio(work_dir, item_id, text, voice, name, speed)
            try:
                _synthesize_into(engine, name, text, voice, speed, target, cache_dir)
            except Exception as exc:
                if self._explicit:
                    raise  # 显式引擎：原因原样上抛，由调用方带 item_id 包装，绝不换引擎
                reasons.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            fallback_used = bool(reasons)
            _emit(
                self._log,
                f"旁白 {item_id} 语音合成: engine_requested={self._requested}"
                f" engine_used={name} fallback_used={fallback_used}"
                f" fallback_reason={'; '.join(reasons)}",
            )
            return target
        raise RuntimeError(f"auto 回退链全员失败: {'; '.join(reasons)}")



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
    log: LogFn | None = None,
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    `source_durations` 是 {集 id: 源片秒数}，必填而非可选：回填会把段尾改成
    `start + 实测音频时长`，只有拿到源长才知道这个窗口还在不在素材里。给默认值
    就等于给「跳过检查」开门，而跳过检查的代价是成片把旁白说到一半掐掉（见
    `_assert_within_source`）。

    `log` 是可选的 (level, message) 回调（api 侧接 notifier.log），每段合成都会
    留下 engine_requested/engine_used/fallback_used/fallback_reason 溯源记录；
    不传则只写模块级 logger。引擎纪律见 `_EnginePool`：显式不回退，auto 才回退。
    """
    _assert_voiceable(plan)
    if not plan.narration_texts:
        return plan
    engine_setting = settings.get("tts.engine", "")
    pool = _EnginePool(engine_setting, models_dir, log)
    # 音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库。
    # auto 链下每段可能落在不同引擎上，段级 voice 缺省时逐引擎取键。
    speed = str(settings.get("tts.speed", "") or "")
    cache_dir = work_dir / "cache"
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    for item in plan.narration_texts:
        # 段级 voice 优先（双人对谈的双音色），缺省用全局设置
        voice = item.voice or pool.voice_for(settings)
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
    _evict_cache(cache_dir, _CACHE_MAX_BYTES)

    timeline = [segment.model_dump() for segment in plan.timeline]
    # 实测音频时长 ≠ 编排期的估计时长：把 end 直接改成 start + 实测，前一段就会
    # 盖住后一段的源素材区间，成片演到第 6 秒又倒回第 1 秒重播同一段画面（业主
    # 立案③）。这里按集重走一遍编排层同款游标（`build_from_script_episodes` 的
    # `start = max(candidate, cursor)`）：只保证源时间单调不回退，旁白段长度
    # 仍等于实测音频，原声段只平移不压缩。
    #
    # 例外（B 项·片头闪前预告）：`build_intro` 把最高冲突镜前置做首帧，片头旁白
    # 讲最大冲突、画面是后段的高潮镜，正文再从头讲——片头对同集后续段是**有意**的
    # 源时间倒回（与 raw_clip 的预告式开场同构），不是立案③那种回填抖动导致的意外
    # 重播。若让片头照常推进游标，游标会把正文挤到预告之后、甚至冲出源集末尾
    # （真机探针：前置 94-100s 的片尾镜 + 8s 钩子 TTS，正文 0-6s 被顶到 106 > 源长
    # 100，整条方案响亮失败）。故闪前预告段不推进游标，正文从自己的计划起点重新起算。
    # 判据：片头段（intro-1 槽位）的计划源起点晚于其后任一**同集**段的计划源起点 ⇒
    # 闪前预告；最高冲突镜本就是时序第一镜（未前置）时片头是普通时序段，游标照常推进，
    # 立案③的重播保护不受影响。
    _planned_starts = [float(segment["start"]) for segment in timeline]
    _intro_teaser = False
    if timeline and timeline[0].get("narration_id") == _HOOK_SLOT_ID:
        _head_episode = str(timeline[0]["episode_id"])
        _intro_teaser = any(
            str(segment["episode_id"]) == _head_episode
            and _planned_starts[index] < _planned_starts[0]
            for index, segment in enumerate(timeline[1:], start=1)
        )
    cursor: dict[str, float] = {}
    for index, segment in enumerate(timeline):
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
        if index == 0 and _intro_teaser:
            continue  # 闪前预告不推进游标：正文从自己的计划起点起算（见上方判据注释）
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


