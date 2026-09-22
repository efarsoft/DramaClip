"""成片封面截钩子帧（默认 1.5s）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.ffmpeg import cover as cover_engine
from dramaclip.infra.ffmpeg import runner


def test_extract_cover_seeks_hook_frame_first(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], timeout_s: float = 30) -> None:
        del timeout_s
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(runner, "run", fake_run)
    out = tmp_path / "cover.jpg"
    assert cover_engine.extract_cover(tmp_path / "film.mp4", out) is True
    assert calls, "应至少试一次截帧"
    assert "-ss" in calls[0] and "1.5" in calls[0]
