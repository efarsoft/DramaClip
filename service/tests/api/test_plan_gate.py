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


def _plan_of_mode(mode: str) -> PlanData:
    timeline = [] if mode in ("raw_clip", "subtitle_flow", "highlight_cut") else [
        TimelineSegment(
            episode_id="ep1", start=0.0, end=3.0, audio="ducked", narration_id="a"
        )
    ]
    texts = [] if not timeline else [NarrationText(id="a", text="开场钩子")]
    return PlanData(mode=mode, timeline=timeline, narration_texts=texts)


def test_list_plans_annotates_copy_source_keys(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """文案来源判据随行注两键（来源 + 期望），不塞布尔结论——是否降级由界面拼读。"""
    project_id = str(projects_repo.create(memory_db, "判据剧", str(tmp_path))["id"])
    plan = _plan_of_mode("full_narration").model_copy(
        update={"planner": "llm_script"}
    )
    plans_repo.create(
        memory_db, project_id, "full_narration", ["ep1"], plan.model_dump(), status="draft"
    )
    plans_repo.create(
        memory_db,
        project_id,
        "full_narration",
        ["ep1"],
        _plan_of_mode("full_narration").model_dump(),
        status="draft",
    )
    harness = _harness(memory_db)

    rows = _rpc(harness, "narration.list_plans", {"project_id": project_id})

    by_planner = {row["copy_source"]: row for row in rows}
    assert by_planner["llm_script"]["copy_source_expected"] == "llm_script"
    assert by_planner["rule"]["copy_source_expected"] == "llm_script"
    assert "copy_source" in rows[0] and "copy_source_expected" in rows[0]


def test_list_plans_zero_copy_mode_rule_is_by_design(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """零文案模式的 rule 来源是设计本意：两键一致，不得被徽章指控为降级。"""
    project_id = str(projects_repo.create(memory_db, "纯剪辑剧", str(tmp_path))["id"])
    plans_repo.create(
        memory_db,
        project_id,
        "raw_clip",
        ["ep1"],
        _plan_of_mode("raw_clip").model_dump(),
        status="draft",
    )
    harness = _harness(memory_db)

    rows = _rpc(harness, "narration.list_plans", {"project_id": project_id})

    assert rows[0]["copy_source"] == "rule"
    assert rows[0]["copy_source_expected"] == "rule"


def test_expected_copy_source_covers_every_supported_mode() -> None:
    """判据接口必须覆盖全部支持模式——highlight_cut 曾被手抄表漏掉（漂移实证）。"""
    for mode in narration_api.SUPPORTED_MODES:
        expected = "rule" if mode in narration_api._NO_TTS_MODES else "llm_script"
        assert narration_api.expected_copy_source(mode) == expected, mode
    assert narration_api.expected_copy_source("highlight_cut") == "rule"
