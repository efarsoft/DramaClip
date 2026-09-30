"""出片受理的配音预检：有旁白 + 克隆引擎 + 未配参考音色 → 提交时即拦（含指引）。

旧形状：提交成功 → 全片渲染到 TTS 逐段炸「voice 为空」——4 条出片白跑
（2026-09-30 实测）。预检把这类配置问题挡在受理门口。运行环境未装
（IndexTTS venv 缺失）同类晚炸，一并拦。Edge/Kokoro/auto 不需要参考
音色，不在拦截范围。
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from tests.conftest import register_job_executor


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[str, str, str]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 60.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plan_data = PlanData(
        mode="dialogue_narration",
        timeline=[
            TimelineSegment(
                episode_id=episode_id,
                start=0.0,
                end=5.0,
                audio="narration",
                narration_id="n1",
            )
        ],
        narration_texts=[
            {"id": "n1", "text": "他花几百万两杀妻——点击左下角，免费观看全集。"}
        ],
    )
    plans_repo.create(
        memory_db,
        project_id,
        "dialogue_narration",
        [episode_id],
        plan_data.model_dump(),
        status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    export_id = str(exports_repo.create(memory_db, project_id, plan_id, "dialogue_narration"))
    return project_id, plan_id, export_id


def _context(
    memory_db: sqlite3.Connection, tmp_path: Path, settings: dict[str, str]
) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings=settings,
        notifier=Notifier(lambda _m: None),
        executor=register_job_executor(ThreadPoolExecutor(max_workers=1)),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )


def _settings(engine: str, voice: str = "") -> dict[str, str]:
    return {
        "tts.engine": engine,
        f"tts.voice.{engine}": voice,
        "export.encoder": "libx264",
    }


def test_submit_rejects_clone_engine_without_voice(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    project_id, plan_id, _ = _seed(memory_db, tmp_path)
    context = _context(memory_db, tmp_path, _settings("indextts2"))

    result = export_api.submit(context, {"plan_ids": [plan_id]})  # type: ignore[arg-type]

    assert result["exports"] == [] and result["rejected"], "未配参考音色必须在受理时拦下"
    reason = result["rejected"][0]["reason"]
    assert "参考音色" in reason and "indextts2" in reason


def test_submit_accepts_clone_engine_with_voice(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, plan_id, _ = _seed(memory_db, tmp_path)
    context = _context(memory_db, tmp_path, _settings("indextts2", voice="D:/ref/voice.wav"))
    monkeypatch.setattr(export_api.encoder, "resolve_canvas", lambda ep, cap: cap)
    monkeypatch.setattr(export_api, "_extract_cover", lambda *a, **k: None)
    # 测试环境的 data_dir 没有 tts-venv：运行时就绪桩为 True（预检只管配置形态）
    import dramaclip.engines.tts.engines.indextts2 as indextts2_mod

    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: True)

    result = export_api.submit(context, {"plan_ids": [plan_id]})  # type: ignore[arg-type]

    assert result["rejected"] == [], "配了参考音色必须放行"
    assert result["exports"], "受理成功的方案要有 export 记录与任务"


def test_submit_accepts_edge_without_voice(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, plan_id, _ = _seed(memory_db, tmp_path)
    context = _context(memory_db, tmp_path, _settings("edge"))
    monkeypatch.setattr(export_api.encoder, "resolve_canvas", lambda ep, cap: cap)
    monkeypatch.setattr(export_api, "_extract_cover", lambda *a, **k: None)

    result = export_api.submit(context, {"plan_ids": [plan_id]})  # type: ignore[arg-type]

    assert result["rejected"] == [], "edge 不需要参考音色"


def test_preflight_error_carries_guidance(tmp_path: Path) -> None:
    plan = PlanData(
        mode="dialogue_narration",
        timeline=[
            TimelineSegment(episode_id="e", start=0.0, end=2.0, audio="narration", narration_id="n")
        ],
        narration_texts=[{"id": "n", "text": "台词"}],
    )
    message = export_api._tts_preflight_error(plan, _settings("cosyvoice"))
    assert message is not None and "cosyvoice" in message and "参考音色" in message
    assert export_api._tts_preflight_error(plan, _settings("edge")) is None
    raw_clip = PlanData(mode="raw_clip", timeline=[])
    assert export_api._tts_preflight_error(raw_clip, _settings("indextts2")) is None
