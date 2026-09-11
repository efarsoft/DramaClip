"""导出编码器：滤镜链编排与两阶段执行（原案 7.1）。

Phase A 逐段：精确切割 → 竖屏 1080x1920 裁切 → 消重（微缩放/eq/微变速）
        → 遮罩（非纯原片模式）→ 段级混音（narration/ducked 段旁白 + 原声压低）→ 重编码。
Phase B 拼接：concat demuxer（-c copy）+ `-map_metadata -1` 指纹擦除。
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
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle.mask import drawbox_filter
from dramaclip.infra import config
from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

# 画幅数值不在这里定义（docs/04 §5.2）：源是 infra.config，settings 默认值读的是同一个常量。
_DEFAULT_OUT_SIZE = (config.EXPORT_WIDTH, config.EXPORT_HEIGHT)


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
        bg_volume = "0.2" if audio == "narration" else "0.12"
        args += ["-i", tts_audio]
        args += [
            "-filter_complex",
            f"[0:v]{','.join(filters)}[v];"
            f"[0:a]volume={bg_volume},atempo={speed}[bg];[1:a]atempo={speed}[tts];"
            "[bg][tts]amix=inputs=2:duration=first:normalize=0[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        args += [
            "-vf",
            ",".join(filters),
            "-af",
            f"atempo={speed}",
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
        # 以首段采样率解读全部包，采样率不一致会把时长/语速翻倍或减半
        "-ar",
        "48000",
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
) -> Path:
    """执行两阶段导出，返回成片路径。

    Phase A：段级并行切割（竖屏 + 消重 + 遮罩 + 字幕烧录 + 混音）；
    Phase B：concat 拼接 + `-map_metadata -1` 元数据擦除。
    段间无依赖，线程池并行（ffmpeg 自身多线程，2 并发已接近 IO/CPU 饱和）。
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
