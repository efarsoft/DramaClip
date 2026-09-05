"""api.analysis：job 模式全生命周期（fake 引擎，真实落库与进度）。"""

from __future__ import annotations

import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import project as project_api
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.infra import jobs
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


class FakeTranscriber:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s

    @property
    def name(self) -> str:
        return "fake"

    def transcribe(self, wav_path: Path, language: str = "zh") -> list[AsrSegment]:
        if self.delay_s:
            time.sleep(self.delay_s)
        return [AsrSegment(start=0.2, end=1.0, text="测试台词")]


class Harness:
    def __init__(
        self, conn: sqlite3.Connection, work_dir: Path, transcriber: FakeTranscriber
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=2)
        from types import SimpleNamespace

        prescreen_repo_stub = SimpleNamespace(get=lambda _episode_id: None)
        self.context = SimpleNamespace(
            conn=conn,
            prescreen_repo=prescreen_repo_stub,
            settings={"asr.language": "zh"},
            notifier=Notifier(self.sent.append),
            executor=self.executor,
            job_store=jobs.JobStore(conn),
            analysis_runtime=SimpleNamespace(transcriber=lambda: transcriber),
            work_dir=work_dir,
            cancel_events={},
        )
        self.router = Router()
        analysis_api.register(self.router, self.context)  # type: ignore[arg-type]
        project_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result

    def wait_done(self, job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.rpc("analysis.status", {"job_id": job_id})
            if status["status"] in ("completed", "failed", "cancelled"):
                return status
            time.sleep(0.05)
        raise AssertionError("任务超时未完成")

    def close(self) -> None:
        self.executor.shutdown(wait=True)


@pytest.fixture
def harness(memory_db: sqlite3.Connection, tmp_path: Path) -> Harness:
    instance = Harness(memory_db, tmp_path / "work", FakeTranscriber())
    yield instance
    instance.close()


def _make_project(harness: Harness, tmp_path: Path, sample_video: Path, copies: int = 2) -> str:
    for number in range(1, copies + 1):
        shutil.copy(sample_video, tmp_path / f"ep{number}.mp4")
    project = harness.rpc("project.create", {"name": "p", "source_path": str(tmp_path)})
    harness.rpc("project.scan_episodes", {"project_id": project["id"]})
    return str(project["id"])


def test_start_completes_and_persists(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _make_project(harness, tmp_path, sample_video)
    result = harness.rpc("analysis.start", {"project_id": project_id})
    status = harness.wait_done(str(result["job_id"]))

    assert status["status"] == "completed"
    assert status["progress"] == 100.0
    results = harness.rpc("analysis.results", {"project_id": project_id})
    assert [ep["status"] for ep in results["episodes"]] == ["done", "done"]
    assert all(ep["asr_segment_count"] == 1 for ep in results["episodes"])
    episode_id = results["episodes"][0]["episode_id"]
    assert results["asr_segments"][episode_id][0]["text"] == "测试台词"
    progresses = [m for m in harness.sent if m["method"] == "progress.update"]
    assert progresses and progresses[-1]["params"]["percent"] == 100.0


def test_failed_engine_marks_episode_only(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _make_project(harness, tmp_path, sample_video)

    def exploding_transcriber() -> FakeTranscriber:
        raise RuntimeError("引擎炸了")

    harness.context.analysis_runtime.transcriber = exploding_transcriber
    result = harness.rpc("analysis.start", {"project_id": project_id})
    status = harness.wait_done(str(result["job_id"]))

    assert status["status"] == "completed", "单集失败不应中断任务"
    results = harness.rpc("analysis.results", {"project_id": project_id})
    assert [ep["status"] for ep in results["episodes"]] == ["failed", "failed"]
    assert all(ep["asr_segment_count"] == 0 for ep in results["episodes"])


def test_cancel_between_episodes(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    instance = Harness(memory_db, tmp_path / "work", FakeTranscriber(delay_s=0.8))
    try:
        project_id = _make_project(instance, tmp_path, sample_video, copies=3)
        result = instance.rpc("analysis.start", {"project_id": project_id})
        time.sleep(0.2)
        instance.rpc("analysis.cancel", {"job_id": result["job_id"]})
        status = instance.wait_done(str(result["job_id"]))
        assert status["status"] == "cancelled"
    finally:
        instance.close()


def test_start_rejects_unknown_project(harness: Harness) -> None:
    response = harness.router.dispatch(
        RpcRequest(id=1, method="analysis.start", params={"project_id": "nope"})
    )
    assert response.error is not None and response.error.code == -32101
