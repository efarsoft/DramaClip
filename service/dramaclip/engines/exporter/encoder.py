"""导出编码器：滤镜链编排与两阶段执行（原案 7.1）。

**行数豁免登记（2026-10-16，唯一超 800 门禁的豁免件）**：本文件是单一职责
（导出编码）的内聚单元，符号间经实测证据互相引用（常量→函数→用例三方
钉死），机械拆模块只是行数搬家。巨型实验记录注释已按「压缩结论」标准
清理（2026-10-16），完整量法链见 git 历史。豁免条件：未来加入第二职责
（如非线性时间线）时按职责切。
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import random
import subprocess  # noqa: F401, S404 - 测试经 encoder.subprocess 打桩 run；film_assembly 实际使用
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.dedup import jitter
from dramaclip.engines.dedup import params as dedup_params
from dramaclip.engines.exporter import ai_label, aigc_metadata, drama_name_layer, loudness

# 测试桩兼容：subprocess 模块对象共享，patch encoder.subprocess.run 对 film_assembly 同效
# 拆出模块的 re-export（cut_segment_args/_export_plan_once 内部调用 + 外部引用面）
from dramaclip.engines.exporter.bgm_bed import (
    _mix_bgm_bed as _mix_bgm_bed,
)

# 成片装配层（拆分专项）：concat/签名/审计/段偏移从本模块 re-export
# ——外部调用方与测试桩按旧名从 encoder 取的契约不变。
from dramaclip.engines.exporter.film_assembly import (  # noqa: F401
    _COLOR_ARGS,
    _SEGMENT_SAMPLE_RATE,
    FilmIntegrityError,
    _audio_signature,
    _audit_film_duration,
    _concat,
    _concat_list_line,
    _concat_manifest,
    _run_ffmpeg_with_heartbeat,
    _segment_offsets,
    _SegmentArtifact,
    _staged_path,
    _video_signature,
)
from dramaclip.engines.exporter.film_assembly import (
    _FALLBACK_CODEC as _FALLBACK_CODEC,
)
from dramaclip.engines.exporter.film_assembly import (
    AUDIT_DURATION_ABS_TOLERANCE_S as AUDIT_DURATION_ABS_TOLERANCE_S,
)
from dramaclip.engines.exporter.film_assembly import (
    AUDIT_DURATION_REL_TOLERANCE as AUDIT_DURATION_REL_TOLERANCE,
)
from dramaclip.engines.exporter.hw_encoders import (
    _video_codec_params as _video_codec_params,
)
from dramaclip.engines.exporter.hw_encoders import (
    nvenc_available as nvenc_available,
)
from dramaclip.engines.exporter.hw_encoders import (
    pick_hw_encoder as pick_hw_encoder,
)
from dramaclip.engines.exporter.signatures import (
    _SIG_VERSION as _SIG_VERSION,
)
from dramaclip.engines.exporter.signatures import (
    _file_identity as _file_identity,
)
from dramaclip.engines.exporter.signatures import (
    _prune_stale_segments as _prune_stale_segments,
)
from dramaclip.engines.exporter.signatures import (
    _read_sig as _read_sig,
)
from dramaclip.engines.exporter.signatures import (
    _reusable_subtitles as _reusable_subtitles,
)
from dramaclip.engines.exporter.signatures import (
    _sha256_file as _sha256_file,
)
from dramaclip.engines.exporter.signatures import (
    _sig_path_for as _sig_path_for,
)
from dramaclip.engines.exporter.signatures import (
    _write_sig_atomic as _write_sig_atomic,
)
from dramaclip.engines.exporter.signatures import (
    _zones_fingerprint as _zones_fingerprint,
)
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle import caption_font
from dramaclip.infra import compute, config
from dramaclip.infra.ffmpeg import probe as ffprobe_mod  # noqa: F401 - 测试桩经 encoder.ffprobe_mod.probe 打桩
from dramaclip.infra.ffmpeg import runner

# 测试桩兼容：模块对象共享，patch encoder.ffprobe_mod.probe 对 film_assembly 同效
from dramaclip.infra.ffmpeg.probe import probe

_LOGGER = logging.getLogger(__name__)

# 画幅数值不在这里定义（docs/04 §5.2）：源是 infra.config，settings 默认值读的是同一个常量。
_DEFAULT_OUT_SIZE = (config.EXPORT_WIDTH, config.EXPORT_HEIGHT)

# 段级真峰天花板（dBFS）：每段交付音频过这道限幅，混音与原声直通两分支都算。
# 演进 -3.0 → -9.0（2026-09-12）：_audio_format_filter 强制 stereo 改变 AAC 编码
# 模式后采样间过冲变大，-3.0 不再成立；-9.0 实测各分支段真峰稳在 0 dBTP 之下。
# 边界：进仓已削平的源限得住电平但压不回过冲（削得越深漏得越多），出口保证仍由
# Phase C 真峰门限+有界重试负责（loudness.py）。对照实验记录见本文件的 git 历史。
_SEGMENT_PEAK_CEILING_DBFS = -9.0

# 段级音频格式逐字统一（48k/stereo，挂在音频链头一级）：amix 会把 mono 旁白与
# stereo 原声协商成 mono 下混，布局换点还会让 ebur128 出两块 Summary 且响度读数
# 不复现（实测整片漂 ~1.2 LU）。aformat 挂头+限幅器收尾是三方案实测最优（挂尾
# 段真峰高 0.4 dB 破 0）；音量常量被真机门禁按名字读，只在此定义一次。
_SEGMENT_CHANNEL_LAYOUT = "stereo"

# BGM 床（C 项接线 → 批3 听感治理升级）：床目标响度、回退音量与尾淡出。
# 床目标 −28 LUFS 的锚：干音契约 −13 LUFS（level_fix 参考带）再低 15 LU——床是
# 连续情绪层不抢人声；固定 0.15 时代曲目 master 实测 −9~−14 LUFS、线性增益
# −16.5 dB 落床 −25~−30 LUFS，取其中位为锚（改这两个数要重听，别挑）。
# 量不到曲目响度时回退 _BGM_BED_VOLUME 固定增益（增强项不挡片）。
_BGM_BED_VOLUME = "0.15"
_BGM_BED_TARGET_LUFS = -28.0
_BGM_TAIL_FADE_S = 1.2
# 循环接长：多副本 acrossfade 替代 stream_loop 硬循环——非无缝曲目在循环点的
# 咔哒消除；曲目过短或副本数超帽（超长片×超短曲）回退硬循环。
_BGM_LOOP_XFADE_S = 0.5
_BGM_LOOP_MAX_COPIES = 8
# 人声躲床：成片混音做 sidechain 触发压床（旁白/原声对白开口床自动退让），
# 与 _SIDECHAIN_COMPRESS 同一模式；attack/release 放慢避免逐音节泵动。
_BGM_DUCK_COMPRESS = "sidechaincompress=threshold=0.05:ratio=4:attack=150:release=400"

# 压底段的原声音量（旁白段 10% / 全片衬底段 8%）。真机门禁按名字读这两个数——它要用同一个
# 值算出该段的预测响度再去量实测，所以音量只在这里定义一次。写成字符串是因为它直接拼进滤镜。
_NARRATION_BED_VOLUME = "0.1"
_DUCKED_BED_VOLUME = "0.08"
# 旁白开口时再压原声：threshold 0.05 ≈ -26 dBFS，安静 TTS 不触发（静音旁白的避让深度
# 仍等于 volume= 声明值，见 test_duck_depth_is_acoustically_real）。限幅器仍收尾。
_SIDECHAIN_COMPRESS = "sidechaincompress=threshold=0.05:ratio=6:attack=20:release=250"


def _audio_format_filter() -> str:
    """段级音频格式滤镜串——两条分支（含 amix 的两路输入）共用的**唯一**一处构造。
    """
    return (
        f"aformat=sample_rates={_SEGMENT_SAMPLE_RATE}"
        f":channel_layouts={_SEGMENT_CHANNEL_LAYOUT}"
    )


def _peak_ceiling_filter() -> str:
    """段级天花板滤镜串——两条分支共用的**唯一**一处构造。
    """
    return (
        f"alimiter=limit={10 ** (_SEGMENT_PEAK_CEILING_DBFS / 20):.4f}"
        f":level=disabled:latency=true"
    )


def _video_fade_s(transition: str) -> float:
    """转场词表只有 cut/fade/black；flash 已在编排层停赋（transitions.assign_transitions），
    未知值一律按 cut 处理，不是静默吞掉——将来加转场必须先来这里登记时长。"""
    if transition == "fade":
        return 0.18
    if transition == "black":
        return 0.30
    return 0.0


def _audio_fade_s(transition: str) -> float:
    if transition == "fade":
        return 0.18
    if transition == "black":
        return 0.30
    return 0.10


def _clamp_fades(duration: float, fade_in: float, fade_out: float) -> tuple[float, float]:
    duration = max(duration, 0.05)
    total = fade_in + fade_out
    if total <= 0 or total <= duration - 0.02:
        return max(fade_in, 0.0), max(fade_out, 0.0)
    scale = max(duration - 0.02, 0.0) / total
    return fade_in * scale, fade_out * scale


def _xfade_filters(kind: str, duration: float, fade_in: float, fade_out: float) -> list[str]:
    """kind: fade（画面）或 afade（声音）。两端时长钳在段长以内。

    刻意**不是** ffmpeg 的 `xfade` 溶解滤镜。两阶段架构（Phase A 逐段独立编码、
    Phase B concat 流复制）下相邻段从不同时存在于一个进程里，做真溶解就得把整条
    时间轴塞进一个 filter_complex：重叠吃时长、字幕/混音/限幅全部要按新时间轴重排，
    逐段并行与台词保护区切点也一并报废。成对淡（出段淡黑 + 入段淡入）观感上是
    一次短促的「换气」，音频另有 afade 交叉，硬切已除；溶解的叠影收益不值这个重构。
    """
    fade_in, fade_out = _clamp_fades(duration, fade_in, fade_out)
    parts: list[str] = []
    if fade_in > 0.001:
        parts.append(f"{kind}=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0.001:
        start = max(duration - fade_out, 0.0)
        parts.append(f"{kind}=t=out:st={start:.3f}:d={fade_out:.3f}")
    return parts


def seam_fades(
    transition: str,
    *,
    is_first: bool,
    is_last: bool,
    next_transition: str | None,
    audio_change_in: bool,
    audio_change_out: bool,
) -> tuple[float, float, float, float]:
    """返回 (video_in, video_out, afade_in, afade_out)。片头钩子不淡入，片尾 0.30s 收黑。"""
    video_in = 0.0 if is_first else _video_fade_s(transition)
    video_out = 0.30 if is_last else _video_fade_s(next_transition or "cut")
    audio_in = 0.0 if is_first else _audio_fade_s(transition)
    audio_out = 0.30 if is_last else _audio_fade_s(next_transition or "cut")
    if audio_change_in:
        audio_in = max(audio_in, 0.15)
    if audio_change_out:
        audio_out = max(audio_out, 0.15)
    return video_in, video_out, audio_in, audio_out


class EpisodeSourceMissing(Exception):
    """时间轴引用的源集文件缺失。"""


def resolve_canvas(episode_paths: dict[str, str], cap: tuple[int, int]) -> tuple[int, int]:
    """成片画布跟随首个源集的画幅（业主裁决：16:9 进 → 16:9 出，不裁不拉）。

    等比缩放使长边贴 cap 长边（cap=1080×1920 时：16:9 源 → 1920×1080，
    竖源 → 1080×1920 与现状一致），宽高取偶。混画幅批次以首集为准，异画幅
    源等比缩进画布、两侧补黑——内容完整优先于满屏。probe 不可得时回退 cap。
    """
    try:
        first = probe(Path(next(iter(episode_paths.values()))))
        src_w, src_h = first.width, first.height
    except Exception:  # noqa: BLE001 - 探测失败回默认画布，不让导出开天窗
        return cap
    if src_w <= 0 or src_h <= 0:
        return cap
    long_side = min(max(cap[0], cap[1]), 1920)
    factor = long_side / max(src_w, src_h)
    width = max(2, round(src_w * factor / 2) * 2)
    height = max(2, round(src_h * factor / 2) * 2)
    return (width, height)


# 常见帧率白名单：probe 报出奇异值（坏容器/可变帧率均值）时回退 30 而不是
# 把怪数钉进全批段的签名——段签名一致是 -c copy 拼接的前置。
_KNOWN_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 60.0)
_FALLBACK_FPS = 30.0


def resolve_output_fps(episode_paths: dict[str, str]) -> float:
    """成片帧率跟随首个源集（与 resolve_canvas 同款纪律：批内一致、以首集为准）。

    此前恒 -r 30：25/24fps 源靠补帧/丢帧凑 30，摇移镜头顿挫。混帧率批次以
    首集为准（与画幅同一裁决面），探测失败/奇异值回退 30=旧行为。
    """
    try:
        first = probe(Path(next(iter(episode_paths.values()))))
        fps = first.fps
    except Exception:  # noqa: BLE001 - 探测失败回默认帧率，不让导出开天窗
        return _FALLBACK_FPS
    if fps <= 0:
        return _FALLBACK_FPS
    return min(_KNOWN_FPS, key=lambda known: abs(known - fps))


# 擦除时间窗的收口常量：短于 50ms 的一闪不值得挂 delogo（它在邻帧间做插值，
# 闪一帧只会让补丁边缘抖）；间隙 ≤200ms 的两段并成一段——同一句台词的 OCR 条
# 在采样边界上常被劈成两条，enable 碎片化不改变画面却增加解析成本。
_ERASE_SPAN_MIN_S = 0.05
_ERASE_SPAN_MERGE_S = 0.20


def _erase_enable_suffix(
    windows: list[tuple[float, float]] | None, start: float, end: float
) -> tuple[str, bool]:
    """台词驻留窗（源绝对秒）→ delogo 的 `:enable=` 片段 + 这段到底擦不擦。

    源字幕是间歇出现的，而 delogo 默认整段挂着——没字的画面上糊一块动过的补丁，
    就是业主反馈的「大幅遮盖画面」（2026-10-09 裁决③：擦除按台词时间窗开合）。

    时间基（易错）：滤镜链里 delogo 排在 `setpts=PTS/speed` **之前**，它看到的 t
    是「裁剪后、变速前」= 源时间 − 段起点，dedup 微变速不参与折算。

    返回 `(后缀, 有交集)`：
    - 窗缺失/空 → `("", True)`：不收窄，整段擦（OCR 未跑时与现状逐字节一致，
      宁多擦不漏擦——漏擦等于源台词留在屏上，是可见缺陷）；
    - 夹到段内后无一段有效 → `("", False)`：这段画面里一帧台词都没有，矩形整框跳过；
    - 单扇窗本就盖住整段 → `("", True)`：不加无意义的 enable 文本。
    """
    if not windows:
        return "", True
    clip = max(end - start, 0.0)
    clipped = sorted(
        (max(w_start - start, 0.0), min(w_end - start, clip))
        for w_start, w_end in windows
        if w_end - w_start > 0.0
    )
    spans: list[tuple[float, float]] = []
    for lo, hi in clipped:
        if hi - lo <= _ERASE_SPAN_MIN_S:
            continue
        if spans and lo <= spans[-1][1] + _ERASE_SPAN_MERGE_S:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))
    if not spans:
        return "", False
    if len(spans) == 1 and spans[0][0] <= 0.001 and spans[0][1] >= clip - 0.001:
        return "", True
    terms = "+".join(f"between(t,{lo:.3f},{hi:.3f})" for lo, hi in spans)
    return f":enable='{terms}'", True


def cut_segment_args(
    source: str,
    out_path: str,
    *,
    start: float,
    end: float,
    audio: str,
    tts_audio: str | None,
    rng: random.Random,
    transition: str = "cut",
    ass_path: str | None = None,
    out_size: tuple[int, int] = _DEFAULT_OUT_SIZE,
    video_codec: str = "libx264",
    fade_in_s: float | None = None,
    fade_out_s: float | None = None,
    afade_in_s: float | None = None,
    afade_out_s: float | None = None,
    erase_rects: list[tuple[float, float]] | None = None,
    erase_windows: list[tuple[float, float]] | None = None,
    ai_label_vf: str | None = None,
    drama_name_vf: str | None = None,
    fps: float = _FALLBACK_FPS,
) -> list[str]:
    """构建单段切割命令（Phase A）。

    画布语义（业主裁决「16:9 就是 16:9，不要拉伸到 9:16」）：等比缩放进画布
    （force_original_aspect_ratio=decrease），不足处补黑——内容完整、比例忠实，
    不再覆盖裁切也不再要人脸裁窗（那是把横屏源塞竖屏画布的旧形状）。

    `erase_rects`：源硬字幕**逐行**归一化 (top, bottom)——delogo 涂抹擦除
    （2026-10-06 业主裁决「直接覆盖原始字幕」推翻 90004e4；2026-10-07 追加
    「只擦检测到的文字行」——矩形贴行不贴带，行间空隙与带边缘画面保留）。
    每个矩形按 dedup 微缩放后的内容区折算成画布坐标（pad 居中的偏移计入），
    且必须紧贴 pad 之后：缩放与居中 pad 定了内容在画布里的实际位置，后面
    eq/fade 不改几何。横屏源被补黑时行比例相对源画面高、落在画布中部——与
    ASS 带内压位共用同一假设（核心素材是 9:16 原生短剧，画布与源同比例）。

    `erase_windows`：该集台词在屏上的驻留窗（源绝对秒，OCR 通道产物）。给了它
    就把 delogo 用 `enable` 收成「只在有字的那几秒挂」——整段涂抹会在无字画面上
    留一块动过的补丁（2026-10-09 业主裁决③）。逐行框的时间窗没有单独落库
    （OCR 条按帧拼接整行文本，`OcrSegment` 只有 start/end/text/conf），所以窗是
    **整带级**的：多行台词时，某行不在屏上的那几秒照样被同扇窗盖住擦——比整段
    挂着的旧行为窄，比逐行精确粗，取中间值是有意的（要逐行窗须先改生产者）。
    """
    out_w, out_h = out_size
    dedup = dedup_params.generate(rng)
    speed = dedup.speed_factor
    scaled_w = int(out_w * dedup.scale_factor) // 2 * 2
    scaled_h = int(out_h * dedup.scale_factor) // 2 * 2
    out_dur = max((end - start) / speed, 0.05)
    vin = _video_fade_s(transition) if fade_in_s is None else fade_in_s
    vout = _video_fade_s(transition) if fade_out_s is None else fade_out_s
    ain = _audio_fade_s(transition) if afade_in_s is None else afade_in_s
    aout = _audio_fade_s(transition) if afade_out_s is None else afade_out_s
    # 音频收尾链：成对 afade + 限幅器（限幅器必须是进 AAC 前的最后一级，见混音分支注释）
    audio_tail = ",".join([*_xfade_filters("afade", out_dur, ain, aout), _peak_ceiling_filter()])

    enable_suffix, has_subtitle = _erase_enable_suffix(erase_windows, start, end)
    band_filter: list[str] = []
    for rect_top, rect_bottom in (erase_rects or []) if has_subtitle else []:
        top = min(max(float(rect_top), 0.0), 1.0)
        bottom = min(max(float(rect_bottom), 0.0), 1.0)
        if bottom - top <= 0.01:
            continue
        if bottom - top > 0.16:
            # 超高"行框"（>16% 画布高 ≈ 台词行最高 9% 的近两倍）是满幅文字
            # 背景的误检（片头字幕墙/竖排题字聚合），不是台词行——擦它等于
            # 糊大半个屏幕（2026-10-09 真机 16:9 源反馈），整框跳过。
            continue
        content_x = max(1, round((out_w - scaled_w) / 2))
        content_y = max(1, round((out_h - scaled_h) / 2))
        delogo_y = min(max(1, content_y + round(top * scaled_h)), out_h - 2)
        delogo_h = min(max(2, round((bottom - top) * scaled_h)), out_h - delogo_y - 1)
        delogo_w = max(2, scaled_w - 2 * content_x)
        band_filter.append(
            f"delogo=x={content_x}:y={delogo_y}:w={delogo_w}:h={delogo_h}{enable_suffix}"
        )

    filters = [
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=decrease",
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black",
        # delogo 紧贴 pad：矩形在「缩放后内容 + 居中 pad」的画布坐标系里折算，
        # 计入微缩放的居中偏移（见 band_filter 注释）
        *band_filter,
        f"eq=contrast={dedup.contrast}:brightness={dedup.brightness}",
        # 像素比必须在这里钉平：`scale` 保留输入 SAR，非方形源的段会带着它编进成片
        # ——存储尺寸对、显示比例错，播放器横向拉伸，烧进去的 ASS（PlayRes 出画尺寸）
        # 跟着变形。且它逐段漂移（末级 scale 目标跟着微缩放取整变），Phase B 又是
        # `-c copy`，一条片子里换几何完全静默。实测与量法见 test_pixel_geometry。
        "setsar=1",
        f"setpts=PTS/{speed}",
        *_xfade_filters("fade", out_dur, vin, vout),
    ]
    if ass_path:
        filters.append(
            f"ass={_escape_filter_path(ass_path)}"
            f":{caption_font.fontsdir_option(caption_font.caption_font())}"
        )
    if drama_name_vf:
        # 剧名层在 AI 标注之前挂（左上/右上各占一角，顺序稳定供单测钉形状）。
        filters.append(drama_name_vf)
    if ai_label_vf:
        # AI 标注在每段烧一次：Phase B 流复制拼接，硬编成果不再整片重编。
        # 失败即该段失败，交给现有段级回退/整片统一重跑——不允许无标注成片。
        filters.append(ai_label_vf)

    args = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        source,
    ]
    if audio in ("narration", "ducked") and tts_audio:
        # 旁白/压底段：TTS 主音 + 原声压低（旁白段原声 10%，全片衬底 8%）
        # normalize=0 必须显式给：ffmpeg 的 amix 默认把每路除以输入数（此处各砍 6dB），
        # 那样上面的 bg_volume 声明值与实际听感差一倍，响度无人负责。最终响度由 Phase C 统一收口。
        #
        # 求和之后必须挂限幅器：normalize=0 也把 amix 那 6 dB 的意外余量一起去掉了，
        # 旁白 + 原声可以直接冲过 0 dBFS。滤镜选型与 `level=disabled` / `latency=true`
        # 为什么不可省，见 `_peak_ceiling_filter`；实测数字见 test_mix。
        #
        # 这两个音量真机门禁按名字读（scripts/verify_modes.py 逐段核对滤镜里真的写了
        # volume=，并按它算出"这一段应当有多响"去量实测）：写成字面量的话，改了这里只有
        # 成片听得出差别，而那是业主立案④「解说与原声同音量叠放」的形状。
        bg_volume = _NARRATION_BED_VOLUME if audio == "narration" else _DUCKED_BED_VOLUME
        args += ["-i", tts_audio]
        args += [
            "-filter_complex",
            f"[0:v]{','.join(filters)}[v];"
            # 两路输入都先过 `_audio_format_filter()`：amix 的格式协商在"一路 mono 一路
            # stereo"时会选 mono，把原声**下混**掉（实测数字与该选 stereo 的理由见常量注释）。
            # 两路都钉成 stereo 之后 amix 无需协商，求和保持 stereo。
            f"[0:a]{_audio_format_filter()},volume={bg_volume},atempo={speed}[bg];"
            f"[1:a]{_audio_format_filter()},atempo={speed},asplit=2[tts][sc];"
            f"[bg][sc]{_SIDECHAIN_COMPRESS}[bed];"
            f"[bed][tts]amix=inputs=2:duration=first:normalize=0,"
            f"{audio_tail}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        # 原声直通段：以前这里只有 atempo，源素材自己的热度原样进成片（真机实测
        # `intro_narration_c3eb30` 整片 +3.38 dBTP / `ultra_short_hook_2c9b87` +1.88 dBTP，
        # 九部里就这两部带 original 段，也就只有这两部超门限）。
        #
        # 限幅器挂在 atempo **之后**，即"进 AAC 前的最后一级"：alimiter 的 `limit` 只约束
        # 它**自己的输出**，后面再接重采样会重新长出采样间过冲，天花板就被下游悄悄作废。
        # 诚实记账：实测这三档素材上"先限后变"反而低 0.06–0.65 dB（平顶源 -1.52 vs -0.87），
        # 那是素材巧合、不是可依赖的保证；而"限幅器收尾"是有语义的——atempo 在前与
        # **只挂限幅器**逐档同值（-0.87 / +0.37 / -2.31 vs -0.87 / +0.37 / -2.32），
        # 说明前置的微变速不扰动天花板。混音分支同理（amix → 限幅器 → 编码器）。
        # 顺序被 test_mix 与 test_encoder 双向钉住，翻转即红。
        args += [
            "-vf",
            ",".join(filters),
            # 格式统一挂头、限幅器收尾：`_audio_format_filter()` 放在 atempo 之前，
            # 保证 alimiter 仍是"进 AAC 前的最后一级"（挂尾实测把段真峰从 -0.3 抬到
            # +0.1 dBTP，见常量注释）。这一级也让 **mono 源集**的直通段落到 stereo，
            # 布局统一不再取决于素材。
            "-af",
            f"{_audio_format_filter()},atempo={speed},{audio_tail}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
        ]
    args += [
        "-c:v",
        video_codec,
        *_video_codec_params(video_codec),
        *_COLOR_ARGS,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        # 帧率跟源（resolve_output_fps 批内一致）：恒 30 对 25/24fps 源靠补帧/
        # 丢帧凑数，摇移镜头顿挫；混合批次以首集为准，探测失败回退 30=旧行为
        "-r",
        f"{fps:g}",
        # 像素格式钉 8bit 4:2:0：10-bit 源会编出 High 10 profile，部分平台/
        # 播放器不收；显式落 yuv420p 也让全批段签名在这一维恒一致
        "-pix_fmt",
        "yuv420p",
        # 音频采样率统一 48k：TTS（24k）与源素材（48k）混流后 concat 流复制
        # 以首段采样率解读全部包，采样率不一致会把时长/语速翻倍或减半。
        # 与 `_audio_format_filter()` 里的 `sample_rates` 同源读一个常量：滤镜侧钉 48k
        # 是为了让段与段布局/采样率逐字相同，输出侧这个 `-ar` 是同一件事的封装层保险。
        "-ar",
        str(_SEGMENT_SAMPLE_RATE),
        "-map_metadata",
        "-1",
        # AAC priming 会写出负起点/编辑列表，concat demuxer 流复制时音频时长
        # 被逐段双倍累计（真机实证：195s 计划渲染出 416s 成片）——归零时间戳
        "-avoid_negative_ts",
        "make_zero",
        out_path,
    ]
    return args


def _escape_filter_path(path: str) -> str:
    """ass 滤镜路径处理：优先相对路径（规避盘符冒号的转义地狱），绝对路径双转义保底。"""

    normalized = path.replace("\\", "/")
    if ":" not in normalized:
        return normalized.replace("'", r"\'")
    try:
        relative = os.path.relpath(normalized).replace("\\", "/")
    except ValueError:
        # 跨盘符（数据目录与工作目录不同盘）根本没有相对路径可算：必须落到下面
        # 转义盘符那一支，交出去的 `C:/…` 会被 ffmpeg 在冒号处切开当选项值。
        relative = ""
    if relative and not relative.startswith(".."):
        return relative.replace("'", r"\'")
    return normalized.replace(":", r"\\:").replace("'", r"\'")


# ---- A4-1 硬编探测：平台候选序 + 同形状质量参数真试编 + 会话级缓存 ----

# 硬编候选序按平台：Windows 三厂商 NVENC→AMF→QSV，Linux 只有 NVENC/QSV（AMF 的
# Linux 支持面未实测，不进候选）。编码器「列表里有」≠「真编能过」（驱动残缺/GPU
# 会话数满），所以每个候选都要做 0.1s 黑帧**真试编**——且必须带与正式合成
# **同形状**的质量参数（`_video_codec_params`），只 `-f null` 探不出「参数不识别」
# 这类实编挂。
_HW_CANDIDATES_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    # win32 三厂商：N 卡第一次命中；AMD 主机 nvenc 黑帧失败后第二次命中 AMF；
    # Intel 核显最后兜底。全失败才 libx264。
    "win32": ("h264_nvenc", "h264_amf", "h264_qsv"),
    "darwin": ("h264_videotoolbox",),
}
# 输出色彩统一打 BT.709 标签：短剧源（网络片源）几乎全为 BT.709，无标签流的
# 播放器/平台各自猜矩阵（BT.601 vs 709）是跨平台偏色投诉的来源。重编码段与
# 重编码 concat 都注入；流复制分支保留源标签不动。

_HW_CANDIDATES_LINUX: tuple[str, ...] = ("h264_nvenc", "h264_qsv")

def _run_cut(
    args: list[str],
    cancel: threading.Event | None = None,
    *,
    timeout_s: float = 600,
    total_duration_s: float | None = None,
    on_progress: runner.ProgressCallback | None = None,
) -> None:
    # total_duration_s/on_progress 成对给才生效（runner.run 据此追加 -progress pipe:1）；
    # 默认 None 时与旧行为逐字节一致。测试桩是 lambda *_a, **_k 形状，吸收新 kwargs。
    runner.run(
        args,
        timeout_s=timeout_s,
        cancel=cancel,
        total_duration_s=total_duration_s,
        on_progress=on_progress,
    )


# ---- A4-2 段级运行时回退：硬编某段失败→清半成品→libx264 重跑一次 ----
#
# 段级回退只解决"这一段能编完"，留下一道尾巴：同一部片子里 nvenc 段与 libx264 段
# 混排，两种编码器的画质特征不同，段间会跳变。所以回退不是终点——本轮只要出现过
# 一次回退，export_plan 就整片按 libx264 统一重跑一次（_UniformCodecRetry）。重跑
# 白嫖 B4 断点续跑的签名机制：已回退段的 sig 记的就是实际成功 codec=libx264，与
# 重跑请求一致 → 命中复用零成本跳过；只有硬编成功的段重编。宁可多付一次整片重编，
# 不交付段间画质跳变的片子。

_HW_ENCODERS = frozenset(
    {"h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"}
)
# 输入侧错误（文件缺失/损坏、参数非法）换编码器重跑也没用，直接抛；
# cancelled 不是编码失败；其余（含分类不出的 unknown，如超时被杀 stderr 空）按可回退。
_NO_FALLBACK_KINDS = frozenset({"io", "invalid"})


class _UniformCodecRetry(Exception):
    """内部信号：本轮出现过段级硬编回退，export_plan 须整片按 libx264 重跑一次。"""


def _args_with_codec(args: list[str], video_codec: str) -> list[str]:
    """把已构建段命令的 `-c:v <codec> <质量参数>` 区间整体换成目标编码器的，其余不动。"""
    start = args.index("-c:v")
    end = args.index("-c:a")
    return [*args[: start + 1], video_codec, *_video_codec_params(video_codec), *args[end:]]


def _fallback_eligible(exc: runner.FfmpegError, args: list[str]) -> bool:
    if exc.cancelled or exc.kind in _NO_FALLBACK_KINDS:
        return False
    if "-c:v" not in args:
        return False
    return args[args.index("-c:v") + 1] in _HW_ENCODERS

# ---- B4 段级断点续跑：sidecar 签名（seg_NNN.sig）决定哪些段可以不重编 ----
# 选型 sidecar 签名而非按 export_id 播种 rng：播种会把「每片段独立随机」的消重
# 前提变成可复现常量，且跳过判定仍需「产物在、输入没变」的签名，(a) 替代不了 (b)。
# 复用判据=声明输入一致（源身份/集号/起止/角色/转场/淡入淡出/尺寸/字幕形状与文本
# hash/TTS 音频 sha/保护区哈希/请求 codec==实际成功 codec）；不含 jitter 后实际切点
# （那是每次渲染要不同的量）。sig 与段同生命周期、tmp+replace 原子写；陈旧尾段清掉。
@dataclass
class _SegmentJob:
    """一段的编码任务 + 写 sidecar 签名所需的全部上下文。

    reuse=True 的段不进线程池：产物与 sig 都已在盘上且输入签名一致。
    """

    index: int
    args: list[str]
    seg_path: Path
    inputs: dict[str, object]
    safe_start: float
    safe_end: float
    progress_duration: float
    burner_duration: float
    subtitle_source: str
    ass_sha256: str | None
    reuse: bool


def _compute_requested(value: str) -> str:
    """导出设置 / 实际 codec → 算力请求词汇（auto / cpu / cuda）。"""
    normalized = (value or "").strip().lower()
    if normalized in ("", "auto"):
        return "auto"
    if normalized in ("cpu", _FALLBACK_CODEC):
        return "cpu"
    return "cuda"


def export_plan(
    plan: PlanData,
    episode_paths: dict[str, str],
    out_path: Path,
    work_dir: Path,
    *,
    tts_audio_by_segment: dict[int, str] | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    subtitle_burner: Callable[[int, str, float], str] | None = None,
    original_subtitle_provider: Callable[[int, float, float], str | None] | None = None,
    parallel: int = 2,
    dialogue_zones: dict[str, list[SpeechZone]] | None = None,
    out_size: tuple[int, int] = _DEFAULT_OUT_SIZE,
    loudness_target: loudness.LoudnessTarget | None = None,
    video_codec: str = "libx264",
    subtitle_bands: dict[str, tuple[float, float]] | None = None,
    subtitle_erase_rects: dict[str, list[tuple[float, float]]] | None = None,
    subtitle_erase_windows: dict[str, list[tuple[float, float]]] | None = None,
    burn_ai_label: bool = False,
    compute_sink: Callable[[compute.ComputeReport], None] | None = None,
    encoder_requested: str = "",
    segment_offsets_sink: Callable[[Sequence[dict[str, float | int | str]]], None] | None = None,
    bgm_track: Path | None = None,
    aigc_stamp: tuple[str, str] | None = None,
    burn_drama_name: str | None = None,
) -> Path:
    """执行两阶段导出，返回成片路径。

    A4-2 统一收口：请求硬编而中途发生段级回退时，整片换 libx264 再跑一次
    （见 _UniformCodecRetry 注释）——已回退段凭签名复用，只有硬编成功的段重编。

    `burn_ai_label`（settings `export.ai_label`，默认关闭）：标注在每段烧一次
    （见 `ai_label` 模块）；开启时任一段烧制失败即导出失败——用户明示要的标注
    不能静默缺席，也不能靠整片 x264 重编把硬编收益吃掉。

    `compute_sink` 只在整片成功（含统一重跑后成功）时收到一份 `video.encode`
    回执：resolved=首轮选中编码器，actual=最终成片编码器，段级回退必须可见。

    `segment_offsets_sink` 只在整片成功且段长全部实测到时收到 `[(段序号, 成片起点秒)]`，
    顺序＝拼接序；用于给成片侧产出逐句时间轴（见 `_segment_offsets`）。不传即零额外探测。
    """
    state: dict[str, Any] = {"fallback": False, "reason": "", "fallback_count": 0}
    try:
        path = _export_plan_once(
            plan, episode_paths, out_path, work_dir,
            tts_audio_by_segment=tts_audio_by_segment,
            cancel=cancel,
            on_progress=on_progress,
            subtitle_burner=subtitle_burner,
            original_subtitle_provider=original_subtitle_provider,
            parallel=parallel,
            dialogue_zones=dialogue_zones,
            out_size=out_size,
            loudness_target=loudness_target,
            video_codec=video_codec,
            subtitle_bands=subtitle_bands,
            subtitle_erase_rects=subtitle_erase_rects,
            subtitle_erase_windows=subtitle_erase_windows,
            burn_ai_label=burn_ai_label,
            segment_offsets_sink=segment_offsets_sink,
            bgm_track=bgm_track,
            aigc_stamp=aigc_stamp,
            burn_drama_name=burn_drama_name,
            _allow_uniform_retry=True,
            _report_state=state,
        )
        actual = video_codec
    except _UniformCodecRetry:
        count = int(state.get("fallback_count") or 0)
        base_reason = str(state.get("reason") or "段级硬编失败")
        state["fallback"] = True
        state["reason"] = f"{base_reason}（共 {count} 段回退，整片统一 libx264 重跑）"
        _LOGGER.warning(
            "本轮出现段级硬编回退：整片按 %s 统一重跑一次，"
            "消除段间编码器混排的画质跳变（已回退段将凭签名复用）",
            _FALLBACK_CODEC,
        )
        path = _export_plan_once(
            plan, episode_paths, out_path, work_dir,
            tts_audio_by_segment=tts_audio_by_segment,
            cancel=cancel,
            on_progress=on_progress,
            subtitle_burner=subtitle_burner,
            original_subtitle_provider=original_subtitle_provider,
            parallel=parallel,
            dialogue_zones=dialogue_zones,
            out_size=out_size,
            loudness_target=loudness_target,
            video_codec=_FALLBACK_CODEC,
            subtitle_bands=subtitle_bands,
            subtitle_erase_rects=subtitle_erase_rects,
            subtitle_erase_windows=subtitle_erase_windows,
            burn_ai_label=burn_ai_label,
            segment_offsets_sink=segment_offsets_sink,
            bgm_track=bgm_track,
            aigc_stamp=aigc_stamp,
            burn_drama_name=burn_drama_name,
            _allow_uniform_retry=False,
            _report_state=state,
        )
        actual = _FALLBACK_CODEC
    if compute_sink is not None:
        compute_sink(
            compute.ComputeReport(
                component="video.encode",
                requested=_compute_requested(encoder_requested or video_codec),
                resolved=video_codec,
                actual=actual,
                fallback=bool(state["fallback"]),
                reason=str(state["reason"]),
            )
        )
    return path


def _export_plan_once(
    plan: PlanData,
    episode_paths: dict[str, str],
    out_path: Path,
    work_dir: Path,
    *,
    tts_audio_by_segment: dict[int, str] | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    subtitle_burner: Callable[[int, str, float], str] | None = None,
    original_subtitle_provider: Callable[[int, float, float], str | None] | None = None,
    parallel: int = 2,
    dialogue_zones: dict[str, list[SpeechZone]] | None = None,
    out_size: tuple[int, int] = _DEFAULT_OUT_SIZE,
    loudness_target: loudness.LoudnessTarget | None = None,
    video_codec: str = "libx264",
    subtitle_bands: dict[str, tuple[float, float]] | None = None,
    subtitle_erase_rects: dict[str, list[tuple[float, float]]] | None = None,
    subtitle_erase_windows: dict[str, list[tuple[float, float]]] | None = None,
    burn_ai_label: bool = False,
    segment_offsets_sink: Callable[[Sequence[dict[str, float | int | str]]], None] | None = None,
    bgm_track: Path | None = None,
    aigc_stamp: tuple[str, str] | None = None,
    burn_drama_name: str | None = None,
    _allow_uniform_retry: bool = True,
    _report_state: dict[str, Any] | None = None,
) -> Path:
    """单次导出尝试（统一重跑的循环体，见 export_plan）。

    B4 断点续跑：Phase A 每段先看 sidecar 签名（seg_NNN.sig）——声明输入一致、
    产物在盘、请求 codec 等于上次实际成功 codec、字幕按上次窗口重生成后内容 hash
    一致，才跳过重编（接受上次的抖动切点与消重参数）。新鲜渲染（空 work_dir）
    路径与无签名时代逐字节一致，只是每段成功后多写一个 sig。
    """

    segments = plan.timeline
    if not segments:
        raise ValueError("编排时间轴为空")
    work_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random()

    total = len(segments)
    # 画布跟随首个源集画幅（16:9 进→16:9 出，不裁不拉；异画幅补黑），全片统一——
    # Phase B -c copy 拼接要求段段几何一致，逐集各画各的会拼出变换静默。
    out_size = resolve_canvas(episode_paths, out_size)
    output_fps = resolve_output_fps(episode_paths)
    # 字号/边距由**解析后的画布**决定，不能用调用方传的上限猜；字体缺失在这里
    # 硬失败（早于任何段编码），不给「跑了半小时才说标不了」的路径。
    label_spec = ai_label.prepare(work_dir, out_size) if burn_ai_label else None
    drama_spec = (
        drama_name_layer.prepare(work_dir, out_size, burn_drama_name)
        if burn_drama_name
        else None
    )
    _prune_stale_segments(work_dir, total)

    # Phase A：构建每段命令参数（含台词保护区安全切点、字幕、混音）；
    # 命中复用判据的段不建令、不动 rng、不抽帧——直接进 jobs 标记 reuse。
    jobs: list[_SegmentJob] = []
    zones_cache: dict[str, list[SpeechZone]] = {}
    reused_count = 0
    for index, segment in enumerate(segments):
        source = episode_paths.get(segment.episode_id)
        if source is None or not Path(source).is_file():
            raise EpisodeSourceMissing(f"第 {segment.episode_id} 集源文件缺失")
        if segment.episode_id not in zones_cache:
            # 同名 .srt 优先（尊重手工校对过的字幕文件），缺失才回退库内 ASR 区
            srt = jitter.srt_for_source(Path(source))
            zones_cache[segment.episode_id] = (
                jitter.parse_srt(srt)
                if srt is not None
                else list((dialogue_zones or {}).get(segment.episode_id) or [])
            )
        zones = zones_cache[segment.episode_id]
        seg_path = work_dir / f"seg_{index:03d}.mp4"
        tts_audio = (tts_audio_by_segment or {}).get(index)
        nxt = segments[index + 1] if index + 1 < total else None
        prev = segments[index - 1] if index else None
        vin, vout, ain, aout = seam_fades(
            segment.transition,
            is_first=index == 0,
            is_last=nxt is None,
            next_transition=None if nxt is None else nxt.transition,
            audio_change_in=prev is not None and prev.audio != segment.audio,
            audio_change_out=nxt is not None and nxt.audio != segment.audio,
        )
        # 字幕接线形状（声明字段即可判定，与下面建令分支同源）：
        # burner=旁白文案烧录；provider=原声段台词字幕；none=无字幕。
        if subtitle_burner is not None and segment.subtitle_text:
            subtitle_source = "burner"
        elif (
            original_subtitle_provider is not None
            and segment.audio == "original"
            and not segment.subtitle_text
        ):
            subtitle_source = "provider"
        else:
            subtitle_source = "none"
        # 声明输入签名：任何影响产物字节的**可声明**输入都在里面；jitter 后的实际
        # 切点与消重参数刻意不在（每次渲染本就不同，复用=接受上次抽样）。
        inputs: dict[str, object] = {
            "source": _file_identity(source),
            "episode_id": segment.episode_id,
            "start": segment.start,
            "end": segment.end,
            "audio": segment.audio,
            "transition": segment.transition,
            "fades": [vin, vout, ain, aout],
            "out_size": [out_size[0], out_size[1]],
            "subtitle_text_sha256": hashlib.sha256(
                (segment.subtitle_text or "").encode("utf-8")
            ).hexdigest(),
            "subtitle_source": subtitle_source,
            "tts_audio": (
                None
                if tts_audio is None
                else {"path": str(tts_audio), "sha256": _sha256_file(tts_audio)}
            ),
            "zones_sha256": _zones_fingerprint(zones),
        }
        if label_spec is not None:
            # 只在开启时入签名：关闭标注的旧缓存逐字节兼容（键缺席 == 未开启）。
            inputs["ai_label"] = label_spec.fingerprint
        if drama_spec is not None:
            # 只在开启时入签名：关闭的旧缓存逐字节兼容（键缺席 == 未开启）。
            inputs["drama_name"] = drama_spec.fingerprint
        existing = _read_sig(seg_path)
        if (
            existing is not None
            and existing["inputs"] == inputs
            and existing["recorded"].get("actual_codec") == video_codec
            and _reusable_subtitles(
                index,
                segment,
                existing["recorded"],
                subtitle_source,
                subtitle_burner,
                original_subtitle_provider,
            )
        ):
            reused_count += 1
            recorded = existing["recorded"]
            jobs.append(
                _SegmentJob(
                    index=index, args=[], seg_path=seg_path, inputs=inputs,
                    # 复用段接受上次的实际切点：film map（成片↔源对照）对复用段
                    # 也要给实测值，0.0/0.0 会把 avsync 映射带回声明值时代。
                    safe_start=float(recorded.get("safe_start") or segment.start),
                    safe_end=float(recorded.get("safe_end") or segment.end),
                    progress_duration=0.05,
                    burner_duration=0.0, subtitle_source=subtitle_source,
                    ass_sha256=None, reuse=True,
                )
            )
            continue

        safe_start, safe_end = jitter.safe_times(
            segment.start, segment.end, zones, rng=rng
        )
        if segment.audio in ("narration", "ducked") and not tts_audio:
            raise ValueError(f"第 {index + 1} 段旁白音频缺失，不能用原声顶替")
        ass_path: str | None = None
        # 字幕生成窗口与段内进度分母同源：safe_times 之后的真实窗口
        burner_duration = max(safe_end - safe_start, 0.1)
        if subtitle_source == "burner" and subtitle_burner is not None:
            ass_path = str(
                subtitle_burner(index, str(segment.subtitle_text), burner_duration)
            )
        elif subtitle_source == "provider" and original_subtitle_provider is not None:
            # 原声段没有 subtitle_text（字幕是台词本身，不是解说文案），走独立回调：
            # 它拿到的是 **safe_times 之后的真实窗口**，词级裁剪才能按实际切点重定基；
            # 在调用方按 segment.start/end 预生成字幕的话，抖动挪过的段会整体错位。
            ass_path = original_subtitle_provider(index, safe_start, safe_end)
        ass_sha256 = None if ass_path is None else _sha256_file(ass_path)
        jobs.append(
            _SegmentJob(
                index=index,
                args=cut_segment_args(
                    source,
                    str(seg_path),
                    start=safe_start,
                    end=safe_end,
                    audio=segment.audio,
                    tts_audio=tts_audio,
                    rng=rng,
                    transition=segment.transition,
                    ass_path=ass_path,
                    out_size=out_size,
                    video_codec=video_codec,
                    fps=output_fps,
                    fade_in_s=vin,
                    fade_out_s=vout,
                    afade_in_s=ain,
                    afade_out_s=aout,
                    # 只在我们烧字幕的段擦源带（ass_path 为空=该段画面保留原样，
                    # raw_clip 整片、交叉的原声段都属此类——原片台词字幕是内容，不能抹）；
                    # 有行框用行框（贴行不贴带），行框缺失回退整带
                    erase_rects=(
                        (subtitle_erase_rects or {}).get(segment.episode_id)
                        or (
                            [band]
                            if (band := (subtitle_bands or {}).get(segment.episode_id))
                            else None
                        )
                        if ass_path is not None
                        else None
                    ),
                    # 台词驻留窗（源绝对秒）：delogo 只在有字的那几秒挂，无字画面的
                    # 补丁痕迹消失（2026-10-09 裁决③）。整集窗共用，不按行分——
                    # OCR 条按帧拼接整行文本，行级时间没有落库。
                    erase_windows=(subtitle_erase_windows or {}).get(segment.episode_id),
                    ai_label_vf=None if label_spec is None else label_spec.vf,
                    drama_name_vf=None if drama_spec is None else drama_spec.vf,
                ),
                seg_path=seg_path,
                inputs=inputs,
                safe_start=safe_start,
                safe_end=safe_end,
                # 段内进度分母：声明时长（dedup 微变速 ±0.4% 忽略，runner 侧
                # min(fraction,1) 钳住）
                progress_duration=max(safe_end - safe_start, 0.05),
                burner_duration=burner_duration,
                subtitle_source=subtitle_source,
                ass_sha256=ass_sha256,
                reuse=False,
            )
        )

    if cancel is not None and cancel.is_set():
        raise runner.FfmpegError("已取消", cancelled=True)

    # 段内进度平滑（调研②）：总进度 = (已完成段 + 当前段内比例)/总段数 × 90。
    # Phase A 并行时段收集序 ≠ 完成序，peak 钳住保证单调不减——进度条回退比冻结更像 bug。
    # B4：复用段直接预置进 completed 基线，续跑时进度条从已完成处起算，不从 0 爬。
    #
    # 完成基线用 **worker 侧写入的 completed 集合**而不是主线程 result() 之后才更新的
    # 计数：parallel=1 时同一 worker 顺序跑段，上一段 _finish 里的 completed.add
    # 必然 happens-before 下一段的 _intra——基线确定；主线程计数跑在 result() 之后，
    # 与 worker 抢跑会输（B4 落地时实测：sig 落盘的毫秒级 I/O 就足以让第二段的段内
    # 回调读到旧计数，67.5 被 peak 钳成 22.5，test_progress 红）。
    progress_lock = threading.Lock()
    completed: set[int] = {job.index for job in jobs if job.reuse}
    progress_state = {"peak": 0.0}
    # 段级回退发生过就整片统一重跑（见 A4-2 注释）；worker 线程写、主线程读
    fallback_seen = {"v": False}

    def _emit(percent: float, label: str) -> None:
        if on_progress is None:
            return
        with progress_lock:
            percent = max(percent, progress_state["peak"])
            progress_state["peak"] = percent
        on_progress(percent, label)

    def _cut_one(job: _SegmentJob) -> None:
        index = job.index
        args = job.args
        actual_codec = args[args.index("-c:v") + 1]

        def _finish() -> None:
            """段编码成功后写 sidecar 签名（产物存在才写；写签名失败不挡导出）。"""
            if job.seg_path.is_file() and job.seg_path.stat().st_size > 0:
                with contextlib.suppress(OSError):
                    _write_sig_atomic(
                        job.seg_path,
                        {
                            "version": _SIG_VERSION,
                            "inputs": job.inputs,
                            "recorded": {
                                # A4 自洽：记**实际成功**的 codec（回退过就是 libx264），
                                # 下次请求同 codec 才跳过；concat 签名检查零改动。
                                "actual_codec": actual_codec,
                                "safe_start": job.safe_start,
                                "safe_end": job.safe_end,
                                "duration_s": job.burner_duration,
                                "subtitle_source": job.subtitle_source,
                                "ass_sha256": job.ass_sha256,
                            },
                        },
                    )
            with progress_lock:
                completed.add(index)

        if on_progress is None:
            try:
                _run_cut(args, cancel)  # 旧路径逐字节不变（不追加 -progress）
            except runner.FfmpegError as exc:
                if not _fallback_eligible(exc, args):
                    raise
                _retry_with_libx264(index, args, exc, cancel)
                actual_codec = _FALLBACK_CODEC
            _finish()
            return

        def _intra(fraction: float) -> None:
            with progress_lock:
                done = len(completed)
            _emit((done + min(fraction, 1.0)) / total * 90, f"切割第 {index + 1} 段")

        try:
            _run_cut(
                args,
                cancel,
                total_duration_s=job.progress_duration,
                on_progress=_intra,
            )
        except runner.FfmpegError as exc:
            if not _fallback_eligible(exc, args):
                raise
            _retry_with_libx264(
                index, args, exc, cancel,
                total_duration_s=job.progress_duration,
                on_progress=_intra,
            )
            actual_codec = _FALLBACK_CODEC
        _finish()

    def _retry_with_libx264(
        index: int,
        args: list[str],
        exc: runner.FfmpegError,
        cancel: threading.Event | None,
        *,
        total_duration_s: float | None = None,
        on_progress: runner.ProgressCallback | None = None,
    ) -> None:
        """A4-2 段级回退：清半成品 → libx264 重跑一次；重跑仍失败才抛。"""
        fallback_seen["v"] = True
        seg_path = Path(args[-1])
        with contextlib.suppress(OSError):
            seg_path.unlink(missing_ok=True)  # 半成品不删会被 Phase B concat 拼进去
        fallback_args = _args_with_codec(args, _FALLBACK_CODEC)
        hw_codec = args[args.index("-c:v") + 1]
        if _report_state is not None:
            # 回执只记第一处失败原文（人话原因），次数另计；统一重跑后一并汇总。
            _report_state["fallback"] = True
            _report_state["fallback_count"] = int(_report_state.get("fallback_count") or 0) + 1
            if not _report_state.get("reason"):
                _report_state["reason"] = (
                    f"第 {index + 1} 段硬编 {hw_codec} 失败（kind={exc.kind}）：{str(exc)[:200]}"
                )
        _LOGGER.warning(
            "第 %d 段硬编 %s 失败（kind=%s）：已清半成品，回退 %s 重跑：%s",
            index + 1, hw_codec, exc.kind, _FALLBACK_CODEC, str(exc)[:200],
        )
        _run_cut(
            fallback_args,
            cancel,
            total_duration_s=total_duration_s,
            on_progress=on_progress,
        )

    if reused_count:
        _LOGGER.info(
            "断点续跑：%d/%d 段输入签名一致，跳过重编", reused_count, total
        )
        _emit(reused_count / total * 90, f"复用 {reused_count}/{total} 段")

    # Phase A 并行执行（ffmpeg 自身多线程，2 并发已接近 IO/CPU 饱和）；复用段不进池
    encode_jobs = [job for job in jobs if not job.reuse]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(_cut_one, job) for job in encode_jobs]
        done = reused_count
        for future in futures:
            future.result()
            done += 1
            _emit(done / total * 90, f"切割 {done}/{total}")
            if cancel is not None and cancel.is_set():
                raise runner.FfmpegError("已取消", cancelled=True)

    # 统一收口在 concat 之前：一旦本轮有回退，就不让"硬编段+回退段"混排着拼成片
    if fallback_seen["v"] and _allow_uniform_retry:
        raise _UniformCodecRetry()

    manifest = _concat_manifest(jobs)
    _concat([item.path for item in manifest], out_path)
    if bgm_track is not None and loudness_target is not None:
        # 床+响度同链：混床落 PCM 中间件（少一代 AAC 有损），响度归一在它身上
        # 续编出最终 192k——段 128k → 终编共两代，不再三段三编。混床失败按增强项
        # 降级（响度归一照跑）；响度归一失败仍是硬失败（loudness 链语义不变）。
        try:
            staged_bed = _mix_bgm_bed(
                out_path, bgm_track, work_dir / "bgm", lossless_intermediate=True
            )
        except Exception as exc:  # noqa: BLE001 - 网络型/瞬时型失败重试一次再降级
            _LOGGER.warning("BGM 床混音失败（%s），重试一次", str(exc)[:200])
            try:
                staged_bed = _mix_bgm_bed(
                    out_path, bgm_track, work_dir / "bgm", lossless_intermediate=True
                )
            except Exception as exc2:  # noqa: BLE001 - 增强项失败不挡已拼好的成片
                _LOGGER.warning(
                    "BGM 床混音重试仍失败（%s）：本条成片不带 BGM 出片", str(exc2)[:200]
                )
                staged_bed = None
        if staged_bed is not None:
            loudness.normalize_in_place(
                staged_bed, target=loudness_target, work_dir=work_dir / "loudnorm"
            )
            staged_bed.replace(out_path)
    else:
        if bgm_track is not None:
            try:
                mixed = _mix_bgm_bed(out_path, bgm_track, work_dir / "bgm")
            except Exception as exc:  # noqa: BLE001 - 增强项失败不挡已拼好的成片（进程日志是底账）
                _LOGGER.warning("BGM 床混音失败（%s）：本条成片不带 BGM 出片", str(exc)[:200])
            else:
                mixed.replace(out_path)
        if loudness_target is not None:
            loudness.normalize_in_place(
                out_path, target=loudness_target, work_dir=work_dir / "loudnorm"
            )
    if aigc_stamp is not None:
        # 隐式标识走最终交付遍：concat 单段 copyfile 分支不经过 ffmpeg，
        # BGM/响度再 mux 的元数据存活性各分支不一——这里写一次覆盖所有路径。
        aigc_metadata.stamp(out_path, producer=aigc_stamp[0], content_id=aigc_stamp[1])
    if segment_offsets_sink is not None:
        offsets = _segment_offsets(manifest)
        if offsets is not None:
            segment_offsets_sink(offsets)
    if on_progress is not None:
        on_progress(100.0, "导出完成")
    return out_path

