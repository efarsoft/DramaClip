"""export_covers.generate_platform_covers：画幅重裁命令形状 + 成片回退 + 幂等。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export_covers
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


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
    # B站 16:10 推导 675 为奇数：extract_cover 尾部 scale=1080:-2 强制偶数 → 676（F1）
    assert "scale=1080:676:force_original_aspect_ratio=increase,crop=1080:676" in seen
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


def test_dict_titles_burn_text_not_repr(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """真实方案 titles 是 dict（{text, selected}）：字层烧 text 而非 dict repr（F2）。

    保持「取第一条候选」语义（不是取 selected）；只桩 ffmpeg 边界，钉 extract_cover
    收到的 title 实参。
    """
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "标题剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id=episode_id, start=0.0, end=10.0, audio="original")],
    )
    plans_repo.create(
        memory_db, project_id, "raw_clip", [episode_id], plan_data.model_dump(), status="ready"
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    plans_repo.set_titles(
        memory_db,
        plan_id,
        json.dumps(
            [{"text": "第一条候选", "selected": False}, {"text": "当选标题", "selected": True}],
            ensure_ascii=False,
        ),
    )
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    row = {"output_path": str(film), "narration_plan_id": plan_id, "project_id": project_id}
    seen_titles: list[str | None] = []

    def fake_extract(
        video: Path, out: Path, *, seek_s: float = 1.5,
        title: str | None = None, composition_vf: str | None = None,
    ) -> bool:
        seen_titles.append(title)
        out.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", fake_extract)
    context = SimpleNamespace(conn=memory_db, data_dir=tmp_path)
    result = export_covers.generate_platform_covers(context, "e1", row)
    assert result["ok"] is True
    assert seen_titles, "至少一个平台走到截帧"
    assert all(t == "第一条候选" for t in seen_titles), f"烧了 dict repr: {seen_titles}"


def test_extract_raise_goes_to_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """ffmpeg 二进制缺失（runner 裸 Popen 抛 FileNotFoundError）：进 skipped 不 raise（F3）。"""
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    row = {"output_path": str(film), "narration_plan_id": "", "project_id": "p1"}

    def raise_missing(*_a: object, **_k: object) -> bool:
        raise FileNotFoundError("ffmpeg binary not found")

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", raise_missing)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert result["ok"] is True
    assert result["covers"] == {}
    assert set(result["skipped"]) == {"视频号", "小红书", "B站"}


def test_plan_read_failure_never_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """准备阶段库读失败（plans_repo.get 抛错）：逐平台进 skipped，函数永不 raise（F3）。"""
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    row = {"output_path": str(film), "narration_plan_id": "plan-x", "project_id": "p1"}

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(export_covers.plans_repo, "get", boom)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert result["ok"] is True
    assert result["covers"] == {}
    assert set(result["skipped"]) == {"视频号", "小红书", "B站"}
