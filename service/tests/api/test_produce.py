"""narration.produce：组合任务（编排→自动渲染）端到端（确定性数据直种）。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import analysis as analysis_api
from dramaclip.api import export as export_api
from dramaclip.api import narration as narration_api
from dramaclip.api import project as project_api
from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.infra import jobs
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, work_dir: Path) -> None:
        self.sent: list[dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.context = SimpleNamespace(
            conn=conn,
            work_dir=work_dir,
            settings={"asr.language": "zh"},
            notifier=Notifier(self.sent.append),
            executor=self.executor,
            job_store=jobs.JobStore(conn),
            cancel_events={},
        )
        self.router = Router()
        analysis_api.register(self.router, self.context)  # type: ignore[arg-type]
        project_api.register(self.router, self.context)  # type: ignore[arg-type]
        narration_api.register(self.router, self.context)  # type: ignore[arg-type]
        export_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        response = self.router.dispatch(
            RpcRequest(id=method, method=method, params=params or {})
        )
        if response.error is not None:
            raise AssertionError(
                f"{method} RPC 错误: [{response.error.code}] {response.error.message}"
            )
        return response.result

    def wait_job(self, job_id: str, timeout_s: float = 60.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.rpc("analysis.status", {"job_id": job_id})
            if status["status"] in ("completed", "failed", "cancelled"):
                return status
            time.sleep(0.05)
        raise AssertionError("任务超时")


def _seed_project_with_analysis(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> str:
    """建项目 + 扫描 + 直种确定性分析数据（单集标记 done），返回 project_id。"""
    shutil.copy(sample_video, tmp_path / "ep1.mp4")
    harness = Harness(memory_db, tmp_path / "cache")
    project = harness.rpc("project.create", {"name": "出片", "source_path": str(tmp_path)})
    harness.rpc("project.scan_episodes", {"project_id": project["id"]})
    project_id = str(project["id"])
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    scenes = [
        {"scene_index": i, "start": float(i), "end": float(i + 0.8), "score": 40 + i * 15}
        for i in range(3)
    ]
    analysis_repo.upsert(
        memory_db,
        episode_id,
        asr_segments=json.dumps(
            [
                {"start": 0.2, "end": 0.8, "text": "台词一"},
                {"start": 1.0, "end": 1.6, "text": "台词二"},
            ]
        ),
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
        conflict_scores=json.dumps(scenes),
        highlights=json.dumps(
            [{"scene_index": 2, "start": 2.0, "end": 2.8, "score": 64, "reason": "冲突"}]
        ),
    )
    episodes_repo.set_status(memory_db, episode_id, "done")
    return project_id


def test_produce_renders_work_end_to_end(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache")
    produce = harness.rpc(
        "narration.produce", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    status = harness.wait_job(str(produce["job_id"]))
    assert status["status"] == "completed", status.get("error")

    exports = harness.rpc("export.list", {"project_id": project_id})
    assert exports[0]["status"] == "completed"
    assert Path(str(exports[0]["output_path"])).is_file()

    works = harness.rpc("export.list_works", {"project_id": project_id})
    assert any(item["project_id"] == project_id for item in works)


def test_produce_invalid_mode(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    harness = Harness(memory_db, tmp_path / "cache")
    project = harness.rpc("project.create", {"name": "x", "source_path": str(tmp_path)})
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.produce",
            params={"project_id": project["id"], "modes": ["nope"]},
        )
    )
    assert response.error is not None and response.error.code == -32302
