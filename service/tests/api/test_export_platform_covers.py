"""export_covers.generate_platform_covers：画幅重裁命令形状 + 成片回退 + 幂等。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export_covers


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(conn=None, data_dir=tmp_path)


def test_composition_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    row = {"output_path": str(film), "narration_plan_id": "", "project_id": "p1"}
    seen: list[str | None] = []

    def fake_extract(
        video: Path, out: Path, *, seek_s: float = 1.5,
        title: str | None = None, composition_vf: str | None = None,
    ) -> bool:
        seen.append(composition_vf)
        out.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", fake_extract)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert set(result["covers"]) == {"视频号", "小红书", "B站"}, "9:16 平台用基础封面"
    assert "scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440" in seen
    assert "scale=1080:675:force_original_aspect_ratio=increase,crop=1080:675" in seen
    assert "scale=1080:1260:force_original_aspect_ratio=increase,crop=1080:1260" in seen


def test_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    covers_dir = tmp_path / "covers" / "exports"
    covers_dir.mkdir(parents=True)
    (covers_dir / "e1.小红书.jpg").write_bytes(b"old")
    row = {"output_path": str(film), "narration_plan_id": "", "project_id": "p1"}
    calls: list[str] = []

    def fake_extract(video: Path, out: Path, **_kw: object) -> bool:
        calls.append(out.name)
        out.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", fake_extract)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert "e1.小红书.jpg" not in calls, "已存在不重截"
    assert result["covers"]["小红书"].endswith("e1.小红书.jpg")


def test_failure_goes_to_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    row = {
        "output_path": str(tmp_path / "missing.mp4"), "narration_plan_id": "", "project_id": "p1",
    }
    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", lambda *a, **k: False)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert result["covers"] == {}
    assert set(result["skipped"]) == {"视频号", "小红书", "B站"}
