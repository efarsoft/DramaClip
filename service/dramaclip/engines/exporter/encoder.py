"""导出编码器：滤镜链编排与两阶段执行（原案 7.1）。

Phase A 逐段：精确切割 → 竖屏 1080x1920 裁切 → 消重（微缩放/eq/微变速）
        → 遮罩（非纯原片模式）→ 段级混音（narration/ducked 段旁白 + 原声压低 + 求和限幅）
        → 段级真峰天花板（**混音与原声直通两条分支都挂**，见 `_SEGMENT_PEAK_CEILING_DBFS`）
        → 重编码。
Phase B 拼接：concat demuxer（-c copy）+ `-map_metadata -1` 指纹擦除。
Phase C 响度：整片归一到 settings 目标——优先确定性纯增益，素材真需要动态压缩时才走
        两遍 loudnorm（见 loudness.py）。
进度：Phase A 按段数、Phase B 占 10%。
"""

from __future__ import annotations

import random
import subprocess  # noqa: S404 - 参数为受控列表
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.dedup import jitter
from dramaclip.engines.dedup import params as dedup_params
from dramaclip.engines.exporter import loudness
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle.mask import drawbox_filter
from dramaclip.infra import config
from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

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


def _audio_format_filter() -> str:
    """段级音频格式滤镜串——两条分支（含 amix 的两路输入）共用的**唯一**一处构造。

    做成函数而不是把串抄三遍：与 `_peak_ceiling_filter` 同一个理由——抄开之后改布局
    只会改一半，而"只改一半"恰恰是本用例要消灭的那个缺陷本身。
    `sample_rates` 与输出侧的 `-ar` 同源读 `_SEGMENT_SAMPLE_RATE`，两处不许各写各的。
    """
    return (
        f"aformat=sample_rates={_SEGMENT_SAMPLE_RATE}"
        f":channel_layouts={_SEGMENT_CHANNEL_LAYOUT}"
    )


def _peak_ceiling_filter() -> str:
    """段级天花板滤镜串——两条分支共用的**唯一**一处构造。

    选 alimiter 不选 acompressor/dynaudnorm：前者是**前瞻**限幅器，`limit` 就是硬天花板，
    而 acompressor 无前瞻（attack 期间瞬时峰照过）、dynaudnorm 是电平器（又会归一化，
    正是 Task 7 要消灭的东西）。

    `level=disabled` 必须显式给——alimiter 的 `level` 默认 true，会按 1/limit 把输出抬回去
    （自动电平，行为等同 maximizer），天花板等于没设；真机实测（0 dBFS 正弦过
    `alimiter=limit=0.7079`）默认 `level=true` → `max_volume 0.0 dB`，`level=disabled`
    → `-3.0 dB`。而且它对根本没碰到天花板的素材照样抬（-38.1 dBFS 的安静信号过默认参数
    变成 -35.1 dB，凭空 +3.0 dB）——那正是 Task 7 刚消灭的"声明值 ≠ 实际值"。

    `latency=true` 补掉前瞻带来的 4.98 ms 音画错位（实测数字见 test_mix）。

    做成函数而不是模块常量：常量在 import 时就把数字烘进串里，改 `_SEGMENT_PEAK_CEILING_DBFS`
    不会生效，`test_ceiling_constant_drives_both_branches` 也就守不住"单一来源"这件事。
    """
    return (
        f"alimiter=limit={10 ** (_SEGMENT_PEAK_CEILING_DBFS / 20):.4f}"
        ":level=disabled:latency=true"
    )


class EpisodeSourceMissing(Exception):
    """时间轴引用的源集文件缺失。"""


def cut_segment_args(
    source: str,
    out_path: str,
    *,
    start: float,
    end: float,
    audio: str,
    mask: bool,
    tts_audio: str | None,
    rng: random.Random,
    transition: str = "cut",
    ass_path: str | None = None,
    out_size: tuple[int, int] = _DEFAULT_OUT_SIZE,
) -> list[str]:
    """构建单段切割命令（Phase A）。

    audio 角色语义：narration 与 ducked 在携带旁白音频时渲染等价（旁白为主 + 原声压低，
    前者原声 20%、后者 12% 衬底）；任一角色拿不到旁白音频时回退纯原声。original 恒原声。
    **两条分支都过 `_SEGMENT_PEAK_CEILING_DBFS` 那道前瞻限幅**：混音分支是因为 Task 7
    关掉 amix 的默认归一化时也关掉了它顺带白送的 6 dB 余量，求和可以直接冲过 0 dBFS；
    原声直通分支是因为源素材自己就在削顶（九模式门禁实测 +1.88/+3.38 dBTP 的两部成片
    都漏在这里），限幅不能反削顶，但少漏一点就少一点，剩下的账 Phase C 负责。
    """
    out_w, out_h = out_size
    dedup = dedup_params.generate(rng)
    speed = dedup.speed_factor
    scaled_w = int(out_w * dedup.scale_factor) // 2 * 2
    scaled_h = int(out_h * dedup.scale_factor) // 2 * 2

    filters = [
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase",
        f"crop={scaled_w}:{scaled_h}",
        f"eq=contrast={dedup.contrast}:brightness={dedup.brightness}",
        f"scale={out_w}:{out_h}",
        f"setpts=PTS/{speed}",
    ]
    box = drawbox_filter(mask, out_size)
    if box:
        filters.append(box)
    if transition == "fade":
        filters.append("fade=t=in:st=0:d=0.25")
    if ass_path:
        filters.append(f"ass={_escape_filter_path(ass_path)}")

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
        # 旁白/压底段：TTS 主音 + 原声压低（旁白 20%，全片衬底 12%）
        # normalize=0 必须显式给：ffmpeg 的 amix 默认把每路除以输入数（此处各砍 6dB），
        # 那样上面的 bg_volume 声明值与实际听感差一倍，响度无人负责。最终响度由 Phase C 统一收口。
        #
        # 求和之后必须挂限幅器：normalize=0 也把 amix 那 6 dB 的意外余量一起去掉了，
        # 旁白 + 原声可以直接冲过 0 dBFS。滤镜选型与 `level=disabled` / `latency=true`
        # 为什么不可省，见 `_peak_ceiling_filter`；实测数字见 test_mix。
        bg_volume = "0.2" if audio == "narration" else "0.12"
        args += ["-i", tts_audio]
        args += [
            "-filter_complex",
            f"[0:v]{','.join(filters)}[v];"
            # 两路输入都先过 `_audio_format_filter()`：amix 的格式协商在"一路 mono 一路
            # stereo"时会选 mono，把原声**下混**掉（实测数字与该选 stereo 的理由见常量注释）。
            # 两路都钉成 stereo 之后 amix 无需协商，求和保持 stereo。
            f"[0:a]{_audio_format_filter()},volume={bg_volume},atempo={speed}[bg];"
            f"[1:a]{_audio_format_filter()},atempo={speed}[tts];"
            f"[bg][tts]amix=inputs=2:duration=first:normalize=0,"
            f"{_peak_ceiling_filter()}[a]",
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
            f"{_audio_format_filter()},atempo={speed},{_peak_ceiling_filter()}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
        ]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
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


def _run_cut(args: list[str]) -> None:
    runner.run(args, timeout_s=600)


def export_plan(
    plan: PlanData,
    episode_paths: dict[str, str],
    out_path: Path,
    work_dir: Path,
    *,
    tts_audio_by_segment: dict[int, str] | None = None,
    mask: bool = True,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    subtitle_burner: Callable[[int, str, float], str] | None = None,
    parallel: int = 2,
    dialogue_zones: dict[str, list[SpeechZone]] | None = None,
    out_size: tuple[int, int] = _DEFAULT_OUT_SIZE,
    loudness_target: loudness.LoudnessTarget | None = None,
) -> Path:
    """执行两阶段导出，返回成片路径。

    Phase A：段级并行切割（竖屏 + 消重 + 遮罩 + 字幕烧录 + 混音）；
    Phase B：concat 拼接 + `-map_metadata -1` 元数据擦除。
    段间无依赖，线程池并行（ffmpeg 自身多线程，2 并发已接近 IO/CPU 饱和）。

    `loudness_target=None` 是测试缝，不是兼容垫片：今天唯一的生产调用点
    （`api/export.py:255`）无条件传值，没有任何生产路径去看模式。
    它也**不是**"零加工模式不做归一"的开关——本仓的"零加工"指的一直是视频包装
    （`docs/service/02-引擎设计.md:57` 不加字幕不遮罩、`api/export.py:31`、
    `modes/__init__.py:27`），raw_clip 照样要过 scale/crop/eq/atempo 抖动 + x264 全量重编码；
    而且 Task 9 的出口判据要求**九个模式全部**落在响度窗口内，给它开口子会直接打破那条。
    生产调用点必传（Phase C 是成片响度的唯一负责人）。
    """
    segments = plan.timeline
    if not segments:
        raise ValueError("编排时间轴为空")
    work_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random()

    total = len(segments)
    # Phase A：构建每段命令参数（含台词保护区安全切点、字幕、混音）
    job_args: list[list[str]] = []
    zones_cache: dict[str, list[SpeechZone]] = {}
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
        safe_start, safe_end = jitter.safe_times(
            segment.start, segment.end, zones_cache[segment.episode_id], rng=rng
        )
        tts_audio = (tts_audio_by_segment or {}).get(index)
        ass_path: str | None = None
        if subtitle_burner is not None and segment.subtitle_text:
            ass_path = str(
                subtitle_burner(
                    index,
                    segment.subtitle_text,
                    max(safe_end - safe_start, 0.1),
                )
            )
        job_args.append(
            cut_segment_args(
                source,
                str(work_dir / f"seg_{index:03d}.mp4"),
                start=safe_start,
                end=safe_end,
                audio=segment.audio,
                mask=mask,
                tts_audio=tts_audio,
                rng=rng,
                transition=segment.transition,
                ass_path=ass_path,
                out_size=out_size,
            )
        )

    if cancel is not None and cancel.is_set():
        raise runner.FfmpegError("已取消", cancelled=True)

    # Phase A 并行执行（ffmpeg 自身多线程，2 并发已接近 IO/CPU 饱和）
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(_run_cut, args) for args in job_args]
        for done, future in enumerate(futures, start=1):
            future.result()
            if on_progress is not None:
                on_progress(done / total * 90, f"切割 {done}/{total}")
            if cancel is not None and cancel.is_set():
                raise runner.FfmpegError("已取消", cancelled=True)

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
    """Phase B：concat demuxer 拼接（流复制）+ 元数据擦除。"""
    if len(segment_files) == 1:
        out_path.write_bytes(segment_files[0].read_bytes())
        return
    list_file = out_path.parent / "concat.txt"
    lines = "".join(f"file '{segment.resolve().as_posix()}'\n" for segment in segment_files)
    list_file.write_text(lines, encoding="utf-8")
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
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            str(out_path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    list_file.unlink(missing_ok=True)
