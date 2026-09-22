"""FFmpeg 进程封装：列表参数（禁字符串拼接）、超时、取消、-progress 进度解析。"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_STDERR_TAIL_LINES = 30


class FfmpegError(RuntimeError):
    """ffmpeg 非零退出/超时/取消。

    ``kind``（A4-3 错误分类）：从 stderr 关键词粗分——
    ``codec``（编码器不可用/参数不识别，换软编重跑有意义）、
    ``io``（输入文件缺失/损坏，回退也没用）、
    ``invalid``（参数非法，回退也没用）、``unknown``（分类不出，按可回退处理）。
    供 encoder 段级回退决策用（tests/infra/ffmpeg/test_error_kind.py 钉住）。
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        cancelled: bool = False,
        kind: str = "unknown",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.cancelled = cancelled
        self.kind = kind


_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("codec", ("unknown encoder", "unrecognized option", "encoder not found")),
    (
        "io",
        ("no such file", "invalid data found", "permission denied",
         "does not contain any stream"),
    ),
    ("invalid", ("invalid argument", "invalid duration", "invalid timestamp")),
)


def _classify_error(stderr_text: str) -> str:
    """stderr 关键词 → 错误分类（顺序敏感：codec 特征词比 invalid 更具体）。"""
    lowered = stderr_text.lower()
    for kind, keywords in _KIND_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return kind
    return "unknown"


@dataclass(frozen=True)
class FfmpegResult:
    returncode: int
    stderr_tail: str
    seconds_processed: float | None


ProgressCallback = Callable[[float], None]


def extract_audio_args(source: str, wav_path: str) -> list[str]:
    """抽 16kHz 单声道 wav（分析管线标准输入）。"""
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        wav_path,
    ]


def run(
    args: list[str],
    *,
    total_duration_s: float | None = None,
    timeout_s: float | None = None,
    cancel: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> FfmpegResult:
    """执行一次 ffmpeg。
    """
    if on_progress is not None and total_duration_s is not None:
        args = ["-progress", "pipe:1", "-nostats", *args]
    if cancel is not None and cancel.is_set():
        raise FfmpegError("ffmpeg 已取消", cancelled=True)
    process = subprocess.Popen(  # noqa: S603 - 参数为受控列表
        [resolve_ffmpeg(), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr_lines: list[str] = []
    watcher: threading.Timer | None = None
    stop_killer = threading.Event()
    killer: threading.Thread | None = None
    try:
        if cancel is not None and cancel.is_set():
            raise FfmpegError("ffmpeg 已取消", cancelled=True)
        threading.Thread(
            target=_drain_stderr, args=(process, stderr_lines), daemon=True
        ).start()
        if timeout_s is not None:
            watcher = threading.Timer(timeout_s, process.kill)
            watcher.start()
        if cancel is not None:
            def _kill_if_cancelled() -> None:
                while process.poll() is None:
                    if cancel.is_set():
                        process.kill()
                        return
                    if stop_killer.wait(0.05):
                        return

            killer = threading.Thread(target=_kill_if_cancelled, daemon=True)
            killer.start()
        if process.stdout is not None:
            for line in process.stdout:
                seconds = _parse_out_time(line)
                if seconds is not None and on_progress is not None and total_duration_s:
                    on_progress(min(seconds / total_duration_s, 1.0))
        returncode = process.wait()
        if cancel is not None and cancel.is_set():
            raise FfmpegError("ffmpeg 已取消", returncode=returncode, cancelled=True)
        if returncode != 0:
            stderr_tail = "".join(stderr_lines[-_STDERR_TAIL_LINES:])
            raise FfmpegError(
                f"ffmpeg 退出码 {returncode}：{stderr_tail}",
                returncode=returncode,
                kind=_classify_error(stderr_tail),
            )
        return FfmpegResult(
            returncode=returncode,
            stderr_tail="".join(stderr_lines[-_STDERR_TAIL_LINES:]),
            seconds_processed=None,
        )
    finally:
        stop_killer.set()
        if watcher is not None:
            watcher.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()


def _drain_stderr(process: subprocess.Popen[str], sink: list[str]) -> None:
    if process.stderr is None:
        return
    for line in process.stderr:
        sink.append(line)


def _parse_out_time(line: str) -> float | None:
    """`out_time_us=…` / `out_time_ms=…` / `out_time=HH:MM:SS.mmm` → 秒。
    """
    for prefix in ("out_time_us=", "out_time_ms="):
        if line.startswith(prefix):
            value = line.split("=", 1)[1].strip()
            return float(value) / 1_000_000 if _is_number(value) else None
    if line.startswith("out_time="):
        value = line.split("=", 1)[1].strip()
        parts = value.split(":")
        if len(parts) == 3 and all(_is_number(part) for part in parts):
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return None


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
