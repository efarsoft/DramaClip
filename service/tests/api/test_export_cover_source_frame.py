"""A1：封面从源素材截帧（去烧录字幕）+ 复现成片构图——API 层接线。

字层/构图滤镜串形状在 tests/infra/ffmpeg/ 钉死；这里钉 api/export.py 的四件事：
- render_export 尾部的封面改用 **源素材** 截帧：首段 start+1.5 映射回源文件，
  composition_vf 与 encoder 同语义（等比缩放进画布 + 不足处补黑，不裁不拉）；
- 降级链：源文件不存在/源截帧失败 → 退回成片截帧（现状行为），全程不 raise；
- ensure_covers 补拍历史成片仍从成片截（拿不到源素材与 plan，不新增查询面）；
  封面已存在直接 return（幂等不破）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

# 首段 start=20.0 → 源时间戳 = 20.0 + 1.5 = 21.5
_FIRST_START = 20.0
_SOURCE_SEEK = _FIRST_START + 1.5


def _seed(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    *,
    titles: list[str] | None = None,
    first_start: float = _FIRST_START,
    source_exists: bool = True,
):
    """项目 + 一集源文件 + ready 方案（首段 start 可配）+ 导出记录。"""
    source = tmp_path / "ep1.mp4"
    if source_exists:
        source.write_bytes(b"real-source-bytes")
    project_id = str(projects_repo.create(memory_db, "源帧剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(
                episode_id=episode_id, start=first_start, end=first_start + 10.0, audio="original"
            )
        ],
    )
    plans_repo.create(
        memory_db, project_id, "raw_clip", [episode_id], plan_data.model_dump(), status="ready"
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    if titles:
        plans_repo.set_titles(memory_db, plan_id, json.dumps(titles, ensure_ascii=False))
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    sent: list[dict[str, Any]] = []
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(sent.append),
        sent=sent,
    )
    return context, export_id, plan_row, plan_data, source


def _stub_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    cover_calls: list[dict[str, Any]],
    *,
    cover_result: Any = True,
) -> None:
    """桩掉 ffmpeg 执行链 + probe + extract_cover。

    cover_result: True/False 恒定，或 callable(video)->bool 按输入文件分流。
    """
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)

    def _fake_concat(_files: list[Path], target: Path) -> None:
        Path(target).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", _fake_concat)
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)

    def _fake_cover(video: Path, out: Path, **kwargs: Any) -> bool:
        cover_calls.append({"video": Path(video), "out": Path(out), **kwargs})
        if callable(cover_result):
            decided: bool = bool(cover_result(Path(video)))
            return decided
        return bool(cover_result)

    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", _fake_cover)
    monkeypatch.setattr(
        export_api.probe,
        "probe",
        lambda _p: probe_mod.MediaInfo(
            duration_s=10.0, width=1080, height=1920, fps=30.0, has_audio=True
        ),
    )


def _render(
    context: SimpleNamespace, export_id: str, plan_row: dict[str, Any], plan_data: PlanData
) -> Path:
    return export_api.render_export(
        context,  # type: ignore[arg-type]
        export_api.ExportRun(
            export_id=export_id,
            project_id=str(plan_row["project_id"]),
            plan_row=plan_row,
            plan_data=plan_data,
            cancel_event=threading.Event(),
        ),
        report=lambda _p, _m: None,
    )


def _expected_composition() -> str:
    return (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    )


# --- render_export：源截帧接线 ------------------------------------------------


def test_render_cover_grabs_from_source_with_composition(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """封面从源素材截：seek=首段 start+1.5，构图链与 encoder 同语义（适配+补黑）。"""
    context, export_id, plan_row, plan_data, source = _seed(
        memory_db, tmp_path, titles=["源帧标题"]
    )
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    out_path = _render(context, export_id, plan_row, plan_data)

    assert len(calls) == 1
    call = calls[0]
    assert call["video"] == source  # 源素材，不是成片
    assert call["video"] != out_path
    assert call["seek_s"] == pytest.approx(_SOURCE_SEEK)
    assert call["title"] == "源帧标题"  # 字层行为零改动
    assert call["composition_vf"] == _expected_composition()
    assert "crop=" not in call["composition_vf"], "不裁不拉（16:9 就是 16:9）"
    assert "ass" not in call["composition_vf"]
    # set_cover 落库
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["cover_path"]


def test_render_cover_source_missing_falls_back_to_film(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """源文件不存在 → 退回现状（成片截帧），封面带字幕仍比没封面强。

    注：render_export 全程走不到这个分支（encoder 会先抛 EpisodeSourceMissing），
    真实触发面是渲染后、截帧前源文件被挪走/删除的竞态，故直接钉 _extract_cover。
    """
    context, export_id, _plan_row, plan_data, _source = _seed(
        memory_db, tmp_path, source_exists=False
    )
    film = tmp_path / "film.mp4"
    film.write_bytes(b"film")
    episode_paths = {seg.episode_id: str(tmp_path / "ep1.mp4") for seg in plan_data.timeline}
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    export_api._extract_cover(
        context,  # type: ignore[arg-type]
        export_id,
        film,
        title=None,
        plan_data=plan_data,
        episode_paths=episode_paths,
        out_size=(1080, 1920),
    )
    assert len(calls) == 1
    assert calls[0]["video"] == film  # 成片
    assert "seek_s" not in calls[0] and "composition_vf" not in calls[0]
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["cover_path"]


def test_render_cover_source_grab_failure_falls_back_to_film(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """源截帧失败（extract_cover 对源返回 False）→ 第二次从成片截，成功仍落库。"""
    context, export_id, plan_row, plan_data, source = _seed(memory_db, tmp_path)
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls, cover_result=lambda video: video != source)
    out_path = _render(context, export_id, plan_row, plan_data)
    assert [c["video"] for c in calls] == [source, out_path]
    assert "composition_vf" not in calls[1]  # 成片回退不带构图链（成片已是该构图）
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["cover_path"]


def test_render_cover_all_fail_never_raises(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """源与成片都截不出 → 导出不炸、封面不落库（占位图兜底是 UI 层的事）。"""
    context, export_id, plan_row, plan_data, _source = _seed(memory_db, tmp_path)
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls, cover_result=False)
    out_path = _render(context, export_id, plan_row, plan_data)
    assert out_path.is_file()
    assert len(calls) == 2  # 源 + 成片各试一轮
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and not row["cover_path"]


def test_cover_idempotent_when_file_exists(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """封面文件已存在 → 直接 return，一次 extract_cover 都不调（幂等不破）。"""
    context, export_id, plan_row, plan_data, _source = _seed(memory_db, tmp_path)
    covers_dir = tmp_path / "covers" / "exports"
    covers_dir.mkdir(parents=True)
    (covers_dir / f"{export_id}.jpg").write_bytes(b"already-here")
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    _render(context, export_id, plan_row, plan_data)
    assert calls == []


# --- _cover_source_frame 单元：降级判据 ---------------------------------------


def test_source_frame_none_when_timeline_empty(tmp_path: Path) -> None:
    plan = PlanData(mode="raw_clip", timeline=[])
    assert export_api._cover_source_frame(plan, {}, (1080, 1920)) is None


def test_source_frame_none_when_episode_unmapped(tmp_path: Path) -> None:
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep-x", start=0.0, end=5.0, audio="original")],
    )
    assert export_api._cover_source_frame(plan, {"other": str(tmp_path)}, (1080, 1920)) is None


def test_source_frame_none_when_source_file_gone(tmp_path: Path) -> None:
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep-1", start=3.0, end=9.0, audio="original")],
    )
    missing = tmp_path / "gone.mp4"
    assert (
        export_api._cover_source_frame(plan, {"ep-1": str(missing)}, (1080, 1920)) is None
    )


def test_source_frame_maps_first_segment(tmp_path: Path) -> None:
    """首段 start=3.0 → 源时间戳 4.5；构图链与 encoder 同语义（适配+补黑）。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep-1", start=3.0, end=9.0, audio="original"),
            TimelineSegment(episode_id="ep-1", start=30.0, end=40.0, audio="original"),
        ],
    )
    frame = export_api._cover_source_frame(plan, {"ep-1": str(source)}, (1080, 1920))
    assert frame is not None
    frame_path, seek_s, composition = frame
    assert frame_path == source
    assert seek_s == pytest.approx(4.5)
    assert composition == _expected_composition()


# --- ensure_covers：补拍历史成片保持现状（从成片截） ---------------------------


def test_ensure_covers_still_grabs_from_film(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """ensure_covers 拿不到源素材与 plan → 从成片截，不带 seek_s/composition_vf。"""
    context, export_id, _plan_row, _plan_data, _source = _seed(memory_db, tmp_path, titles=["补拍"])
    film = tmp_path / "film.mp4"
    film.write_bytes(b"film")
    exports_repo.mark_completed(memory_db, export_id, str(film))
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    result = export_api.ensure_covers(context, {"limit": 10})  # type: ignore[arg-type]
    assert result == {"ok": True, "generated": 1}
    assert len(calls) == 1
    assert calls[0]["video"] == film
    assert calls[0]["title"] == "补拍"
    assert "seek_s" not in calls[0] and "composition_vf" not in calls[0]
