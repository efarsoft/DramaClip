"""narration.list_plans：转化门禁给方案卡补 block_reason。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import narration as narration_api
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcRequest


def _harness(memory_db: sqlite3.Connection) -> SimpleNamespace:
    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]
    return SimpleNamespace(context=context, router=router)


def _rpc(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    response = harness.router.dispatch(RpcRequest(id=method, method=method, params=params))
    if response.error is not None:
        raise AssertionError(f"{method} RPC 错误: [{response.error.code}] {response.error.message}")
    return response.result


def _plan_without_cta() -> PlanData:
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="ducked", narration_id="a"
            ),
            TimelineSegment(
                episode_id="ep1", start=3.0, end=5.0, audio="ducked", narration_id="b"
            ),
        ],
        narration_texts=[
            NarrationText(id="a", text="开场钩子"),
            NarrationText(id="b", text="今天就讲到这里"),
        ],
    )


def test_list_plans_returns_block_reason_when_cta_missing(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    project_id = str(projects_repo.create(memory_db, "门禁剧", str(tmp_path))["id"])
    plan = _plan_without_cta()
    plans_repo.create(
        memory_db,
        project_id,
        "full_narration",
        ["ep1"],
        plan.model_dump(),
        status="draft",
    )
    harness = _harness(memory_db)

    rows = _rpc(harness, "narration.list_plans", {"project_id": project_id})

    assert len(rows) == 1
    assert rows[0]["status"] == "draft"
    assert "收尾没有指向看全集" in rows[0]["block_reason"]
