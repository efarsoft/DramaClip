"""分析链韧性：失败必须可见、可查、可恢复（客户反馈「分析失败没细节」的修复面）。

钉六件事：①任务体任何异常（含 pre-try 窗口）都落 mark_failed，不留 running 死尸；
②单集失败原因 append_detail 进任务行（轮询方可查，不再只有滚走的日志）；
③全军覆没判 failed 而非 completed；④取消恢复集状态而非记成「分析失败：已取消」；
⑤同项目并发分析被拒；⑥results 对一行坏 JSON 列不炸整个 RPC。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import analysis as analysis_api
from dramaclip.api import analysis_job as analysis_job
from dramaclip.engines.analysis import pipeline as analysis_pipeline
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcDomainError


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "work",
        settings={"analysis.ocr_enabled": "0"},
        analysis_runtime=SimpleNamespace(transcriber=lambda: SimpleNamespace(name="fake")),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
        executor=None,
        notifier=Notifier(lambda _m: None),
    )


def _project_with_episodes(
    memory_db: sqlite3.Connection, tmp_path: Path, count: int = 2
) -> tuple[str, list[dict[str, Any]]]:
    project = projects_repo.create(memory_db, "剧", str(tmp_path))
    episodes_repo.replace_all(
        memory_db,
        str(project["id"]),
        [
            {
                "episode_number": i + 1,
                "source_path": str(tmp_path / f"ep{i + 1}.mp4"),
                "duration": 60.0,
            }
            for i in range(count)
        ],
    )
    return str(project["id"]), episodes_repo.list_by_project(memory_db, str(project["id"]))


def test_run_job_marks_failed_when_pretry_step_raises(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """视觉会话打开失败（pre-try 窗口）→ 任务 failed、项目回 ready，不留 running 死尸。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path)
    context = _context(memory_db, tmp_path)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("视觉模型加载失败")

    monkeypatch.setattr(analysis_job.vision_engine, "open_session", boom)
    job_id = context.job_store.create("analysis", ref_id=project_id)
    analysis_job._run_job(context, job_id, project_id, episodes, threading.Event())
    job = context.job_store.get(job_id)
    assert job is not None and job["status"] == "failed"
    assert "视觉模型加载失败" in str(job["error"])
    assert projects_repo.get(memory_db, project_id)["status"] == "ready"


def test_all_episodes_failed_marks_job_failed(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每一集都失败 → 任务判 failed（带「全部 N 集」文案），不是绿色 completed。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=2)
    context = _context(memory_db, tmp_path)
    monkeypatch.setattr(analysis_job, "_analyze_one", lambda *a, **k: False)
    monkeypatch.setattr(analysis_job, "_mine_hotwords", lambda *a, **k: ({}, {}, {}, ""))
    job_id = context.job_store.create("analysis", ref_id=project_id)
    analysis_job._run_job(context, job_id, project_id, episodes, threading.Event())
    job = context.job_store.get(job_id)
    assert job is not None and job["status"] == "failed"
    assert "全部 2 集分析失败" in str(job["error"])


def test_partial_failure_still_completes(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单集失败不连坐：其余成功时任务仍 completed（原有语义保持）。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=2)
    context = _context(memory_db, tmp_path)
    monkeypatch.setattr(
        analysis_job, "_analyze_one", lambda *a, **k: int(a[2]["episode_number"]) == 1
    )
    monkeypatch.setattr(analysis_job, "_mine_hotwords", lambda *a, **k: ({}, {}, {}, ""))
    job_id = context.job_store.create("analysis", ref_id=project_id)
    analysis_job._run_job(context, job_id, project_id, episodes, threading.Event())
    assert context.job_store.get(job_id)["status"] == "completed"


def test_episode_failure_reason_lands_in_job_row(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单集失败原因 append_detail 进任务行——「分析失败」三个字之后能查到为什么。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=1)
    context = _context(memory_db, tmp_path)
    episode = episodes[0]
    episode_id = str(episode["id"])
    episodes_repo.set_status(memory_db, episode_id, "analyzing")

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("音频文件损坏")

    monkeypatch.setattr(analysis_pipeline, "analyze_episode", boom)
    ok = analysis_job._analyze_one(
        context, "job-1", episode, 0, 1, "zh", threading.Event()
    )
    assert ok is False
    job = memory_db.execute("SELECT error FROM jobs WHERE id='job-1'").fetchone()
    assert job is None  # 直调 _analyze_one 没有真 job 行——明细写不进不存在的行
    # 真实路径经 _run_job：重新以真 job 验证一次
    context2 = _context(memory_db, tmp_path)

    def fake_mine(*_a: object, **_k: object) -> tuple[dict, dict, dict, str]:
        return {}, {}, {}, ""

    monkeypatch.setattr(analysis_job, "_mine_hotwords", fake_mine)
    monkeypatch.setattr(analysis_pipeline, "analyze_episode", boom)
    monkeypatch.setattr(
        analysis_job.vision_engine, "open_session", lambda *a, **k: None
    )
    job_id = context2.job_store.create("analysis", ref_id=project_id)
    analysis_job._run_job(context2, job_id, project_id, episodes, threading.Event())
    row = context2.job_store.get(job_id)
    assert row is not None and row["status"] == "failed"
    assert "第1集: 音频文件损坏" in str(row["error"])


def test_cancel_restores_episode_status_not_failed(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """取消发生在一集内部 → 该集恢复原状态（prescreened），不是「分析失败：已取消」。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=1)
    context = _context(memory_db, tmp_path)
    episode_id = str(episodes[0]["id"])
    # 快照时序与真实链路一致：先落 prescreened 再取快照（start() 也是先标状态后……
    # 不——start() 先查列表后标 analyzing，快照=标记前状态；这里同构）。
    episodes_repo.set_status(memory_db, episode_id, "prescreened")
    episodes = episodes_repo.list_by_project(memory_db, project_id)
    episode = episodes[0]

    cancel_event = threading.Event()
    cancel_event.set()

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("已取消")

    monkeypatch.setattr(analysis_pipeline, "analyze_episode", boom)
    ok = analysis_job._analyze_one(
        context, "job-1", episode, 0, 1, "zh", cancel_event
    )
    assert ok is False
    assert episodes_repo.get(memory_db, episode_id)["status"] == "prescreened"


def test_start_rejects_concurrent_ingest(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """同项目已有 analysis 任务在跑 → 再 start 报 BUSY，不放双跑。"""
    project_id, _episodes = _project_with_episodes(memory_db, tmp_path)
    context = _context(memory_db, tmp_path)
    context.job_store.create("analysis", ref_id=project_id)
    # create 是 pending；_active_ingest_job 只认 active——把它标 running
    job = context.job_store.list_recent(limit=10)[0]
    context.job_store.mark_running(str(job["id"]))
    with pytest.raises(RpcDomainError) as excinfo:
        analysis_api.start(context, {"project_id": project_id})
    assert excinfo.value.code == -32205


def test_update_asr_rejected_while_analyzing(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=1)
    context = _context(memory_db, tmp_path)
    episode_id = str(episodes[0]["id"])
    episodes_repo.set_status(memory_db, episode_id, "analyzing")
    with pytest.raises(RpcDomainError) as excinfo:
        analysis_api.update_asr(
            context,
            {"project_id": project_id, "episode_id": episode_id, "segments": []},
        )
    assert excinfo.value.code == -32204


def test_results_tolerates_corrupt_json_columns(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """一行坏 JSON 列（asr_segments/highlights/scene_data）不再炸整个 results RPC。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=1)
    context = _context(memory_db, tmp_path)
    episode_id = str(episodes[0]["id"])
    episodes_repo.mark_done(memory_db, episode_id)
    memory_db.execute(
        "INSERT INTO episode_analysis (episode_id, asr_segments, highlights, scene_data,"
        " audio_features, analyzed_at) VALUES (?, ?, ?, ?, ?, ?)",
        (episode_id, "{broken", "[also broken", "not json", "{}", 1),
    )
    memory_db.commit()
    result = analysis_api.results(context, {"project_id": project_id})
    entry = result["episodes"][0]
    assert entry["asr_segment_count"] == 0
    assert entry["scene_count"] == 0


def test_prescreen_handoff_failure_keeps_job_completed(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预筛完成后的 then_analyze 移交失败 → 预筛任务保持 completed，不回写 failed。"""
    project_id, episodes = _project_with_episodes(memory_db, tmp_path, count=1)
    context = _context(memory_db, tmp_path)

    def fake_prescreen(_path: Path, _wav: Path, *, threshold: float) -> dict[str, Any]:
        return {
            "audio_peak_density": 0.0, "scene_cut_density": 0.0,
            "voice_activity_ratio": 0.0, "motion_intensity": 0.0,
            "prescreen_score": 99.0, "recommended": True,
        }

    monkeypatch.setattr(analysis_api.prescreen_engine, "prescreen_episode", fake_prescreen)

    def boom(*_a: object, **_k: object) -> dict[str, str]:
        raise RuntimeError("start 移交失败")

    monkeypatch.setattr(analysis_api, "start", boom)
    job_id = context.job_store.create("prescreen", ref_id=project_id)
    context.job_store.mark_running(job_id)
    analysis_api._run_prescreen(
        context, job_id, project_id, episodes, threading.Event(), then_analyze=True
    )
    assert context.job_store.get(job_id)["status"] == "completed"


def test_parse_sensevoice_tolerates_malformed_timestamps() -> None:
    """畸形时间戳行（≠2 元素）跳过，不再 ValueError: too many values to unpack。"""
    from dramaclip.engines.analysis.transcriber import _parse_sensevoice

    raw = [
        {"text": "你好 世界", "timestamp": [[0, 400], [400]], "broken": True},
        {"text": "没事", "timestamp": [[800, 1200], "junk", (1600, 2000)]},
    ]
    segments = _parse_sensevoice(raw)
    assert segments, "合法行仍要产出"
    assert all(seg.end > seg.start for seg in segments)
