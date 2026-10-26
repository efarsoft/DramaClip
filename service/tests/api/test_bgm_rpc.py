"""bgm.* RPC：生成入库全链（mock 引擎 + 真 ffmpeg 转码）、重扫幂等、清单聚合。

生成任务的边界语义都在这里锁死：单首失败留痕继续、全失败才判任务失败、
产物命名 acestep_<emotion>_NN 自增、入库行带 MIT 生成来源标记。
"""

from __future__ import annotations

import sqlite3
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import bgm as bgm_api
from dramaclip.infra.storage.repos import bgm as bgm_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import RpcRequest


class FakeJobStore:
    """bgm 域用到的最小作业账本（create/mark/complete/fail 四件）。"""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, str]] = {}
        self._n = 0

    def create(self, job_type: str, ref_id: str = "") -> str:
        self._n += 1
        job_id = f"job-{self._n}"
        self.jobs[job_id] = {"type": job_type, "status": "pending"}
        return job_id

    def mark_running(self, job_id: str) -> None:
        self.jobs[job_id]["status"] = "running"

    def mark_completed(self, job_id: str) -> None:
        self.jobs[job_id]["status"] = "completed"

    def mark_failed(self, job_id: str, message: str) -> None:
        self.jobs[job_id]["status"] = "failed"
        self.jobs[job_id]["error"] = message

    def list_recent(self, limit: int = 50, active_only: bool = False) -> list[dict[str, str]]:
        rows = [
            {"id": jid, **job, "active": job["status"] in ("pending", "running")}
            for jid, job in self.jobs.items()
        ]
        return [
            r for r in rows
            if not active_only or r["status"] in ("pending", "running")
        ][:limit]


class FakeEngine:
    """is_available/generate 的替身：generate 按 script 逐次出牌（异常或产 wav）。"""

    def __init__(self, available: bool = True, script: list[Any] | None = None) -> None:
        self.available = available
        self.script = list(script or [])
        self.calls: list[Path] = []

    def is_available(self) -> tuple[bool, str]:
        return self.available, "" if self.available else "未装配乐运行环境"

    def synthesize(self, request: Any, out_dir: Path) -> Path:
        self.calls.append(out_dir)
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"generated-{len(self.calls)}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 8000)
        return path


def _context(memory_db: sqlite3.Connection, tmp_path: Path, engine: FakeEngine) -> SimpleNamespace:
    sent: list[dict[str, Any]] = []
    return SimpleNamespace(
        conn=memory_db,
        settings={},
        notifier=Notifier(sent.append),
        sent=sent,
        job_store=FakeJobStore(),
        cancel_events={},
        work_dir=tmp_path / "cache",
        data_dir=tmp_path,
        _engine=lambda: engine,
    )


@pytest.fixture()
def fake_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from dramaclip.infra import paths

    monkeypatch.setattr(paths, "resolve_data_dir", lambda: tmp_path)
    monkeypatch.setattr(bgm_api, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


def _register_engine(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> None:
    monkeypatch.setattr(bgm_api, "_engine", lambda _context: engine)


def _router(memory_db: sqlite3.Connection) -> Any:
    from dramaclip.transport.rpc import Router

    return Router()


def test_generate_full_chain_lands_library_track(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    _register_engine(monkeypatch, engine)
    context = _context(memory_db, tmp_path, engine)
    router = _router(memory_db)
    bgm_api.register(router, context)
    result = router.dispatch(RpcRequest(id=1, method="bgm.generate", params={
        "emotions": ["suspense"], "per_emotion": 1, "duration_s": 120,
    })).result
    job_id = str(result["job_id"])
    # 任务线程是 daemon：轮询到终态为止（真转码亚秒级）
    for _ in range(200):
        if context.job_store.jobs[job_id]["status"] in ("completed", "failed"):
            break
        import time

        time.sleep(0.05)
    assert context.job_store.jobs[job_id]["status"] == "completed"
    rows = bgm_repo.list_all(memory_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["emotion"] == "suspense"
    assert row["license"] == "MIT·本地生成"
    assert row["attribution"] == "ACE-Step v1.5"
    landed = Path(str(row["file_path"]))
    assert landed.name == "acestep_suspense_01.ogg"
    assert landed.is_file()
    assert row["duration_s"] > 0
    # 产物 wav 已被转码清理
    assert not list((tmp_path / "cache" / "bgm-gen").glob("*.wav"))


def test_generate_two_successes_land_two_files(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """per_emotion=2 双成功 → 两个不同文件两行入库（自增序号 bug 回归钉）。"""
    engine = FakeEngine()
    _register_engine(monkeypatch, engine)
    context = _context(memory_db, tmp_path, engine)
    router = _router(memory_db)
    bgm_api.register(router, context)
    result = router.dispatch(
        RpcRequest(id=1, method="bgm.generate",
                   params={"emotions": ["suspense"], "per_emotion": 2}),
    ).result
    job_id = str(result["job_id"])
    import time

    for _ in range(200):
        if context.job_store.jobs[job_id]["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert context.job_store.jobs[job_id]["status"] == "completed"
    rows = bgm_repo.list_all(memory_db)
    assert len(rows) == 2
    names = {Path(r["file_path"]).name for r in rows}
    assert names == {"acestep_suspense_01.ogg", "acestep_suspense_02.ogg"}


def test_generate_partial_failure_continues(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(script=[RuntimeError("CUDA 崩了"), None])
    _register_engine(monkeypatch, engine)
    context = _context(memory_db, tmp_path, engine)
    router = _router(memory_db)
    bgm_api.register(router, context)
    result = router.dispatch(RpcRequest(id=1, method="bgm.generate", params={
        "emotions": ["anger"], "per_emotion": 2, "duration_s": 120,
    })).result
    job_id = str(result["job_id"])
    import time

    for _ in range(200):
        if context.job_store.jobs[job_id]["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert context.job_store.jobs[job_id]["status"] == "completed"
    assert len(bgm_repo.list_all(memory_db)) == 1
    assert any("生成失败" in str(m["params"]["message"]) for m in context.sent)


def test_generate_all_failed_marks_job_failed(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(script=[RuntimeError("模型装载失败")])
    _register_engine(monkeypatch, engine)
    context = _context(memory_db, tmp_path, engine)
    router = _router(memory_db)
    bgm_api.register(router, context)
    result = router.dispatch(
        RpcRequest(id=1, method="bgm.generate", params={"emotions": ["sadness"]}),
    ).result
    job_id = str(result["job_id"])
    import time

    for _ in range(200):
        if context.job_store.jobs[job_id]["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert context.job_store.jobs[job_id]["status"] == "failed"
    assert bgm_repo.list_all(memory_db) == []


def test_generate_rejects_bad_params_and_unavailable_engine(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(available=False)
    _register_engine(monkeypatch, engine)
    context = _context(memory_db, tmp_path, engine)
    router = _router(memory_db)
    bgm_api.register(router, context)

    def error_of(params: dict[str, Any]) -> str:
        response = router.dispatch(RpcRequest(id=1, method="bgm.generate", params=params))
        assert response.error is not None, "非法请求必须被拒"
        return response.error.message

    assert "emotions" in error_of({"emotions": ["happy"]})
    assert "duration_s" in error_of({"emotions": ["default"], "duration_s": 30})
    assert "运行环境" in error_of({"emotions": ["default"]})
    assert context.job_store.jobs == {}


def test_rescan_is_idempotent(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
) -> None:
    context = _context(memory_db, tmp_path, FakeEngine())
    router = _router(memory_db)
    bgm_api.register(router, context)
    import wave

    folder = tmp_path / "bgm" / "default"
    folder.mkdir(parents=True)
    with wave.open(str(folder / "default_01.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)
    first = router.dispatch(RpcRequest(id=1, method="bgm.rescan", params={})).result
    assert first["tracks"] == 1
    second = router.dispatch(RpcRequest(id=1, method="bgm.rescan", params={})).result
    assert second["tracks"] == 1
    assert len(bgm_repo.list_all(memory_db)) == 1


def test_library_groups_cover_five_emotions(
    memory_db: sqlite3.Connection, tmp_path: Path, fake_data_dir: Path,
) -> None:
    context = _context(memory_db, tmp_path, FakeEngine())
    router = _router(memory_db)
    bgm_api.register(router, context)
    bgm_repo.upsert_track(
        memory_db, file_path="x.ogg", emotion="triumph", duration_s=120.0, bpm=100.0,
    )
    result = router.dispatch(RpcRequest(id=1, method="bgm.library", params={})).result
    assert [g["emotion"] for g in result["groups"]] == [
        "default", "anger", "triumph", "suspense", "sadness",
    ]
    triumph = next(g for g in result["groups"] if g["emotion"] == "triumph")
    assert triumph["count"] == 1 and triumph["total_s"] == 120.0
    assert result["tracks"][0]["bpm"] == 100.0
