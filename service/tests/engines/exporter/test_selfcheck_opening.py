"""开场 3 秒质检（W4）：narration 模式前窗应有旁白开口——静默黑洞判红带实测；
原声模式开场自有节奏灰不判；量不到灰（宁灰勿假绿纪律同全表）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.exporter import selfcheck


def test_narration_mode_with_sound_passes() -> None:
    row = selfcheck.check_opening(-24.0, "full_narration")
    assert row is not None
    assert row["pass"] is True
    assert row["mean_volume_db"] == pytest.approx(-24.0)


def test_narration_mode_silent_opening_fails() -> None:
    row = selfcheck.check_opening(-62.0, "full_narration")
    assert row is not None
    assert row["pass"] is False
    assert "静默黑洞" in row["reason"]


def test_original_mode_not_judged() -> None:
    """raw_clip 等原声模式开场自有节奏：灰（None）不判。"""
    assert selfcheck.check_opening(-62.0, "raw_clip") is None
    assert selfcheck.check_opening(-24.0, "raw_clip") is None


def test_unmeasurable_reads_none() -> None:
    assert selfcheck.check_opening(None, "full_narration") is None


def test_measure_opening_audio_real_ffmpeg(
    sample_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真 ffmpeg 小样本：量得到给数值（sample_video 带音轨）。"""
    value = selfcheck.measure_opening_audio(sample_video)
    assert value is not None and value > -70.0
    import re

    monkeypatch.setattr(
        selfcheck, "_MEAN_VOLUME_RE", re.compile(r"nomatch:\s*(-?\d+)")
    )
    # 正则不命中=量不到 → None（诚实灰）
    assert selfcheck.measure_opening_audio(sample_video) is None
