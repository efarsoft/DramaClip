"""api.analysis：job 模式全生命周期（fake 引擎，真实落库与进度）。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import project as project_api
from dramaclip.engines.analysis import pipeline
from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures
from dramaclip.infra import jobs
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest
from tests.conftest import register_job_executor


class FakeTranscriber:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.calls = 0

    @property
    def name(self) -> str:
        return "fake"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return [AsrSegment(start=0.2, end=1.0, text="测试台词")]


class Harness:
    def __init__(
        self,
        conn: sqlite3.Connection,
        work_dir: Path,
        transcriber: FakeTranscriber,
        *,
        data_dir: Path,
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.transcriber = transcriber
        register_job_executor(self.executor)
        self._futures: list[Any] = []
        # 捕获型 submit：future 完成即留存，wait_done 超时能拿到作业线程里被吞的异常
        inner_submit = self.executor.submit

        def capturing_submit(fn: Any, *args: Any, **kwargs: Any) -> Any:
            future = inner_submit(fn, *args, **kwargs)
            self._futures.append(future)
            return future

        self.executor.submit = capturing_submit  # type: ignore[method-assign]
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
            data_dir=data_dir,
            cancel_events={},
        )
        self.router = Router()
        analysis_api.register(self.router, self.context)  # type: ignore[arg-type]
        project_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        response = self.router.dispatch(RpcRequest(id=method, method=method, params=params))
        if response.error is not None:
            raise AssertionError(
                f"{method} RPC 错误: [{response.error.code}] {response.error.message}"
            )
        return response.result

    def wait_done(self, job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        status: dict[str, Any] | None = None
        while time.time() < deadline:
            status = self.rpc("analysis.status", {"job_id": job_id})
            if status["status"] in ("completed", "failed", "cancelled"):
                return status
            time.sleep(0.05)
        import io
        import sys
        import threading
        import traceback

        dump = io.StringIO()
        dump.write(f"任务超时未完成：最后状态 {status}\n")
        dump.write(f"队列积压 {self.executor._work_queue.qsize()} 项\n")  # noqa: SLF001 - 诊断
        for future in self._futures:
            if future.done() and future.exception() is not None:
                dump.write("--- 作业线程未落库的异常 ---\n")
                dump.write("".join(
                    traceback.format_exception(future.exception())
                ))
        for thread_id, frame in sys._current_frames().items():  # noqa: SLF001 - 诊断
            name = next(
                (t.name for t in threading.enumerate() if t.ident == thread_id), str(thread_id)
            )
            if name == "MainThread":
                continue
            dump.write(f"--- {name} ---\n")
            traceback.print_stack(frame, file=dump)
        raise AssertionError(dump.getvalue())

    def close(self) -> None:
        self.executor.shutdown(wait=True)


@pytest.fixture
def harness(memory_db: sqlite3.Connection, tmp_path: Path) -> Harness:
    instance = Harness(memory_db, tmp_path / "work", FakeTranscriber(), data_dir=tmp_path)
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
    instance = Harness(
        memory_db, tmp_path / "work", FakeTranscriber(delay_s=0.8), data_dir=tmp_path
    )
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


def _analyzed_project(
    harness: Harness, tmp_path: Path, sample_video: Path
) -> tuple[str, str]:
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    result = harness.rpc("analysis.start", {"project_id": project_id})
    status = harness.wait_done(str(result["job_id"]))
    assert status["status"] == "completed"
    results = harness.rpc("analysis.results", {"project_id": project_id})
    episode_id = str(results["episodes"][0]["episode_id"])
    return project_id, episode_id


def test_update_asr_replaces_and_keeps_semantics(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id, episode_id = _analyzed_project(harness, tmp_path, sample_video)
    before = analysis_repo.get(memory_db, episode_id)
    assert before is not None

    result = harness.rpc(
        "analysis.update_asr",
        {
            "project_id": project_id,
            "episode_id": episode_id,
            "segments": [
                {"start": 0.5, "end": 2.5, "text": " 修正后的台词 ", "speaker": "主角"},
                {"start": 5.0, "end": 3.0, "text": "时间倒置应被过滤"},
                {"start": 6.0, "end": 7.0, "text": "   "},
            ],
        },
    )
    assert result == {"ok": True, "count": 1}

    after = analysis_repo.get(memory_db, episode_id)
    assert after is not None
    segments = json.loads(after["asr_segments"])
    assert [(seg["start"], seg["text"], seg["speaker"]) for seg in segments] == [
        (0.5, "修正后的台词", "主角")
    ]
    assert after["scene_data"] == before["scene_data"], "语义/场景结果必须保留"
    assert after["highlights"] == before["highlights"]


def test_update_asr_rejects_missing_analysis(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="analysis.update_asr",
            params={
                "project_id": project_id,
                "episode_id": episode_id,
                "segments": [],
            },
        )
    )
    assert response.error is not None and response.error.code == -32203


def test_update_asr_rejects_foreign_episode(
    harness: Harness, tmp_path: Path, sample_video: Path
) -> None:
    project_id, episode_id = _analyzed_project(harness, tmp_path, sample_video)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="analysis.update_asr",
            params={"project_id": project_id, "episode_id": "nope", "segments": []},
        )
    )
    assert response.error is not None and response.error.code == -32101
    assert project_id and episode_id


def test_resync_semantic_refreshes_without_touching_asr(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id, episode_id = _analyzed_project(harness, tmp_path, sample_video)
    harness.rpc(
        "analysis.update_asr",
        {
            "project_id": project_id,
            "episode_id": episode_id,
            "segments": [{"start": 0.2, "end": 1.0, "text": "修正后的台词"}],
        },
    )
    result = harness.rpc(
        "analysis.resync_semantic", {"project_id": project_id, "episode_id": episode_id}
    )
    status = harness.wait_done(str(result["job_id"]))
    assert status["status"] == "completed"

    record = analysis_repo.get(memory_db, episode_id)
    assert record is not None
    assert json.loads(record["asr_segments"])[0]["text"] == "修正后的台词"
    assert isinstance(json.loads(record["conflict_scores"]), list)
    progresses = [m for m in harness.sent if m["method"] == "progress.update"]
    assert progresses[-1]["params"]["percent"] == 100.0


def test_resync_semantic_rejects_missing_analysis(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="analysis.resync_semantic",
            params={"project_id": project_id, "episode_id": episode_id},
        )
    )
    assert response.error is not None and response.error.code == -32203


def test_start_reanalyzes_stale_analyzing_episode(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """崩溃残留的 analyzing 集（无分析数据）必须被下次分析重跑，而不是被跳过。"""
    project_id = _make_project(harness, tmp_path, sample_video)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    harness.wait_done(str(first["job_id"]))
    episodes = episodes_repo.list_by_project(memory_db, project_id)
    stale = episodes[0]
    memory_db.execute("DELETE FROM episode_analysis WHERE episode_id = ?", (stale["id"],))
    memory_db.execute("UPDATE episodes SET status = 'analyzing' WHERE id = ?", (stale["id"],))
    memory_db.commit()

    second = harness.rpc("analysis.start", {"project_id": project_id})
    status = harness.wait_done(str(second["job_id"]))

    assert status["status"] == "completed"
    refreshed = episodes_repo.list_by_project(memory_db, project_id)
    assert all(ep["status"] == "done" for ep in refreshed)


def test_scan_at_or_below_threshold_autostarts_analysis(
    harness: Harness, tmp_path: Path, sample_video: Path
) -> None:
    """≤N 集导入扫完即交全量分析，不用人点「批量分析」。"""
    harness.context.settings["analysis.full_threshold"] = "15"
    project_id = _make_project(harness, tmp_path, sample_video, copies=2)
    jobs = [
        job
        for job in harness.context.job_store.list_recent()
        if job["type"] == "analysis" and job["ref_id"] == project_id
    ]
    assert len(jobs) == 1, "扫集后应自动提交 analysis 任务"
    status = harness.wait_done(str(jobs[0]["id"]))
    assert status["status"] == "completed"
    results = harness.rpc("analysis.results", {"project_id": project_id})
    assert [ep["status"] for ep in results["episodes"]] == ["done", "done"]


def test_scan_above_threshold_prescreens_then_analyzes_recommended(
    harness: Harness, tmp_path: Path, sample_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """>N 集先预筛，入选的再全量分析。"""
    harness.context.settings["analysis.full_threshold"] = "1"

    def fake_prescreen(video_path: Path, wav_path: Path, *, threshold: float) -> dict[str, float]:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"")
        return {
            "audio_peak_density": 1.0,
            "scene_cut_density": 1.0,
            "voice_activity_ratio": 1.0,
            "motion_intensity": 1.0,
            "prescreen_score": 90.0,
            "recommended": 1.0,
        }

    monkeypatch.setattr(analysis_api.prescreen_engine, "prescreen_episode", fake_prescreen)
    project_id = _make_project(harness, tmp_path, sample_video, copies=2)
    prescreen_jobs = [
        job
        for job in harness.context.job_store.list_recent()
        if job["type"] == "prescreen" and job["ref_id"] == project_id
    ]
    assert len(prescreen_jobs) == 1, "超阈值应先预筛而不是直接全量"
    harness.wait_done(str(prescreen_jobs[0]["id"]))
    deadline = time.time() + 30.0
    analysis_jobs: list[dict[str, Any]] = []
    while time.time() < deadline:
        analysis_jobs = [
            job
            for job in harness.context.job_store.list_recent()
            if job["type"] == "analysis" and job["ref_id"] == project_id
        ]
        if analysis_jobs:
            break
        time.sleep(0.05)
    assert analysis_jobs, "预筛入选后应自动开全量分析"
    status = harness.wait_done(str(analysis_jobs[0]["id"]))
    assert status["status"] == "completed"


def test_scan_without_threshold_setting_does_not_autostart(
    harness: Harness, tmp_path: Path, sample_video: Path
) -> None:
    """测试夹具不带 analysis.full_threshold 时保持原行为：扫集不等于分析。"""
    assert "analysis.full_threshold" not in harness.context.settings
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    jobs = [job for job in harness.context.job_store.list_recent() if job["ref_id"] == project_id]
    assert jobs == []


def test_results_sets_clipping_when_audio_features_clip(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """源音频削顶：results 透出 clipping + peak_dbfs，不跑 ASR。"""
    from types import SimpleNamespace

    project_id = str(projects_repo.create(memory_db, "削顶剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {
                "episode_number": 1,
                "source_path": str(tmp_path / "ep1.mp4"),
                "duration": 3.0,
                "name": "ep1",
            }
        ],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments="[]",
        scene_data="[]",
        audio_features=AudioFeatures(clipping=True, peak_dbfs=0.0).model_dump_json(),
    )
    payload = analysis_api.results(SimpleNamespace(conn=memory_db), {"project_id": project_id})
    entry = payload["episodes"][0]
    assert entry["clipping"] is True
    assert entry["peak_dbfs"] == 0.0


# ── B8：源签名失效判定（防「源换了还静默用旧 ASR」）───────────────────────────


def _force_mtime(path: Path, seconds: int = 1_800_000_000) -> None:
    os.utime(path, ns=(seconds * 10**9, seconds * 10**9))


def _expected_signature(harness: Harness, source: Path) -> str | None:
    return pipeline.source_signature(
        source, ocr_channel=analysis_api._ocr_channel_available(harness.context)
    )


def test_changed_source_forces_reanalysis_of_done_episode(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """done 集源被换（同路径不同 mtime/size）→ 强制重分析 + 新签名落库 + 留痕。"""
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(first["job_id"]))["status"] == "completed"
    episode = episodes_repo.list_by_project(memory_db, project_id)[0]
    assert episode["status"] == "done"
    source = Path(str(episode["source_path"]))
    stored = episode["source_signature"]
    assert stored == _expected_signature(harness, source), "分析成功后应落库源签名"
    calls_before = harness.transcriber.calls

    _force_mtime(source)  # 源被替换：同路径，mtime 变
    second = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(second["job_id"]))["status"] == "completed"

    refreshed = episodes_repo.list_by_project(memory_db, project_id)[0]
    assert refreshed["status"] == "done"
    assert harness.transcriber.calls > calls_before, "源变更后必须真实重转写，不得静默用旧结果"
    assert refreshed["source_signature"] != stored
    assert refreshed["source_signature"] == _expected_signature(harness, source), "新签名落库"
    logs = [m["params"]["message"] for m in harness.sent if m["method"] == "log.append"]
    assert any("源已变更" in message for message in logs), "源变更重分析必须留痕"


def test_unchanged_source_keeps_done_episode_skipped(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """源不变 → 签名一致 → done 集照旧跳过（现有行为不变）。"""
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    harness.wait_done(str(first["job_id"]))
    calls_before = harness.transcriber.calls

    response = harness.router.dispatch(
        RpcRequest(id=1, method="analysis.start", params={"project_id": project_id})
    )
    assert response.error is not None and response.error.code == -32202, "源不变的 done 集应被跳过"
    response = harness.router.dispatch(
        RpcRequest(id=1, method="analysis.prescreen", params={"project_id": project_id})
    )
    assert response.error is not None and response.error.code == -32202
    assert harness.transcriber.calls == calls_before


def test_null_signature_done_episode_is_reanalyzed(
    harness: Harness, memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """旧库升级：done 集签名为 NULL → 首次判定视为需分析，重跑后签名补齐。"""
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    harness.wait_done(str(first["job_id"]))
    memory_db.execute("UPDATE episodes SET source_signature = NULL")
    memory_db.commit()
    calls_before = harness.transcriber.calls

    second = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(second["job_id"]))["status"] == "completed"
    assert harness.transcriber.calls > calls_before, "空签名（旧库首次）必须视为需分析"
    episode = episodes_repo.list_by_project(memory_db, project_id)[0]
    assert episode["status"] == "done"
    assert episode["source_signature"] == _expected_signature(
        harness, Path(str(episode["source_path"]))
    )


def test_ocr_capability_change_invalidates_done_episode(
    harness: Harness,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """降级路径：OCR 通道不可用 → 纯 ASR 产物打降级留痕；依赖就绪后签名失配强制重算。"""
    monkeypatch.setattr(analysis_api, "_ocr_channel_available", lambda _context: False)
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(first["job_id"]))["status"] == "completed"
    episode = episodes_repo.list_by_project(memory_db, project_id)[0]
    source = Path(str(episode["source_path"]))
    assert episode["source_signature"] == pipeline.source_signature(source, ocr_channel=False)
    logs = [m["params"]["message"] for m in harness.sent if m["method"] == "log.append"]
    assert any("降级" in message for message in logs), "降级产物必须打标留痕"
    calls_before = harness.transcriber.calls

    monkeypatch.setattr(analysis_api, "_ocr_channel_available", lambda _context: True)
    second = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(second["job_id"]))["status"] == "completed"
    assert harness.transcriber.calls > calls_before, "OCR 就绪后纯 ASR 降级产物必须重算"
    refreshed = episodes_repo.list_by_project(memory_db, project_id)[0]
    assert refreshed["source_signature"] == pipeline.source_signature(source, ocr_channel=True)


def test_prescreen_repcreens_done_episode_with_changed_source(
    harness: Harness,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """done 集源被换 → prescreen 也纳入重筛（预筛产物同样由源派生）。"""
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    harness.wait_done(str(first["job_id"]))
    episode = episodes_repo.list_by_project(memory_db, project_id)[0]
    source = Path(str(episode["source_path"]))
    _force_mtime(source)

    def fake_prescreen(video_path: Path, wav_path: Path, *, threshold: float) -> dict[str, float]:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"")
        return {
            "audio_peak_density": 1.0,
            "scene_cut_density": 1.0,
            "voice_activity_ratio": 1.0,
            "motion_intensity": 1.0,
            "prescreen_score": 90.0,
            "recommended": 1.0,
        }

    monkeypatch.setattr(analysis_api.prescreen_engine, "prescreen_episode", fake_prescreen)
    result = harness.rpc("analysis.prescreen", {"project_id": project_id})
    assert harness.wait_done(str(result["job_id"]))["status"] == "completed"
    refreshed = episodes_repo.list_by_project(memory_db, project_id)[0]
    assert refreshed["status"] == "prescreened", "源变更的 done 集应被重新预筛"
    assert refreshed["source_signature"] == _expected_signature(harness, source)


# ── A2：源硬字幕带落库（避让数据链：探测 → episode_analysis.subtitle_band）──────


def test_detected_subtitle_band_is_persisted(
    harness: Harness,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract_subtitles 回传的 band 必须落库，不能用完即弃。"""

    def fake_extract(*_a: Any, **_k: Any) -> Any:
        return ([], (0.76, 0.9))

    monkeypatch.setattr(analysis_api.subtitle_ocr, "extract_subtitles", fake_extract)
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(first["job_id"]))["status"] == "completed"
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    record = analysis_repo.get(memory_db, episode_id)
    assert record is not None
    assert json.loads(str(record["subtitle_band"])) == [0.76, 0.9]


def test_ocr_import_error_leaves_band_null_and_does_not_crash(
    harness: Harness,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """降级不可见：rapidocr 未装（ImportError）→ 分析照常完成，band 落 NULL。"""

    def fake_extract(*_a: Any, **_k: Any) -> Any:
        raise ImportError("rapidocr_onnxruntime")

    monkeypatch.setattr(analysis_api.subtitle_ocr, "extract_subtitles", fake_extract)
    project_id = _make_project(harness, tmp_path, sample_video, copies=1)
    first = harness.rpc("analysis.start", {"project_id": project_id})
    assert harness.wait_done(str(first["job_id"]))["status"] == "completed"
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    record = analysis_repo.get(memory_db, episode_id)
    assert record is not None and record["subtitle_band"] is None
