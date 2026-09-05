"""infra.ffmpeg.probe：真实 ffprobe 探测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.infra.ffmpeg import probe


def test_probe_returns_media_info(sample_video: Path) -> None:
    media = probe.probe(sample_video)
    assert 2.5 < media.duration_s <= 3.5
    assert media.width == 320 and media.height == 240
    assert media.fps == pytest.approx(10.0, abs=0.5)
    assert media.has_audio


def test_probe_rejects_non_media(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-video.mp4"
    bogus.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        probe.probe(bogus)
