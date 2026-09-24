"""project.list / project.get / project.create 出参携带阶段聚合（09-10 §6 核心层）。

analyzed_count = 分析落库（status='done'）的集数；plan_count = narration_plans 行数。
前端 deriveStages 靠它把 ②分析 / ③规划 灯从降级两极升级为真值——卷三意见 03：
聚合落地前宁灰勿假绿，落地后绿灯才允许点亮。语义红线：prescreened/analyzing/failed
都不算「分析完成」，只有 done 算。

对账三戳（09-10 §3.1 过期金灯）：analyzed_at=最近一次分析落库、last_episode_at=
最近一次喂料、latest_plan_at=最近一份方案快照——服务只供时间戳不下结论，
比先后是前端 stageFactsOf 的活。无从对账（NULL）金灯保持灰。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import project as project_api
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.transport.rpc import Router, RpcRequest


def _request(request_id: int, method: str, params: dict[str, Any]) -> Any:
    return RpcRequest(id=request_id, method=method, params=params)


def _router(memory_db: sqlite3.Connection, tmp_path: Path) -> Router:
    context = SimpleNamespace(conn=memory_db, work_dir=tmp_path, data_dir=tmp_path)
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def _seed(
    router: Router, memory_db: sqlite3.Connection, statuses: list[str], source: Path
) -> str:
    created = router.dispatch(
        _request(1, "project.create", {"name": "聚合", "source_path": str(source)})
    ).result
    project_id = str(created["id"])
    episodes_repo.replace_all(
        memory_db,
        project_id,
        [
            {
                "episode_number": index,
                "name": f"ep{index}",
                "source_path": f"ep{index}.mp4",
                "duration": 1.0,
            }
            for index in range(1, len(statuses) + 1)
        ],
    )
    for episode, status in zip(
        episodes_repo.list_by_project(memory_db, project_id), statuses, strict=True
    ):
        if status != "pending":
            episodes_repo.set_status(memory_db, str(episode["id"]), status)
    return project_id


def test_create_carries_zero_counts(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    router = _router(memory_db, tmp_path)
    created = router.dispatch(
        _request(1, "project.create", {"name": "空库", "source_path": "."})
    ).result
    assert created["analyzed_count"] == 0
    assert created["plan_count"] == 0


def test_list_and_get_count_only_done(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    router = _router(memory_db, tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    project_id = _seed(
        router, memory_db, ["done", "done", "prescreened", "failed", "pending"], source
    )
    plans_repo.create(memory_db, project_id, "full_narration", ["e1"], {"scenes": []})
    plans_repo.create(memory_db, project_id, "raw_clip", ["e2"], {"scenes": []})

    rows = router.dispatch(_request(2, "project.list", {})).result
    row = next(item for item in rows if str(item["id"]) == project_id)
    assert row["episode_count"] == 5
    assert row["analyzed_count"] == 2, "prescreened/failed/pending 都不算分析完成"
    assert row["plan_count"] == 2

    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id})).result
    assert detail["project"]["analyzed_count"] == 2
    assert detail["project"]["plan_count"] == 2


def test_counts_isolated_per_project(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    router = _router(memory_db, tmp_path)
    # projects.source_path 有 UNIQUE：两部剧各给一个真实目录
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _seed(router, memory_db, ["done"], first_dir)
    plans_repo.create(memory_db, first, "full_narration", ["e1"], {"scenes": []})
    second = _seed(router, memory_db, ["pending", "pending"], second_dir)

    listed = router.dispatch(_request(2, "project.list", {})).result
    rows = {str(item["id"]): item for item in listed}
    assert rows[first]["analyzed_count"] == 1
    assert rows[first]["plan_count"] == 1
    assert rows[second]["analyzed_count"] == 0, "别的剧的账不许串到这部剧头上"
    assert rows[second]["plan_count"] == 0


def test_reconciliation_timestamps_aggregated(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    router = _router(memory_db, tmp_path)
    source = tmp_path / "ts-src"
    source.mkdir()
    project_id = _seed(router, memory_db, ["pending", "pending"], source)
    episodes = episodes_repo.list_by_project(memory_db, project_id)
    first_id = str(episodes[0]["id"])

    episodes_repo.mark_done(memory_db, first_id)
    stamped = memory_db.execute(
        "SELECT analyzed_at FROM episodes WHERE id = ?", (first_id,)
    ).fetchone()
    assert stamped[0] is not None, "mark_done 必须同时盖对账戳"

    plans_repo.create(memory_db, project_id, "full_narration", ["e1"], {"scenes": []})
    # 钉显式时间戳，免同毫秒竞态：分析(5000) 新于方案(4000)
    memory_db.execute(
        "UPDATE episodes SET analyzed_at = 5000 WHERE project_id = ?", (project_id,)
    )
    memory_db.execute(
        "UPDATE narration_plans SET created_at = 4000 WHERE project_id = ?", (project_id,)
    )
    memory_db.commit()

    rows = router.dispatch(_request(2, "project.list", {})).result
    row = next(item for item in rows if str(item["id"]) == project_id)
    assert row["analyzed_at"] == 5000
    assert row["latest_plan_at"] == 4000
    assert isinstance(row["last_episode_at"], int), "喂料时间是硬数据，不许缺"

    detail = router.dispatch(_request(3, "project.get", {"project_id": project_id})).result
    assert detail["project"]["analyzed_at"] == 5000
    assert detail["project"]["latest_plan_at"] == 4000
    assert isinstance(detail["project"]["last_episode_at"], int)


def test_reconciliation_null_when_nothing_analyzed(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    router = _router(memory_db, tmp_path)
    source = tmp_path / "null-src"
    source.mkdir()
    project_id = _seed(router, memory_db, ["pending"], source)

    rows = router.dispatch(_request(2, "project.list", {})).result
    row = next(item for item in rows if str(item["id"]) == project_id)
    assert row["analyzed_at"] is None, "没分析过就不给对账戳——金灯宁灰勿假"
    assert row["latest_plan_at"] is None
    assert row["last_episode_at"] is not None

    created = router.dispatch(
        _request(1, "project.create", {"name": "空对账", "source_path": "."})
    ).result
    assert created["analyzed_at"] is None
    assert created["last_episode_at"] is None
    assert created["latest_plan_at"] is None
