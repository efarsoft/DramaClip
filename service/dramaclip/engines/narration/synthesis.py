"""TTS 配音执行族：契约校验 + 内容寻址缓存 + 引擎池 + hook 槽位对齐。

自 narration/pipeline.py 拆出（拆分专项 B）：规划/吸附/回填布局留在 pipeline，
本模块承载「文案 → 音频」的执行侧——引擎解析纪律（显式不回退）、两层缓存、
hook 槽位策略机都在这里。测试对 create_tts 的打桩统一打本模块。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from dramaclip.engines.narration import modes
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.tts import base as tts_base
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.infra.ffmpeg import runner as ffmpeg_runner

logger = logging.getLogger(__name__)


def _usable(path: Path) -> bool:
    """非空文件才算数：0 字节占位残留（历史脏产物）不是缓存命中。"""
    return path.is_file() and path.stat().st_size > 0


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
    produced = staging
    try:
        # 以引擎返回的路径为准：云端引擎按 out_path 的扩展名决定落盘格式，
        # 要 .mp3 它就在旁边写一个 .wav 并返回那条——只认 staging 会让每段
        # 配音都在缓存/落位那一步扑空（出片必败）。
        produced = engine.synthesize(text, voice, staging)
        _store_in_cache(produced, cache_dir, text, engine_name, voice, speed)
        os.replace(produced, final_path)
    finally:
        staging.unlink(missing_ok=True)
        if produced != staging:
            produced.unlink(missing_ok=True)  # 成功时已被搬走，这里只收失败残留


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
        model: str = "",
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
        self._model = model
        self._instances: dict[str, tts_base.TtsEngine] = {}
        if self._explicit:
            # 显式引擎构造失败必须当场炸（未知引擎名 = 配置错误，不许当 auto 兜走）
            self._instances[self._requested] = create_tts(
                self._requested, models_dir, api_key=api_key, model=model
            )

    @property
    def label(self) -> str:
        return self._requested

    def voice_for(self, settings: dict[str, str]) -> str:
        """音色按引擎独立成键；兼容升级前仅存全局 tts.voice 的旧库。"""
        return settings.get(f"tts.voice.{self._setting}") or settings.get("tts.voice") or ""

    def accepts_voice(self, voice: str) -> bool:
        """段级音色对请求引擎是否有意义；克隆系引擎要求真实存在的音频文件。

        双人对谈/内心独白模式在槽位里硬编码的是 Edge 音色名——引擎切到克隆系
        （indextts2，音色=参考音频文件）时段级名字不再是文件，必须回退引擎默认
        音色，否则克隆引擎拿 Edge 名当路径直接报错（真机：mono-1 合成失败）。
        edge/kokoro 的音色名体系维持现状（非空即有效）。
        """
        if self._requested != "indextts2":
            return True
        return bool(voice) and Path(voice).is_file()

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
                    engine = create_tts(
                        name, self._models_dir, api_key=self._api_key, model=self._model
                    )
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
