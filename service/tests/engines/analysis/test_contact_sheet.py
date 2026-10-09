"""infra/analysis.contact_sheet：参数纯函数 + 真实 ffmpeg 拼图执行。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis import contact_sheet
from dramaclip.infra.ffmpeg import runner


def test_contact_sheet_args_deterministic() -> None:
    args = contact_sheet.contact_sheet_args("v.mp4", "sheet.png", duration_s=68.0)
    assert args == [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        "v.mp4",
        "-vf",
        f"fps={16 / 68.0:.6f},scale=320:-2,tile=4x4",
        "-frames:v",
        "1",
        "sheet.png",
    ]


def test_contact_sheet_args_rejects_bad_duration() -> None:
    with pytest.raises(ValueError, match="集时长非法"):
        contact_sheet.contact_sheet_args("v.mp4", "sheet.png", duration_s=0.0)


def test_build_contact_sheet_produces_png(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "sheets" / "ep01.png"
    progress: list[float] = []
    contact_sheet.build_contact_sheet(
        sample_video,
        out,
        duration_s=3.0,
        on_progress=progress.append,
    )
    assert out.is_file() and out.stat().st_size > 1000
    assert progress and 0.0 <= progress[-1] <= 1.0


def test_build_contact_sheet_missing_output_raises(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.mp4"
    with pytest.raises(runner.FfmpegError):
        contact_sheet.build_contact_sheet(ghost, tmp_path / "x.png", duration_s=3.0)
