"""分析任务的算力账：转写与视觉轨各记一条，谁没有运行证据谁就不出现。

直连 `_analyze_one`（不起作业线程池），第一层/融合/语义全部打桩，只留真实的
任务行读写——验的是「回执怎么落进 jobs.compute」，不是分析本身。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import analysis_job
from dramaclip.engines.analysis import pipeline
from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, EpisodeRawAnalysis
from dramaclip.infra import jobs
from dramaclip.infra.compute import ComputeReport
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier

_ASR = ComputeReport(component="asr.funasr", requested="auto", resolved="cuda", actual="cuda")
_VISION = ComputeReport(
    component="vision.llama", requested="auto", resolved="cuda", actual="cuda",
    device="Quadro M4000",
)


def _seg() -> AsrSegment:
    return AsrSegment(start=0.0, end=1.0, text="台词")


@pytest.fixture
def env(memory_db: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    project = projects_repo.create(memory_db, "p", str(tmp_path))
    project_id = str(project["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [{"episode_number": 1, "source_path": str(tmp_path / "1.mp4"), "duration": 60.0}],
    )
    context = SimpleNamespace(
        conn=memory_db,
        settings={"asr.language": "zh"},
        notifier=Notifier(lambda _m: None),
        job_store=jobs.JobStore(memory_db),
        analysis_runtime=SimpleNamespace(
            transcriber=lambda: SimpleNamespace(compute=lambda: _ASR)
        ),
        work_dir=tmp_path / "work",
        data_dir=tmp_path,
        cancel_events={},
    )
    monkeypatch.setattr(
        pipeline,
        "analyze_episode",
        lambda **_kw: EpisodeRawAnalysis(asr_segments=[_seg()], audio=AudioFeatures()),
    )
    monkeypatch.setattr(
        analysis_job, "_fuse_ocr", lambda *_a, **_k: ([_seg()], None, None, None)
    )
    monkeypatch.setattr(analysis_job, "_contact_sheet", lambda *_a: None)
    monkeypatch.setattr(analysis_job, "_describe_frames", lambda *_a, **_k: [])
    monkeypatch.setattr(
        analysis_api.semantic_pipeline,
        "enhance",
        lambda _raw, _settings, **_kw: SimpleNamespace(
            conflict_scores=[], highlights=[], genre=""
        ),
    )
    return SimpleNamespace(
        context=context,
        episode=episodes_repo.list_by_project(memory_db, project_id)[0],
        job_id=context.job_store.create("analysis", ref_id=project_id),
    )


def _run(env: SimpleNamespace, vision: Any) -> list[dict[str, Any]] | None:
    analysis_api._analyze_one(  # noqa: SLF001 - 直连内部编排，不起作业线程
        env.context, env.job_id, env.episode, 0, 1, "zh", threading.Event(), vision=vision
    )
    job = env.context.job_store.get(env.job_id)
    assert job is not None
    compute: list[dict[str, Any]] | None = job["compute"]
    return compute


def test_vision_receipt_joins_the_asr_receipt(env: SimpleNamespace) -> None:
    """视觉会话拉起过：任务行两条回执，转写在前、画面理解在后。"""
    vision = SimpleNamespace(model_id="qwen3-vl-4b", compute=lambda: _VISION)
    assert _run(env, vision) == [_ASR.to_dict(), _VISION.to_dict()]


def test_vision_without_evidence_leaves_the_asr_receipt_alone(env: SimpleNamespace) -> None:
    """会话开了但没拉起过（compute() 为 None）：不许凭空多出一条视觉回执。"""
    vision = SimpleNamespace(model_id="qwen3-vl-4b", compute=lambda: None)
    assert _run(env, vision) == [_ASR.to_dict()]


def test_no_vision_session_keeps_the_single_receipt(env: SimpleNamespace) -> None:
    assert _run(env, None) == [_ASR.to_dict()]
