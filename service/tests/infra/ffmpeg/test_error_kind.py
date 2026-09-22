"""A4-3 runner 错误分类：stderr 关键词 → FfmpegError.kind（供 encoder 回退决策）。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from dramaclip.infra.ffmpeg import runner


@pytest.mark.parametrize(
    ("stderr", "kind"),
    [
        ("Unknown encoder 'h264_nvenc'", "codec"),
        ("Unrecognized option 'cq'.", "codec"),
        ("encoder not found", "codec"),
        ("src.mp4: No such file or directory", "io"),
        ("src.mp4: Invalid data found when processing input", "io"),
        ("Permission denied", "io"),
        ("Invalid argument", "invalid"),
        ("moov atom not found", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_error(stderr: str, kind: str) -> None:
    assert runner._classify_error(stderr) == kind


def test_ffmpeg_error_carries_kind_and_default() -> None:
    assert runner.FfmpegError("boom").kind == "unknown"
    err = runner.FfmpegError("boom", returncode=1, kind="codec")
    assert err.kind == "codec" and err.returncode == 1 and not err.cancelled


def test_real_run_missing_file_classified_io(tmp_path: Path) -> None:
    """真 ffmpeg：输入缺失的失败必须被分类成 io（encoder 据此不回退）。"""
    with pytest.raises(runner.FfmpegError) as excinfo:
        runner.run(["-i", str(tmp_path / "missing.mp4"), "-f", "null", "-"])
    assert excinfo.value.kind == "io"


def test_cancelled_error_kind_not_io(tmp_path: Path) -> None:
    """取消路径抛的错 kind 保持 unknown 且 cancelled=True——分类不许吞掉取消语义。"""
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(runner.FfmpegError) as excinfo:
        runner.run(["-version"], cancel=cancel)
    assert excinfo.value.cancelled
