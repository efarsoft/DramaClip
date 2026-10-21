"""导出回执落库：export_jobs.compute 与 jobs.compute 同写，界面读哪张表都一致。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import compute
from dramaclip.infra.ffmpeg import probe as probe_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier


def _seed(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> tuple[SimpleNamespace, str, dict[str, Any], PlanData]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "回执剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 10.0}],
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
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache",
        settings={"export.encoder": "libx264"},
        notifier=Notifier(lambda _m: None),
    )
    return context, export_id, plan_row, plan_data


def test_render_export_writes_the_receipt_to_both_tables(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    job_writes: list[tuple[str, list[dict[str, Any]]]] = []

    class _Jobs:
        def set_compute(self, job_id: str, reports: list[dict[str, Any]]) -> None:
            job_writes.append((job_id, reports))

    context.job_store = _Jobs()
    codec_calls: list[tuple[str, str]] = []

    def _no_probe() -> str | None:
        raise AssertionError("export.encoder=libx264 不得触发硬编探测")

    monkeypatch.setattr(encoder, "pick_hw_encoder", _no_probe)

    def _fake_plan(*args: Any, **kwargs: Any) -> Path:
        codec_calls.append((kwargs["video_codec"], kwargs["encoder_requested"]))
        kwargs["compute_sink"](
            compute.ComputeReport(
                component="video.encode",
                requested="auto",
                resolved="h264_nvenc",
                actual="h264_nvenc",
            )
        )
        out_path = Path(args[2])
        out_path.write_bytes(b"film")
        return out_path

    monkeypatch.setattr(encoder, "export_plan", _fake_plan)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)
    monkeypatch.setattr(
        export_api.probe,
        "probe",
        lambda _path: probe_mod.MediaInfo(
            duration_s=10.0, width=1080, height=1920, fps=30.0, has_audio=True
        ),
    )

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
        job_id="job-1",
    )

    expected = [
        {
            "component": "video.encode",
            "requested": "auto",
            "resolved": "h264_nvenc",
            "actual": "h264_nvenc",
            "fallback": False,
            "reason": "",
            "device": "h264_nvenc",
        }
    ]
    row = exports_repo.get(memory_db, export_id)
    assert row is not None
    assert row["compute"] == expected
    assert job_writes == [("job-1", expected)]
    assert codec_calls == [("libx264", "libx264")]


def test_render_export_ledgers_the_voice_receipt_before_the_encode_one(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """渲染前的音色清洗回执排在导出账首位：界面读一条数组就能看到全链算力。"""
    context, export_id, plan_row, plan_data = _seed(memory_db, tmp_path)
    context.job_store = SimpleNamespace(set_compute=lambda *_a: None)

    def _fake_plan(*args: Any, **kwargs: Any) -> Path:
        kwargs["compute_sink"](
            compute.ComputeReport(
                component="video.encode",
                requested="auto",
                resolved="libx264",
                actual="libx264",
            )
        )
        out_path = Path(args[2])
        out_path.write_bytes(b"film")
        return out_path

    monkeypatch.setattr(encoder, "export_plan", _fake_plan)
    monkeypatch.setattr(export_api.ffmpeg_cover, "extract_cover", lambda *_a, **_k: False)
    monkeypatch.setattr(
        export_api.probe,
        "probe",
        lambda _path: probe_mod.MediaInfo(
            duration_s=10.0, width=1080, height=1920, fps=30.0, has_audio=True
        ),
    )
    voice_receipt = {
        "component": "tts.separation",
        "requested": "auto",
        "resolved": "cpu",
        "actual": "cpu",
        "fallback": False,
        "reason": "",
        "device": "cpu",
    }

    export_api.render_export(
        context,  # type: ignore[arg-type]
        export_api.ExportRun(
            export_id=export_id,
            project_id=str(plan_row["project_id"]),
            plan_row=plan_row,
            plan_data=plan_data,
            cancel_event=threading.Event(),
            voice_reports=[voice_receipt],
        ),
        report=lambda _p, _m: None,
        job_id="job-2",
    )

    row = exports_repo.get(memory_db, export_id)
    assert row is not None
    components = [item["component"] for item in row["compute"]]
    assert components == ["tts.separation", "video.encode"]
    assert row["compute"][0] == voice_receipt
