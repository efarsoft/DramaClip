"""infra.ffmpeg.runner：真实 ffmpeg 执行（进度/超时/取消）。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from dramaclip.infra.ffmpeg import runner


def test_parse_out_time_variants() -> None:
    assert runner._parse_out_time("out_time_us=1500000\n") == pytest.approx(1.5)
    # ffmpeg 的 out_time_ms 实际是微秒（上游历史怪癖）
    assert runner._parse_out_time("out_time_ms=1500000\n") == pytest.approx(1.5)
    assert runner._parse_out_time("out_time=00:00:12.500\n") == pytest.approx(12.5)
    assert runner._parse_out_time("frame=42\n") is None
    assert runner._parse_out_time("out_time_us=N/A\n") is None


def test_extract_audio_produces_wav(sample_video: Path, tmp_path: Path) -> None:
    wav = tmp_path / "out.wav"
    runner.run(runner.extract_audio_args(str(sample_video), str(wav)))
    assert wav.is_file() and wav.stat().st_size > 1000


def test_progress_callback_receives_fraction(sample_video: Path, tmp_path: Path) -> None:
    wav = tmp_path / "progress.wav"
    seen: list[float] = []
    runner.run(
        runner.extract_audio_args(str(sample_video), str(wav)),
        total_duration_s=3.0,
        on_progress=seen.append,
    )
    assert seen and 0.0 <= seen[-1] <= 1.0


def test_nonzero_exit_raises(tmp_path: Path) -> None:
    with pytest.raises(runner.FfmpegError):
        runner.run(["-i", str(tmp_path / "missing.mp4"), "-f", "null", "-"])


def test_cancel_kills_process(sample_video: Path, tmp_path: Path) -> None:
    cancel = threading.Event()
    threading.Timer(0.05, cancel.set).start()
    with pytest.raises(runner.FfmpegError) as excinfo:
        runner.run(
            [
                "-y",
                "-i",
                str(sample_video),
                "-vf",
                "scale=1920:1080",
                "-c:v",
                "libx264",
                "-preset",
                "veryslow",
                "-f",
                "null",
                "-",
            ],
            cancel=cancel,
        )
    assert excinfo.value.cancelled
