"""成片装配：段清单验盘→concat 拼接→流签名一致性→时长审计→段偏移实测。

自 encoder.py 拆出（拆分专项）：Phase B（全部段编完后的成片装配）是独立的
后处理层——输入是段文件列表 + 编排元数据（_SegmentArtifact），输出是拼接
好的成片。与 encoder.py 的依赖单向：本模块 import 段类型与常量，encoder
的编排函数（_export_plan_once）import 本模块的装配函数。

关键设计（保持不动，只搬家）：
- **concat 签名守卫**：各段视频/音频流签名一致才走 `-c copy` 流复制；
  不齐（典型：某段硬编失败回退了 libx264）保守整体重编码——流复制混拼
  不一致的流是「导出到 90% 崩」的一条路
- **.part 原子交付**：半成品/编码失败对下载接口不可见
- **时长审计**：成片实测 vs 各段实测和，超阈值抛错（缺段/重复级偏差），
  测不出来只 warn 不伪装通过
- **心跳日志**：长 ffmpeg 每 30s 记已耗时+产物体积（编码中 vs 僵死可分辨）
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess  # noqa: S404 - 参数为受控列表
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from dramaclip.infra.ffmpeg import probe as ffprobe_mod
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg, resolve_ffprobe

if TYPE_CHECKING:
    from dramaclip.engines.exporter.encoder import _SegmentJob

_LOGGER = logging.getLogger(__name__)

# 共享常量与异常的家在本模块——encoder.py 从这里 re-import（单向依赖：
# encoder → film_assembly，film_assembly 不 import encoder 的任何东西，
# 循环 import 从结构上不可能）。


class FilmIntegrityError(Exception):
    """成片完整性违规（缺段/时长超阈）——不出片的硬错误。"""


_COLOR_ARGS = [
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
]
_FALLBACK_CODEC = "libx264"
_SEGMENT_SAMPLE_RATE = 48000


class _SegmentArtifact(NamedTuple):
    """Phase A 交给 Phase B 的一份产物：序号 + 路径 + film map 所需源侧信息。

    序号跟着路径一起走，偏移才不必靠「两处各自排序再指望它们对齐」——清单序＝拼接序。
    episode/audio/safe 窗供 _segment_offsets 产出成片↔源实测对照（avsync/ending
    检查的刻度来源，见 selfcheck）。
    """

    seq: int
    path: Path
    episode_id: str
    audio: str
    safe_start: float
    safe_end: float


def _segment_offsets(manifest: list[_SegmentArtifact]) -> list[dict[str, float | int | str]] | None:
    """各段实测记录＝按拼接序累加**实测**段长 + 源侧实际切点；测不出返回 None。

    成片逐句时间轴只有这一个诚实来源：`timeline[].start/end` 是源片坐标，观众看到的
    是切完拼接后的成片坐标，两者差着 jitter 与保护区外扩。拿计划声明值凑一份等于把
    误差固化成"看起来精确"的假账，所以宁可不给。
    记录含 (seq, film_start, episode_id, audio, source_start, source_end)——
    source_* 是 jitter 后的安全窗实际值：avsync 成片→源映射与 ending 词级出点
    检查都靠它对齐（此前用声明窗映射，多段累积漂移轻松吃掉互相关搜索窗）。
    """
    offsets: list[dict[str, float | int | str]] = []
    cursor = 0.0
    try:
        for item in manifest:
            offsets.append(
                {
                    "seq": item.seq,
                    "film_start": round(cursor, 3),
                    "episode_id": item.episode_id,
                    "audio": item.audio,
                    "source_start": round(item.safe_start, 3),
                    "source_end": round(item.safe_end, 3),
                }
            )
            cursor += ffprobe_mod.probe(item.path).duration_s
    except Exception as exc:  # noqa: BLE001 - 测不出就不交付，别拿半截偏移冒充
        _LOGGER.warning("段偏移测量失败（%s）：本条成片不产出逐句时间轴", str(exc)[:200])
        return None
    return offsets


def _concat_manifest(jobs: list[_SegmentJob]) -> list[_SegmentArtifact]:
    """Phase B 段清单以 **jobs 为准逐段验盘**，不按 `glob("seg_*.mp4")` 收。

    glob 回答的是"目录里恰好有什么"，不是"这次渲染产出了什么"：某段 ffmpeg 退出码 0
    却没落文件（`_finish` 见文件不在就静默不写 sig）、0 字节残留、命名恰好匹配的杂项，
    都会静默改变成片内容——缺一段就是少讲一段剧情。这类偏差改变观众所见，按 §3.3.1
    属禁止级，当场判死。顺带两笔账：清单按 `job.index` 排（词法排序会把 `seg_1000`
    插到 `seg_999` 前面），且本次段集不再受 work_dir 里别的文件影响。
    """
    items: list[_SegmentArtifact] = []
    broken: list[str] = []
    for job in sorted(jobs, key=lambda job: job.index):
        try:
            usable = job.seg_path.stat().st_size > 0
        except OSError:  # 缺盘/目录/权限问题一律按"这块产物不可信"
            usable = False
        if usable:
            items.append(
                _SegmentArtifact(
                    job.index, job.seg_path,
                    episode_id=str(job.inputs.get("episode_id") or ""),
                    audio=str(job.inputs.get("audio") or ""),
                    safe_start=job.safe_start, safe_end=job.safe_end,
                )
            )
        else:
            broken.append(f"第 {job.index + 1} 段（{job.seg_path.name}）")
    if broken:
        raise FilmIntegrityError(
            f"编码报成功的段有 {len(broken)}/{len(jobs)} 段不在盘上或为空文件："
            f"{'、'.join(broken[:5])}——缺段成片不予交付"
        )
    return items


def _concat_list_line(path: Path) -> str:
    r"""concat 清单的一行：单引号串内 ffmpeg 只认 `'\''` 这一种转义写法。

    裸拼 `file '<路径>'` 时，路径里的单引号会提前终结字符串，后半截变成解析垃圾。
    """
    quoted = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{quoted}'\n"


_HEARTBEAT_INTERVAL_S = 30.0


def _staged_path(out_path: Path) -> Path:
    """同目录 .part 暂存名：与最终产物同分区，os.replace 才是原子改名而非跨盘复制。"""
    return out_path.with_name(f"{out_path.stem}.part{out_path.suffix}")


def _run_ffmpeg_with_heartbeat(
    cmd: list[str], *, timeout: float, watch: Path
) -> None:
    """长 ffmpeg 执行带心跳日志：每 30s 记一次已耗时与暂存产物体积——

    「编码中还在长大」与「进程僵死」从此在日志里可分辨（排查不再靠猜）。"""
    import subprocess  # noqa: PLC0415 - 模块顶部已间接依赖；保持函数自包含

    started = time.monotonic()
    proc = subprocess.Popen(  # noqa: S603
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )

    def _beat() -> None:
        while proc.poll() is None:
            time.sleep(_HEARTBEAT_INTERVAL_S)
            if proc.poll() is not None:
                return
            size = watch.stat().st_size if watch.is_file() else 0
            _LOGGER.info(
                "ffmpeg 仍在编码：已 %.0fs，产物 %.1f MB（超时预算 %.0fs）",
                time.monotonic() - started,
                size / 1e6,
                timeout,
            )

    beat = threading.Thread(target=_beat, name="ffmpeg-heartbeat", daemon=True)
    beat.start()
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise subprocess.TimeoutExpired(cmd, timeout) from exc
    if proc.returncode != 0:
        # 异常类型与旧 subprocess.run 语义一致：调用方按类型处理，不因心跳封装而变
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)


def _concat(segment_files: list[Path], out_path: Path) -> None:
    """Phase B：concat demuxer 拼接 + 元数据擦除。

    A4-2 签名守卫：各段视频流签名（codec_name/profile/level/pix_fmt/宽高/SAR）一致才走
    `-c copy` 流复制；不齐（典型：某段硬编失败回退了 libx264）或签名探测自身失败时
    保守整体重编码 concat——流复制混拼不一致的流是「导出到 90% 崩」的一条路。
    拼完做时长审计（实测 vs 各段实测和，超阈值抛错不出片；测不出只 warn 留痕）。
    """
    if len(segment_files) == 1:
        tmp = _staged_path(out_path)
        shutil.copyfile(segment_files[0], tmp)
        _audit_film_duration(tmp, segment_files)
        os.replace(tmp, out_path)
        return
    signatures = [_video_signature(segment) for segment in segment_files]
    uniform = signatures[0] is not None and all(sig == signatures[0] for sig in signatures)
    audio_signatures = [_audio_signature(segment) for segment in segment_files]
    audio_uniform = audio_signatures[0] is not None and all(
        sig == audio_signatures[0] for sig in audio_signatures
    )
    if not uniform:
        _LOGGER.warning(
            "段视频流签名不齐或不可测（%s）：concat 整体重编码而非流复制"
            "（音频%s）",
            signatures,
            "流复制（一次 AAC）" if audio_uniform else "重编码",
        )
    # 清单名跟着 out_path 走而非固定名：out_path 落在 `data/outputs/<project>/`，同项目的
    # K 条方案并发导出时固定 `concat.txt` 会被后写者顶掉——A 拼出 B 的段。
    list_file = out_path.with_name(f"{out_path.stem}.concat.txt")
    lines = "".join(_concat_list_line(segment) for segment in segment_files)
    codec_args = (
        ["-c", "copy"]
        if uniform
        else [
            "-c:v", _FALLBACK_CODEC, "-preset", "medium", "-crf", "20",
            *_COLOR_ARGS,
            # 一次 AAC：切段时音频已统一编码，非一致分支只重编视频；
            # 音频签名不齐才降级重编（AAC 逐段重编会累积编码延迟）
            *(
                ("-c:a", "copy")
                if audio_uniform
                else ("-c:a", "aac", "-b:a", "128k", "-ar", str(_SEGMENT_SAMPLE_RATE))
            ),
        ]
    )
    tmp = _staged_path(out_path)
    try:
        list_file.write_text(lines, encoding="utf-8")
        _run_ffmpeg_with_heartbeat(
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
                str(tmp),
            ],
            # 重编码 concat 是整片再编一遍，预算要比流复制宽（300s 对长片不够）
            timeout=300 if uniform else 3600,
            watch=tmp,
        )
        _audit_film_duration(tmp, segment_files)
        # 原子交付：半成品/编码失败的文件对下载接口不可见（.part 永不冒充成片）
        os.replace(tmp, out_path)
    finally:
        # 超时/check=True 抛错时也要收走：留在成片目录里的是一个指向已失效段的垃圾文件
        list_file.unlink(missing_ok=True)
        if not out_path.is_file():
            Path(tmp).unlink(missing_ok=True)  # 失败路径收走 .part，旧成片原样保留


def _audio_signature(path: Path) -> tuple[str, int, int] | None:
    """段音频流签名（codec/采样率/声道）：全部段 AAC 已在切段时统一编码
    （48k/立体声），concat 非一致分支只需重编视频——音频流复制即「AAC 只编
    一次」，逐段 AAC 重编会累积编码延迟（真机口径：音频时长逐段双倍的事故
    与此同源）。签名不齐或测不出 → 保守重编音频。"""
    try:
        result = subprocess.run(  # noqa: S603
            [
                resolve_ffprobe(),
                "-v", "error",
                "-print_format", "json",
                "-select_streams", "a:0",
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
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        return (
            str(stream["codec_name"]),
            int(stream["sample_rate"]),
            int(stream["channels"]),
        )
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return None


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
            _LOGGER.warning(
                "视频流签名探测失败（ffprobe 返回 %d：%s）：拼片按几何不齐处理，"
                "走全量重编码而非流复制",
                result.returncode,
                (result.stderr or "")[:120],
            )
            return None
        streams = json.loads(result.stdout).get("streams") or []
        if not streams:
            _LOGGER.warning(
                "视频流签名探测失败（ffprobe 无视频流输出）：拼片按几何不齐处理，"
                "走全量重编码而非流复制"
            )
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
    except Exception as exc:  # noqa: BLE001 - 签名探测失败按不齐处理，绝不挡已成功的段编码
        _LOGGER.warning(
            "视频流签名探测失败（%s）：拼片按几何不齐处理，走全量重编码而非流复制",
            str(exc)[:120],
        )
        return None


# 时长容差的**唯一**落点：三处判据（本层段和闸=超阈值抛错、api 层渲染后 warn、
# selfcheck 成品库红绿）全部引用这两个名字——改一处即三处同改，界面绿/日志 warn
# 的分叉没有第二种写法。容得下 dedup 微变速（±0.4%）、切点抖动与 AAC/concat
# 的毫秒级出入，只抓缺段/重复级真偏差。
AUDIT_DURATION_REL_TOLERANCE = 0.08
AUDIT_DURATION_ABS_TOLERANCE_S = 3.0


def _audit_film_duration(out_path: Path, segment_files: list[Path]) -> None:
    """成片实测时长 vs **各段实测和**：超阈值即抛，量不出来只留痕、绝不伪装成通过。

    分母是"段产物自己加起来多少"，与 jitter、台词保护区外扩无关，超线只能是缺段/
    重复段/拼错——那是观众看得见的差异，按 §3.3.1 与响度同判据改成抛错。
    **别和 `api/export._audit_duration` 混为一谈**：那条量的是"成片 vs 计划声明"，
    分母里合法混着抖动余量，仍是 warn。
    测量自身失败不在本片内容里造假，也不拿它挡门——记 warn，缺段那一半已由
    `_concat_manifest` 的清单对账兜住。
    """
    try:
        segments_total_s = sum(
            ffprobe_mod.probe(segment).duration_s for segment in segment_files
        )
        actual = ffprobe_mod.probe(out_path).duration_s
    except Exception as exc:  # noqa: BLE001 - 测不出 ≠ 通过，但也不许拿它挡已拼好的片
        _LOGGER.warning(
            "成片时长审计未能测量（%s）：本条成片没有时长核对", str(exc)[:200],
        )
        return
    if segments_total_s <= 0:
        _LOGGER.warning(
            "成片时长审计未能测量（各段实测和 %.1fs）：本条成片没有时长核对", segments_total_s
        )
        return
    diff = actual - segments_total_s
    tolerance = max(
        segments_total_s * AUDIT_DURATION_REL_TOLERANCE, AUDIT_DURATION_ABS_TOLERANCE_S
    )
    if abs(diff) > tolerance:
        raise FilmIntegrityError(
            f"成片时长审计：实测 {actual:.1f}s vs 各段实测和 {segments_total_s:.1f}s"
            f"（差 {diff:+.1f}s，超出阈值 ±{tolerance:.1f}s）——疑似缺段/重复段，不出片"
        )
