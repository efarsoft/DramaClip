"""导出编码器：滤镜链编排与两阶段执行（原案 7.1）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import subprocess  # noqa: S404 - 参数为受控列表
import sys
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.dedup import jitter
from dramaclip.engines.dedup import params as dedup_params
from dramaclip.engines.exporter import loudness
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.engines.subtitle import caption_font
from dramaclip.infra import config
from dramaclip.infra.ffmpeg import probe as ffprobe_mod
from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg, resolve_ffprobe
from dramaclip.infra.ffmpeg.probe import probe

_LOGGER = logging.getLogger(__name__)

# 画幅数值不在这里定义（docs/04 §5.2）：源是 infra.config，settings 默认值读的是同一个常量。
_DEFAULT_OUT_SIZE = (config.EXPORT_WIDTH, config.EXPORT_HEIGHT)

# 段级真峰天花板（dBFS）：**每一段交付音频**都过这道限幅，不分混音还是原声直通。
#
# 为什么必须有（混音分支的来历）：Task 7 把 `amix` 的默认归一化关掉（声明的 0.2/0.12
# 才是实际值）时，顺带关掉了它**意外的削顶保护**——原先每路除以 2 等于白送 6 dB 余量。
# 真机实测（`resources/ffmpeg/ffmpeg.exe` 8.1.1-essentials）：真实源集 5 s 窗口（源自身
# `input_tp=+0.30`）配 +3.0 dBTP 的旁白，混音段 `input_tp=+4.37 dBTP`、采样峰 +4.36 dB
# （硬削顶，不可逆的失真）；真成片 `intro_narration_325c84` 整片 `input_tp=+3.26 dBTP`。
#
# 为什么天花板必须**长出混音分支之外**（这一版新加的账，九模式门禁实测）：
# 片源 `小小球神不好惹` 10 集全部 stereo 48k，**源音频进仓就在削顶**。Phase C 之前的
# 九部真成片里七部 `input_tp` 是 −3.77…−2.17 dBTP，另外两部是 **+3.38**
# （`intro_narration_c3eb30`，207.8 s）与 **+1.88**（`ultra_short_hook_2c9b87`，15.2 s）
# ——恰好就是时间轴里带 `original` 段的那两部。漏点正是本函数 `else` 那条：
# 混音分支有限幅、直通分支只有 `atempo`，源素材自己的热度原样穿过 AAC 128k 进了成片
# （`raw_clip` 整片 +2.98 dBTP 同一成因）。loudnorm 只能再限、不能"反削顶"，
# 而 AAC 重编已削平的波形还会过冲，所以 Phase C 的有界真峰重试也救不回来
# （实测 1.5 dB 余量重试后仍 −0.2 dBTP，整条导出硬失败）。
#
# 取 -3.0 的依据：段级音轨是 AAC 128k，编码后还会抬出采样间过冲。实测同一窗口
# 128k 编解码回环把 +0.30 抬到 **+4.04 dBTP**（换 192k 只抬到 +0.48）——过冲的大头是
# **已经削平的平顶波形**，所以先把求和限干净：限到 -3.0 dBFS 之后 128k 只再抬
# 0.57–1.06 dB（四例实测：合成 narration 段 -2.43、合成 ducked 段 -1.94、
# 真源 narration 段 -2.12、真源 ducked 段 -2.18 dBTP），段真峰稳在 0 dBTP 之下
# （tests/engines/exporter/test_mix.py 用真 ffmpeg 钉住，含"剥掉限幅器必须超标"的对照组）。
# 代价：旁白本来就热到碰天花板时，混音段实测掉 0.77 LU / 真峰掉 0.81 dB——这是限幅不是电平，
# 掉的电平 Phase C 按目标响度补回来。它**不接管绝对响度**，Phase C 仍是唯一负责人。
#
# 边界（诚实记账，别把这道天花板当保证）：对**进仓就已削平**的源，限幅器能把电平压回
# -3.0 dBFS，却不能把削掉的顶长回来；AAC 重编平顶波形的过冲照旧，而且**过冲跟着削顶深度走**。
# 真机实测（同一张 aevalsrc 床，`resources/ffmpeg/ffmpeg.exe` 8.1.1-essentials，走完整条
# else 分支到 AAC 128k 段；素材确定性：同一命令两次生成的 mp4 md5 逐字节相同）：
#   源 +1.98（抬 1.4 倍落 s16 平顶）→ 剥限幅 +1.41 / 挂限幅 **-0.87**（掉 2.28 dB，过冲 2.13）
#   源 +3.59（抬 2.0 倍落 s16 平顶）→ 剥限幅 +3.33 / 挂限幅 **+0.37**（掉 2.96 dB，仍过 0）
#   源 +2.29（抬 1.4 倍、**未削平**）→ 剥限幅 -0.11 / 挂限幅 **-2.31**（落进 1.5 dB 预算）
# 读法：**源没被削平时预算成立**；源已是平顶时"限回 -3.0 dBFS"能做到、"落进预算"做不到，
# 削得越深漏得越多——真机超标那部整片 +3.38 dBTP 正落在第二档那一带，所以别把段级天花板
# 当成出口保证。它的作用是"没削平的源彻底治住 + 已削平的源少漏 2~3 dB"，剩下的账仍由
# Phase C 的真峰门限与有界重试负责（见 loudness.py）。三档都在 tests/engines/exporter/
# test_mix.py 用真 ffmpeg 钉住，含"剥掉限幅器必须超标"的对照组与 level=enabled 变异
# （实测把段真峰推回 +1.34 / +0.28 dBTP，自动电平按 1/limit 抵消天花板）。
#
# 为什么是 **-9.0** 而不是原先的 -3.0（2026-09-12 实测改的，别顺手改回去）：
# 加了下面的 `_audio_format_filter()` 之后，同一张削平热源的段真峰从原记录的 +0.37
# 变成了 **+2.07 dBTP**（`test_original_ceiling_holds_acoustically` 当场量到的数）——
# 强制 stereo 改变了 AAC 的编码模式，平顶波形上的采样间过冲跟着变大，-3.0 那道天花板
# 于是不再成立。降到 -9.0 是给这部分过冲留出余量。
# **降天花板不损失任何交付响度**：绝对响度由 Phase C 的 `loudnorm`/增益路统一负责
# （见 loudness.py），段级天花板只是余量管理；代价仅是进 AAC 前信号低 6 dB，
# 192k/128k AAC 上听不出来，而 Phase C 会把电平补回目标。
_SEGMENT_PEAK_CEILING_DBFS = -9.0

# 段级音频格式：**每一段交付音频**的采样率与声道布局都必须逐字相同。
#
# 为什么必须有这一级（真机实测，`resources/ffmpeg` 8.1.1-essentials）：`amix` 会把求和
# 收成 mono——混音段的旁白是 mono（真 TTS 产物 `preflight.mp3` 实测 `24000 Hz / 1 ch`），
# 原声是 stereo（真片源 `小小球神不好惹/1.mp4` 实测 `aac / 48000 Hz / 2 ch / stereo`），
# 两路进 amix 之后 ffmpeg 的格式协商选了 mono，**原声被下混**；而原声直通段跟着源走 stereo。
# Phase B 又是 `-c copy` 流复制，两种布局照单拼进同一条音轨。实测一段 narration + 一段
# original 各 5 s 拼起来：`ffprobe … frame=channel_layout | sort | uniq -c` → **236 mono /
# 472 stereo**（真成片同法：`ultra_short_hook_2c9b87` → 177 mono / 533 stereo，
# `intro_narration_c3eb30` → 399 mono / 9299 stereo）。
#
# 后果是**任何响度读数都不复现**：布局换点处 ffmpeg 打印 `Reconfiguring filter graph`、
# 把测量滤镜 flush 掉，一次运行吐出**两块** ebur128 Summary；门禁与 Phase C 都取最后一块，
# 而最后一块只覆盖换点之后。实测同一片直接量 mp4 连跑三次 I = **-14.3 / -14.5 / -13.9 LUFS**
# （2 块 Summary、1 次 Reconfiguring），先解码成 stereo WAV 再量则是 **1 块、0 次、
# I = -15.5 三次逐位相同**——最后一块把整片响度高估约 1.2 LU，而且它自己就不复现。
# Phase C 的决策读数用的是同一套量法，所以增益路的可行性预测继承同样的误差
# （`loudness.py` 实测那部 15.32 s 的片子上增益路漂 1.20 LU）。
#
# 为什么钉 **stereo** 而不是 mono：源素材本来就是 stereo，全部下混成 mono 是实打实的
# 画质外的音质倒退（今天 amix 已经在混音段上意外这么干了）；反过来把 mono 旁白升成
# dual-mono 不丢任何信息。stereo 也是唯一能同时满足两条分支的布局。
#
# 为什么挂在**每条音频链的头一级**而不是收尾（三种改法都用真 ffmpeg 量过，素材同上，
# 一段 narration + 一段 original 走真 `cut_segment_args` + 真 `_concat`）：
#   aformat 挂头（本实现）  → 708 帧全 stereo、1 块、三次 I=-15.5、段真峰 **-0.3 dBTP**
#   aformat 挂尾（限幅之后）→ 布局同样均匀，但段真峰 **+0.1 dBTP**（高 0.4 dB，过了 0）
#   pan 只挂旁白那一路      → 布局均匀靠的是"源恰好是 stereo"，直通段仍跟着源走
# 挂尾那 0.4 dB 正是既有注释与用例钉住的那条不变量：**限幅器必须是进 AAC 前的最后一级**，
# 后面再重采样会重新长出采样间过冲。所以格式统一放在头、限幅器收尾。
# `pan` 不选的理由：mono 源集会让直通段照样输出 mono，布局统一这件事就取决于素材了。
_SEGMENT_SAMPLE_RATE = 48000
_SEGMENT_CHANNEL_LAYOUT = "stereo"

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

    band_filter: list[str] = []
    for rect_top, rect_bottom in erase_rects or []:
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
        band_filter.append(f"delogo=x={content_x}:y={delogo_y}:w={delogo_w}:h={delogo_h}")

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
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-r",
        "30",
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
    import os

    normalized = path.replace("\\", "/")
    if ":" not in normalized:
        return normalized.replace("'", r"\'")
    try:
        relative = os.path.relpath(normalized).replace("\\", "/")
    except ValueError:
        relative = normalized
    if not relative.startswith(".."):
        return relative.replace("'", r"\'")
    return normalized.replace(":", r"\\:").replace("'", r"\'")


# ---- A4-1 硬编探测：平台候选序 + 同形状质量参数真试编 + 会话级缓存 ----

# 硬编候选序按平台：Windows/Linux 先 NVENC 后 QSV（Intel 核显），macOS 只有
# VideoToolbox。编码器「列表里有」≠「真编能过」（驱动残缺/GPU 会话数满），所以每个
# 候选都要做 0.1s 黑帧**真试编**——且必须带与正式合成**同形状**的质量参数
# （`_video_codec_params`），只 `-f null` 探不出「参数不识别」这类实编挂。
_HW_CANDIDATES_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    "win32": ("h264_nvenc", "h264_qsv"),
    "darwin": ("h264_videotoolbox",),
}
_HW_CANDIDATES_LINUX: tuple[str, ...] = ("h264_nvenc", "h264_qsv")

# 驱动挂起兜底：探测真编不许拖住导出超过 15s（正式段编码仍走 _run_cut 默认 600s）。
_HW_PROBE_TIMEOUT_S = 15.0


def _hw_candidates(platform: str | None = None) -> list[str]:
    """当前平台的硬编候选序（win32/darwin 显式表，其余平台按 linux 序）。"""
    key = sys.platform if platform is None else platform
    if key in _HW_CANDIDATES_BY_PLATFORM:
        return list(_HW_CANDIDATES_BY_PLATFORM[key])
    return list(_HW_CANDIDATES_LINUX)


def _video_codec_params(video_codec: str) -> list[str]:
    """各编码器的质量参数——正式合成与探测真试编读**同一处**构造（不许各写一份）。"""
    if video_codec == "h264_nvenc":
        return ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "22"]
    if video_codec == "h264_qsv":
        # QSV 用全局质量（ICQ）对齐 NVENC 的 VBR+CQ 语义；preset 名与 x264 系不同。
        return ["-preset", "medium", "-global_quality", "22"]
    if video_codec == "h264_videotoolbox":
        return ["-q:v", "55"]
    return ["-preset", "veryfast", "-crf", "20"]


def _hw_probe_args(video_codec: str) -> list[str]:
    """0.1s 黑帧真试编命令：与正式段编码同形状的质量参数，输出到 null。"""
    return [
        "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
        "-c:v", video_codec, *_video_codec_params(video_codec),
        "-f", "null", "-",
    ]


_HW_LOCK = threading.Lock()
# 缓存「选中的编码器名」（None=全失败也缓存）：会话级结果，防换卡/驱动更新后陈旧
# 的代价由进程生命周期界定；旧 _NVENC_CACHE(bool) 形状被 pick_hw_encoder 取代。
_HW_ENCODER_CACHE: str | None = None


def pick_hw_encoder() -> str | None:
    """返回第一个真试编通过的硬编编码器名；全失败/探测自身异常返回 None。

    探测自身的任何异常（驱动崩溃、OSError）都吞掉按不可用处理——best-effort 增强
    绝不反过来把本来能软编成功的导出挡死。
    """
    global _HW_ENCODER_CACHE  # noqa: PLW0603
    with _HW_LOCK:
        if _HW_ENCODER_CACHE is None:
            chosen: str | None = None
            for candidate in _hw_candidates():
                try:
                    _run_cut(_hw_probe_args(candidate), timeout_s=_HW_PROBE_TIMEOUT_S)
                except Exception:  # noqa: BLE001 - 驱动/会话异常一律按该候选不可用
                    continue
                chosen = candidate
                break
            # 用哨兵区分「还没探过」与「探过、全失败」：全失败缓存为 ""，
            # 避免每次导出都重试真编（黑帧 0.1s×候选数，机器慢时是秒级）。
            _HW_ENCODER_CACHE = chosen if chosen is not None else ""
            if chosen is None:
                _LOGGER.info("硬编探测：所有候选不可用，回退 libx264")
            else:
                _LOGGER.info("硬编探测：选用 %s", chosen)
        return _HW_ENCODER_CACHE or None


def nvenc_available() -> bool:
    """旧签名兼容（api/export.py 无参调用）：严格语义 = pick_hw_encoder() 选中 NVENC。

    不放宽成「任何硬编可用」：调用方拿到 True 后写死 h264_nvenc，若这里在 mac 上因
    videotoolbox 返回 True 就会用 NVENC 真编挂掉。新调用方直接用 pick_hw_encoder()。
    """
    return pick_hw_encoder() == "h264_nvenc"


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

_HW_ENCODERS = frozenset({"h264_nvenc", "h264_qsv", "h264_videotoolbox"})
_FALLBACK_CODEC = "libx264"
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
#
# 选型（b）sidecar 签名，不选（a）按 export_id 播种 rng。理由：
# - rng 同时喂 jitter.safe_times 与 dedup_params.generate，「每片段独立随机、避免
#   批量成品呈规律性」是消重设计的一部分（docs/06 §1）。按 export_id 播种会把
#   一次导出的全部抖动/消重参数变成可复现常量，等于取消「每片段独立随机、
#   逐次渲染各不相同」这一设计前提；
# - 播种也救不了新鲜渲染的行为一致性：现状 rng 无种子，任何「复现上次切点」的
#   方案都改变了 fresh run 的输出分布（硬验收：空 work_dir 行为与现状一致）；
# - 即便播种，跳过判定仍需要「产物在不在、输入变没变」的签名——（a）不能替代（b）。
#
# 签名判据：**声明输入**一致才复用——源文件身份（path+size+mtime_ns）、episode_id、
# 声明 start/end、audio 角色、transition、seam 淡入淡出、out_size、字幕接线形状、
# 字幕文本 hash、TTS 音频 path+内容 sha256、台词保护区内容哈希（srt/ASR zones）、
# 请求 codec == sig 记录的**实际成功** codec（A4 回退自洽）。
# **不含 jitter 后的实际切点**：复用即接受上次的抖动切点与消重参数（它们本来就是
# 每次渲染要不同的量）；上次窗口只作为「recorded」元数据存着，用来确定性地重新
# 生成字幕 ass 并比对内容 hash——预设/拆行逻辑/emotion 这些编码器看不见的隐藏
# 输入全靠这一步兜住。只查文件存在不查签名 = autoclip 的反例，禁止。
#
# 成对性与原子性：sig 与 seg 同生命周期——任何一边缺失/损坏都重编；sig 只在段
# 编码成功且产物存在后写，tmp+replace 原子落盘（与 A5 TTS 缓存同形状），崩溃留下
# 的半成品（cancel/进程被杀）永远没有 sig，下次自然重编。
# 陈旧尾段：上次更长的计划留下的 seg/sig（索引 >= 本次段数）必须清掉，否则会被
# Phase B 的 glob("seg_*.mp4") 捡进 concat。
_SIG_VERSION = 1


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


def _sig_path_for(seg_path: Path) -> Path:
    return seg_path.with_suffix(".sig")


def _sha256_file(path: str | Path) -> str | None:
    """文件内容 sha256；读不到返回 None（调用方按不可复用处理）。"""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _file_identity(path: str | Path) -> dict[str, object]:
    """源文件身份：path+size+mtime_ns。stat 失败给 -1（必与任何真实签名不等）。"""
    try:
        stat = Path(path).stat()
    except OSError:
        return {"path": str(path), "size": -1, "mtime_ns": -1}
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _zones_fingerprint(zones: list[SpeechZone]) -> str:
    """台词保护区内容哈希：手工 .srt 或库内 ASR 变了，切点语义就变了，不许复用。"""
    payload = json.dumps([[zone.start, zone.end] for zone in zones])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_sig(seg_path: Path) -> dict[str, Any] | None:
    """读 sidecar 签名：缺任何一边/损坏/版本或形状不对都返回 None（按不可复用）。

    产物必须非空（与 A5 缓存的 `_usable` 同判据）：0 字节残留不是可复用产物。
    """
    sig_path = _sig_path_for(seg_path)
    if not sig_path.is_file():
        return None
    try:
        if not (seg_path.is_file() and seg_path.stat().st_size > 0):
            return None
        payload = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError 含 JSONDecodeError：损坏按不可复用
        return None
    if not isinstance(payload, dict) or payload.get("version") != _SIG_VERSION:
        return None
    inputs = payload.get("inputs")
    recorded = payload.get("recorded")
    if not isinstance(inputs, dict) or not isinstance(recorded, dict):
        return None
    return {"inputs": inputs, "recorded": recorded}


def _write_sig_atomic(seg_path: Path, payload: dict[str, Any]) -> None:
    """签名原子落盘（tmp+replace，A5 缓存同形状）：崩溃只会丢 sig，不会留半截可误读的。"""
    sig_path = _sig_path_for(seg_path)
    tmp = seg_path.with_name(f"{seg_path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, sig_path)
    finally:
        tmp.unlink(missing_ok=True)


def _reusable_subtitles(
    index: int,
    segment: TimelineSegment,
    recorded: dict[str, Any],
    subtitle_source: str,
    subtitle_burner: Callable[[int, str, float], str] | None,
    original_subtitle_provider: Callable[[int, float, float], str | None] | None,
) -> bool:
    """复用候选段的字幕校验：用**上次记录的窗口**重新生成 ass，内容 hash 必须与记录一致。

    为什么必须重新生成而不是「旧 ass 文件还在就行」：ass 字节由预设、拆行逻辑、
    emotion 标签共同决定，编码器看不见这些量；重新生成一遍才证明它们没变。
    生成窗口取 sig 里记的上次值而非本次 jitter 切点——否则时间字段必然不同，
    复用永不命中（rng 无种子）。任何异常/hash 不一致→不可复用（重编）。
    """
    if recorded.get("subtitle_source") != subtitle_source:
        return False
    want = recorded.get("ass_sha256")
    produced: str | None = None
    try:
        if subtitle_source == "burner":
            if subtitle_burner is None:
                return False
            produced = subtitle_burner(
                index, str(segment.subtitle_text or ""), float(recorded["duration_s"])
            )
        elif subtitle_source == "provider":
            if original_subtitle_provider is None:
                return False
            produced = original_subtitle_provider(
                index, float(recorded["safe_start"]), float(recorded["safe_end"])
            )
        elif subtitle_source != "none":
            return False
    except Exception:  # noqa: BLE001 - 校验失败按不可复用处理，绝不挡正常编码
        return False
    if produced is None:
        return want is None
    return want is not None and _sha256_file(produced) == want


def _prune_stale_segments(work_dir: Path, segment_count: int) -> None:
    """清掉上次更长的计划留下的 seg/sig 尾段（索引 >= 本次段数）。

    不清就会被 Phase B 的 glob("seg_*.mp4") 捡进 concat——旧尾段的输入签名再对
    也没人要它了。只按 seg_NNN 命名清 .mp4/.sig 两种，不碰 api 层的 seg_NNN.ass。
    """
    for pattern in ("seg_*.mp4", "seg_*.sig"):
        for path in work_dir.glob(pattern):
            try:
                index = int(path.stem.rsplit("_", 1)[-1])
            except ValueError:
                continue
            if index >= segment_count:
                path.unlink(missing_ok=True)


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
) -> Path:
    """执行两阶段导出，返回成片路径。

    A4-2 统一收口：请求硬编而中途发生段级回退时，整片换 libx264 再跑一次
    （见 _UniformCodecRetry 注释）——已回退段凭签名复用，只有硬编成功的段重编。
    """
    try:
        return _export_plan_once(
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
            _allow_uniform_retry=True,
        )
    except _UniformCodecRetry:
        _LOGGER.warning(
            "本轮出现段级硬编回退：整片按 %s 统一重跑一次，"
            "消除段间编码器混排的画质跳变（已回退段将凭签名复用）",
            _FALLBACK_CODEC,
        )
        return _export_plan_once(
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
            _allow_uniform_retry=False,
        )


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
    _allow_uniform_retry: bool = True,
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
            jobs.append(
                _SegmentJob(
                    index=index, args=[], seg_path=seg_path, inputs=inputs,
                    safe_start=0.0, safe_end=0.0, progress_duration=0.05,
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

    segment_files = sorted(work_dir.glob("seg_*.mp4"))
    _concat(segment_files, out_path)
    if loudness_target is not None:
        loudness.normalize_in_place(
            out_path, target=loudness_target, work_dir=work_dir / "loudnorm"
        )
    if on_progress is not None:
        on_progress(100.0, "导出完成")
    return out_path


def _concat(segment_files: list[Path], out_path: Path) -> None:
    """Phase B：concat demuxer 拼接 + 元数据擦除。

    A4-2 签名守卫：各段视频流签名（codec_name/profile/level/pix_fmt/宽高）一致才走
    `-c copy` 流复制；不齐（典型：某段硬编失败回退了 libx264）或签名探测自身失败时
    保守整体重编码 concat——流复制混拼不一致的流是「导出到 90% 崩」的一条路。
    拼完做时长审计（实测 vs 各段声明和，超阈值只 warn 不失败；审计自身异常静默）。
    """
    if len(segment_files) == 1:
        out_path.write_bytes(segment_files[0].read_bytes())
        _audit_film_duration(out_path, segment_files)
        return
    signatures = [_video_signature(segment) for segment in segment_files]
    uniform = signatures[0] is not None and all(sig == signatures[0] for sig in signatures)
    if not uniform:
        _LOGGER.warning(
            "段视频流签名不齐或不可测（%s）：concat 整体重编码而非流复制",
            signatures,
        )
    list_file = out_path.parent / "concat.txt"
    lines = "".join(f"file '{segment.resolve().as_posix()}'\n" for segment in segment_files)
    list_file.write_text(lines, encoding="utf-8")
    codec_args = (
        ["-c", "copy"]
        if uniform
        else [
            "-c:v", _FALLBACK_CODEC, "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", str(_SEGMENT_SAMPLE_RATE),
        ]
    )
    subprocess.run(  # noqa: S603
        [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            *codec_args,
            "-map_metadata",
            "-1",
            str(out_path),
        ],
        check=True,
        capture_output=True,
        # 重编码 concat 是整片再编一遍，预算要比流复制宽（300s 对长片不够）
        timeout=300 if uniform else 3600,
    )
    list_file.unlink(missing_ok=True)
    _audit_film_duration(out_path, segment_files)


def _video_signature(path: Path) -> tuple[str, str, int, str, int, int, str] | None:
    """段的视频流签名（concat 流复制的一致性前提）；测不出返回 None（→保守重编码）。

    `sample_aspect_ratio` 必须在内：两套存储尺寸相同、像素比不同的流（setsar 修复前
    的旧段 vs 新段）在 `-c copy` 下会拼成一条播放器按首段横向拉伸的片子，且毫无痕迹。
    """
    try:
        result = subprocess.run(  # noqa: S603
            [
                resolve_ffprobe(),
                "-v", "error",
                "-print_format", "json",
                "-select_streams", "v:0",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return None
        streams = json.loads(result.stdout).get("streams") or []
        if not streams:
            return None
        stream = streams[0]
        return (
            str(stream.get("codec_name") or ""),
            str(stream.get("profile") or ""),
            int(stream.get("level") or 0),
            str(stream.get("pix_fmt") or ""),
            int(stream.get("width") or 0),
            int(stream.get("height") or 0),
            # ffprobe 对方形像素报 "1:1"，个别容器/编码流不带该字段 → ""（同值即同几何）
            str(stream.get("sample_aspect_ratio") or ""),
        )
    except Exception:  # noqa: BLE001 - 签名探测失败按不齐处理，绝不挡已成功的段编码
        return None


# 时长容差的**唯一**落点：三处判据（本层段和 warn、api 层渲染后 warn、
# selfcheck 成品库红绿）全部引用这两个名字——改一处即三处同改，界面绿/日志 warn
# 的分叉没有第二种写法。容得下 dedup 微变速（±0.4%）、切点抖动与 AAC/concat
# 的毫秒级出入，只抓缺段/重复级真偏差。
AUDIT_DURATION_REL_TOLERANCE = 0.08
AUDIT_DURATION_ABS_TOLERANCE_S = 3.0


def _audit_film_duration(out_path: Path, segment_files: list[Path]) -> None:
    """成片实测时长 vs 各段声明和：超阈值 warn 明账；审计自身任何异常静默吞掉。"""
    with contextlib.suppress(Exception):
        declared = sum(ffprobe_mod.probe(segment).duration_s for segment in segment_files)
        if declared <= 0:
            return
        actual = ffprobe_mod.probe(out_path).duration_s
        diff = actual - declared
        tolerance = max(
            declared * AUDIT_DURATION_REL_TOLERANCE, AUDIT_DURATION_ABS_TOLERANCE_S
        )
        if abs(diff) > tolerance:
            _LOGGER.warning(
                "成片时长审计：实测 %.1fs vs 段声明和 %.1fs（差 %+.1fs，超阈值 ±%.1fs）",
                actual, declared, diff, tolerance,
            )
