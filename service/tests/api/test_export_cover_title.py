"""封面标题字层接线：render_export/ensure_covers 把方案第一条标题传给 extract_cover。

字层本身的能力（drawtext 形状/折行/降级）在 tests/infra/ffmpeg/test_cover.py 钉死；
这里只钉 API 层的三件事：
- render_export 尾部把 plan 的第一条标题作为 title= 传进 extract_cover；
- plan_row 快照里 titles 为空时回库重读（_ensure_titles 刚生成的新标题也能用上）；
- ensure_covers 补拍历史成片时同样带标题；无标题/无方案时传 None（旧行为）。
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


def _seed(memory_db: sqlite3.Connection, tmp_path: Path, titles: list[str] | None):
    """项目 + 一集 + ready 方案（titles 可预置）+ 导出记录；返回 context/export_id/plan_row。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "封面剧", str(tmp_path))["id"])
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
    return context, export_id, plan_row, plan_data, plan_id


def _stub_pipeline(
    monkeypatch: pytest.MonkeyPatch, cover_calls: list[dict[str, Any]]
) -> None:
    """桩掉 ffmpeg 执行链，记录 extract_cover 收到的 kwargs。"""
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)

    def _fake_concat(_files: list[Path], target: Path) -> None:
        Path(target).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", _fake_concat)
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)

    def _fake_cover(video: Path, out: Path, **kwargs: Any) -> bool:
        cover_calls.append({"video": video, "out": out, **kwargs})
        return True

    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", _fake_cover)
    monkeypatch.setattr(
        export_api.probe,
        "probe",
        lambda _p: probe_mod.MediaInfo(
            duration_s=10.0, width=1080, height=1920, fps=30.0, has_audio=True
        ),
    )


def _render(
    context: SimpleNamespace,
    export_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
) -> None:
    export_api.render_export(
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


def test_render_passes_first_title_to_cover(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """方案带标题：render_export 把第一条标题作为 title= 传给 extract_cover。"""
    context, export_id, plan_row, plan_data, _ = _seed(
        memory_db, tmp_path, ["赘婿归来：第一集 he was dead", "备选标题"]
    )
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    _render(context, export_id, plan_row, plan_data)
    assert len(calls) == 1
    assert calls[0]["title"] == "赘婿归来：第一集 he was dead"


def test_render_rereads_titles_when_snapshot_is_stale(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """plan_row 快照 titles 为空但库里已有（_ensure_titles 刚生成）：回库重读拿到标题。"""
    context, export_id, plan_row, plan_data, plan_id = _seed(memory_db, tmp_path, None)
    assert not plan_row.get("titles")
    plans_repo.set_titles(memory_db, plan_id, json.dumps(["后生成的标题"], ensure_ascii=False))
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    _render(context, export_id, plan_row, plan_data)
    assert calls[0]["title"] == "后生成的标题"


def test_render_without_titles_passes_none(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """库里也没有标题：title=None，封面退化为无字层截帧（旧行为）。"""
    context, export_id, plan_row, plan_data, _ = _seed(memory_db, tmp_path, None)
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    _render(context, export_id, plan_row, plan_data)
    assert calls[0]["title"] is None


def test_ensure_covers_backfills_with_title(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """ensure_covers 补拍历史成片：按 narration_plan_id 找回方案标题一并烧字层。"""
    context, export_id, _plan_row, _plan_data, _ = _seed(memory_db, tmp_path, ["补拍也要标题"])
    out_path = tmp_path / "film.mp4"
    out_path.write_bytes(b"film")
    exports_repo.mark_completed(memory_db, export_id, str(out_path))
    calls: list[dict[str, Any]] = []
    _stub_pipeline(monkeypatch, calls)
    result = export_api.ensure_covers(context, {"limit": 10})  # type: ignore[arg-type]
    assert result == {"ok": True, "generated": 1}
    assert len(calls) == 1
    assert calls[0]["title"] == "补拍也要标题"
