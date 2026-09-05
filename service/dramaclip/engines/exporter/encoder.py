"""导出编码器：滤镜链编排与两阶段执行（原案 7.1）。

Phase A 逐段：精确切割 → 竖屏 1080x1920 裁切 → 消重（微缩放/eq/微变速）
        → 遮罩（非纯原片模式）→ 段级混音（narration 段旁白+原声压低）→ 重编码。
Phase B 拼接：concat demuxer（-c copy）+ `-map_metadata -1` 指纹擦除。
进度：Phase A 按段数、Phase B 占 10%。
"""

from __future__ import annotations

import random
import subprocess  # noqa: S404 - 参数为受控列表
import threading
from collections.abc import Callable
from pathlib import Path

from dramaclip.engines.dedup import params as dedup_params
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle.mask import drawbox_filter
from dramaclip.infra.ffmpeg import runner
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

OutWidth = 1080
OutHeight = 1920


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
) -> list[str]:
    """构建单段切割命令（Phase A）。audio: original | narration | ducked。"""
    dedup = dedup_params.generate(rng)
    speed = dedup.speed_factor
    scaled_w = int(OutWidth * dedup.scale_factor) // 2 * 2
    scaled_h = int(OutHeight * dedup.scale_factor) // 2 * 2

    filters = [
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase",
        f"crop={scaled_w}:{scaled_h}",
        f"eq=contrast={dedup.contrast}:brightness={dedup.brightness}",
        f"scale={OutWidth}:{OutHeight}",
        f"setpts=PTS/{speed}",
    ]
    box = drawbox_filter(mask)
    if box:
        filters.append(box)
    if transition == "fade":
        filters.append("fade=t=in:st=0:d=0.25")

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
    if audio == "narration" and tts_audio:
        # 旁白段：TTS 主音 + 原声压低 20%（原案 6.4 混音规则）
        args += ["-i", tts_audio]
        args += [
            "-filter_complex",
            f"[0:v]{','.join(filters)}[v];"
            f"[0:a]volume=0.2,atempo={speed}[bg];[1:a]atempo={speed}[tts];"
            "[bg][tts]amix=inputs=2:duration=first[a]",
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
        "-map_metadata",
        "-1",
        out_path,
    ]
    return args


def export_plan(
    plan: PlanData,
    episode_paths: dict[str, str],
    out_path: Path,
    work_dir: Path,
    *,
    tts_audio_by_segment: dict[int, Path] | None = None,
    mask: bool = True,
    cancel: threading.Event | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> Path:
    """执行两阶段导出，返回成片路径。"""
    segments = plan.timeline
    if not segments:
        raise ValueError("编排时间轴为空")
    work_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random()

    total = len(segments)
    segment_files: list[Path] = []
    for index, segment in enumerate(segments):
        if cancel is not None and cancel.is_set():
            raise runner.FfmpegError("已取消", cancelled=True)
        source = episode_paths.get(segment.episode_id)
        if source is None or not Path(source).is_file():
            raise EpisodeSourceMissing(f"第 {segment.episode_id} 集源文件缺失")
        seg_out = work_dir / f"seg_{index:03d}.mp4"
        tts_audio = None
        if tts_audio_by_segment and index in tts_audio_by_segment:
            tts_audio = str(tts_audio_by_segment[index])
        args = cut_segment_args(
            source,
            str(seg_out),
            start=segment.start,
            end=segment.end,
            audio=segment.audio,
            mask=mask,
            tts_audio=tts_audio,
            rng=rng,
            transition=segment.transition,
        )
        runner.run(args, timeout_s=600)
        segment_files.append(seg_out)
        if on_progress is not None:
            on_progress((index + 1) / total * 90, f"切割 {index + 1}/{total}")

    if cancel is not None and cancel.is_set():
        raise runner.FfmpegError("已取消", cancelled=True)

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
