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
    "highlight_cut": "高光混剪",
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
    source_durations: dict[str, float] | None = None,
    golden_lines: dict[str, list[tuple[float, float]]] | None = None,
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。

    `source_durations`（{集 id: 源片秒数}）可选，供超短钩子做可行性选景——
    钩子/CTA 的画面预算要在规划期就知道放不放得下，不能等 TTS 实测才爆。
    """
    strategy = StrategySpec(platform="douyin")
    if mode == "raw_clip":
        return apply_transitions(modes.build_raw_clip(scenes, highlights, strategy))
    if mode == "highlight_cut":
        return apply_transitions(modes.build_highlight_cut(scenes, strategy))
    if mode == "intro_narration":
        return apply_transitions(modes.build_intro(scenes, strategy))
    if mode == "cross_narration":
        return apply_transitions(modes_w5.build_cross(scenes, strategy, material))
    if mode == "ultra_short_hook":
        return apply_transitions(
            modes_w5.build_ultra_short(scenes, strategy, material, source_durations)
        )
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return apply_transitions(modes_w8.build_full(scenes, strategy))
    if mode == "subtitle_flow":
        return apply_transitions(
            modes_w9.build_subtitle_flow(scenes, material, strategy, golden_lines)
        )
    if mode == "dual_host_chat":
        return apply_transitions(modes_p2.build_dual_host(scenes, strategy))
    if mode == "inner_monologue":
        return apply_transitions(modes_p2.build_monologue(scenes, strategy))
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")


_NEAR_GAP_S = 1.0  # 近邻衔接阈值：段间隔小于此值视为同镜头连续推进
# 镜头切点外扩吸附容差：0.7s 内有切点就扩过去（start 前扩/end 后扩，只加余地不吞内容）；
# 更宽会把解说与画面的对应关系拉远，更窄则大部分切点够不着。
_SHOT_TOL_S = 0.7
# 接缝判定：段开口与切点距离小于此值视为「落在换镜头上」（转 fade→cut 的依据）。
_SHOT_JOINT_EPS_S = 0.2

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
        self,
        setting: str,
        models_dir: Path | None,
        log: LogFn | None,
        api_key: str = "",
    ) -> None:
        self._setting = setting
        self._explicit = not _is_auto(setting)
        self._requested = setting.strip() if self._explicit else "auto"
        self._names: tuple[str, ...] = (
            (self._requested,) if self._explicit else _AUTO_CHAIN
        )
        self._models_dir = models_dir
        self._log = log
        self._api_key = api_key
        self._instances: dict[str, tts_base.TtsEngine] = {}
        if self._explicit:
            # 显式引擎构造失败必须当场炸（未知引擎名 = 配置错误，不许当 auto 兜走）
            self._instances[self._requested] = create_tts(
                self._requested, models_dir, api_key=api_key
            )

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
                    engine = create_tts(name, self._models_dir, api_key=self._api_key)
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
    on_progress: Callable[[int, int], None] | None = None,
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
    pool = _EnginePool(engine_setting, models_dir, log, api_key=settings.get("tts.api_key", ""))
    # 音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库。
    # auto 链下每段可能落在不同引擎上，段级 voice 缺省时逐引擎取键。
    speed = str(settings.get("tts.speed", "") or "")
    cache_dir = work_dir / "cache"
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    total_segments = len(plan.narration_texts)
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
        if on_progress is not None:
            on_progress(len(voiced), total_segments)
    _evict_cache(cache_dir, _CACHE_MAX_BYTES)

    # 布局分发（2026-10-06 业主裁决「先出语音、再选画面」）：超短（带候选池）与
    # 交叉的时间轴在编排期只是占位（超短三拍互相重叠、交叉桥段叠在下个场景开头），
    # 实测时长到手后按模式规则**整体重铺**；其余模式（intro/full/ducker/对谈/
    # 独白/剧本驱动）时间轴承载语义（闪前预告、ASR 吸附、台词对位），走下方的
    # 游标修补——修补的头部扩展/尾部收口对所有模式仍是兜底。
    if plan.mode == "ultra_short_hook" and plan.scene_pool:
        timeline = _layout_ultra_short(plan, voiced, source_durations, log)
    elif plan.mode == "cross_narration":
        timeline = _layout_cross(plan, voiced, source_durations, log)
    else:
        timeline = _patch_timeline(plan, voiced, source_durations)
    _assert_within_source(timeline, source_durations)
    updated = [
        item.model_copy(
            update={"audio_path": voiced[item.id][0], "duration": voiced[item.id][2]}
        )
        for item in plan.narration_texts
    ]
    # timeline 是裸 dict，必须过 model_validate 才是模型实例，导出层按属性读段
    laid = PlanData.model_validate(
        {**plan.model_dump(), "narration_texts": updated, "timeline": timeline}
    )
    if plan.mode in ("ultra_short_hook", "cross_narration"):
        # 重铺改变了相邻关系，规划期的转场判定过期：按新窗口重算 fade/cut
        laid = apply_transitions(laid)
    return laid


def _layout_ultra_short(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
    log: LogFn | None,
) -> list[dict[str, Any]]:
    """超短三拍整体重铺：候选池按实测时长选景，三拍精确落位、互不重叠。

    候选窗按分值序找第一个「场景前放得下钩子实测、集尾放得下 CTA 实测」的；
    全都放不下 → 如实报错并给出各候选差多少秒，不静默、不裁剪（业主裁决）。
    钩子尾锚冲突窗开头（讲完正好进正片）、原声拍原样、CTA 接在窗后。
    """
    missing = [slot for slot in ("hook-1", "cta-1") if slot not in voiced]
    if missing:
        raise RuntimeError(f"超短方案缺 {'、'.join(missing)} 槽位的实测音频，无法布局")
    conflict = next(
        (segment for segment in plan.timeline if segment.audio == "original"), None
    )
    if conflict is None:
        raise RuntimeError("超短方案时间轴里没有冲突原声拍，无法布局")
    hook_dur = voiced["hook-1"][2]
    cta_dur = voiced["cta-1"][2]

    def _placed(episode_id: str, win_start: float, win_end: float) -> list[dict[str, Any]]:
        return [
            {
                "episode_id": episode_id,
                "start": round(win_start - hook_dur, 3),
                "end": round(win_start, 3),
                "audio": "narration",
                "narration_id": "hook-1",
                "subtitle_text": voiced["hook-1"][1],
            },
            {
                "episode_id": episode_id,
                "start": round(win_start, 3),
                "end": round(win_end, 3),
                "audio": "original",
            },
            {
                "episode_id": episode_id,
                "start": round(win_end, 3),
                "end": round(win_end + cta_dur, 3),
                "audio": "narration",
                "narration_id": "cta-1",
                "subtitle_text": voiced["cta-1"][1],
            },
        ]

    shortfalls: list[str] = []
    for candidate in plan.scene_pool:
        limit = source_durations.get(candidate.episode_id, 0.0)
        if limit <= 0:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s 查不到集时长"
            )
            continue  # 与守卫同口径：查不了 = 放不下，换下一个
        if candidate.start < hook_dur:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s "
                f"场景前素材 {candidate.start:.1f}s < 钩子 {hook_dur:.1f}s"
            )
            continue
        if candidate.end + cta_dur > limit + _SOURCE_FIT_TOL_S:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s "
                f"集尾差 {candidate.end + cta_dur - limit:.1f}s"
            )
            continue
        _emit(
            log,
            f"超短布局按实测时长选中冲突窗 {candidate.episode_id} "
            f"{candidate.start:.2f}-{candidate.end:.2f}s"
            f"（钩子 {hook_dur:.1f}s + CTA {cta_dur:.1f}s）",
        )
        return _placed(candidate.episode_id, candidate.start, candidate.end)
    raise RuntimeError(
        "候选池里没有放得下实测时长的冲突窗（"
        + "；".join(shortfalls)
        + "）——重新生成方案即可换一批候选，文案与音频一秒不裁"
    )


def _layout_cross(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
    log: LogFn | None,
) -> list[dict[str, Any]]:
    """交叉解说桥段落位：场景原声窗原封不动，桥段旁白放进场景间空隙。

    旧布局把桥段叠在下个场景开头（与场景窗设计性重叠），IndexTTS 实测一超长
    就把场景顶出集尾（真机 2026-10-06：cross-3 差 0.16s 整条判死）。场景窗吸附
    过最强台词 span，挪了就不是那句台词——所以桥段改为收尾锚在下个场景开头、
    向前伸进空隙；末段桥（没有下一场景）接在自己场景窗之后。空隙放不下如实报错。
    """
    segments = plan.timeline
    timeline: list[dict[str, Any]] = []
    cursor: dict[str, float] = {}
    for index, segment in enumerate(segments):
        if segment.audio != "narration":
            entry = segment.model_dump()
            timeline.append(entry)
            cursor[segment.episode_id] = float(entry["end"])
            continue
        slot = str(segment.narration_id or "")
        voiced_entry = voiced.get(slot)
        if voiced_entry is None:
            raise RuntimeError(f"交叉桥段 {slot} 没有实测音频，无法布局")
        _audio_path, text, duration = voiced_entry
        next_original = next(
            (s for s in segments[index + 1 :] if s.audio != "narration"), None
        )
        if next_original is None:
            start = cursor.get(segment.episode_id, float(segment.start))
        else:
            start = float(next_original.start) - duration
            floor = cursor.get(next_original.episode_id, 0.0)
            if start < floor:
                raise RuntimeError(
                    f"交叉桥段 {slot} 实测 {duration:.2f}s，但 "
                    f"{next_original.episode_id} 场景 {next_original.start:.2f}s 前的"
                    f"空隙只有 {float(next_original.start) - floor:.2f}s——"
                    "空隙放不下，这条方案判失败（不裁音、不重播）"
                )
        end = start + duration
        timeline.append(
            {
                "episode_id": segment.episode_id,
                "start": round(start, 3),
                "end": round(end, 3),
                "audio": "narration",
                "narration_id": slot,
                "subtitle_text": text,
            }
        )
        cursor[segment.episode_id] = end
    _emit(
        log,
        f"交叉布局按实测时长把 {sum(1 for s in timeline if s['audio'] == 'narration')}"
        "段桥旁白放进场景间空隙，场景原声窗原样保留",
    )
    return timeline


def _patch_timeline(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
) -> list[dict[str, Any]]:
    """游标修补（既有回填语义）：旁白段长=实测音频，头部扩展→尾部收口→守卫。"""
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
        planned_start = float(segment["start"])
        planned_end = float(segment["end"])
        start = max(planned_start, floor)
        if segment["audio"] in ("narration", "ducked"):
            # ducked（全片解说全程压底旁白）与 narration 同权：两者都要回填时长与解说字幕
            _audio_path, text, duration = voiced[str(segment["narration_id"])]
            segment["subtitle_text"] = text
            length = duration
        else:
            length = planned_end - planned_start
        limit = source_durations.get(episode_id, 0.0)
        # 头部扩展（2026-10-06 业主裁决「保障素材时长，不裁」）：实测旁白比计划窗口
        # 长时，先保住计划尾——配哪几秒画面是编排选好的——把起点往前伸。吃的是
        # 上一段与本段之间的空闲素材：不偷后段的画面（立案③），不把已计划素材
        # 推出集尾。伸不动（计划尾本身出界、或前面被上一段占满）再退回收口，
        # 还不行由 `_assert_within_source` 如实判死。
        if (
            segment["audio"] in ("narration", "ducked")
            and length > planned_end - planned_start
            and limit > 0
            and planned_end <= limit + _SOURCE_FIT_TOL_S
            and planned_end - length >= floor
        ):
            start = planned_end - length
        # 尾部收口：实测比剩余素材长时，整段往前挪到贴着集尾——这段的文案与长度都不动，
        # 换的只是压在它下面的画面。挪不动（再往前就和上一段重叠=画面重播）就照原样
        # 交给 `_assert_within_source` 判死，不截音也不截画面。
        # 为什么"段尾正好等于源末尾"是安全的：真机实测（bundled ffmpeg 8.1.1，源
        # `1.mp4` 现量 192.200s，真 TTS 干音 6.350s，命令由 `cut_segment_args` 生成）
        # 窗口 185.85→192.20 出片视频 6.367s / 音频 6.371s，与同一干音在素材中段
        # 20.00→26.35 的产物逐毫秒一致；而起点即 EOF 的越界窗口退码仍 0、262 字节无流。
        # 收口损失的只有"这一段配哪几秒画面"，没有一帧声音被丢掉。
        elif 0 < limit < start + length and limit - length >= floor:
            start = limit - length
        end = start + length
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        if index == 0 and _intro_teaser:
            continue  # 闪前预告不推进游标：正文从自己的计划起点起算（见上方判据注释）
        cursor[episode_id] = end
    return timeline


