"""B10 接线面：评分落库三列、生成链尾部评分、list_plans 软排序与降级。

硬边界（业主红线）：评分只做排序信号+改进建议，grade/defects 零改动；
评分失败/缺失不挡任何现有流程（job 照常 completed）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import variant_scoring
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from tests.api.test_plan_variants import (
    _LLM_SETTINGS,
    Harness,
    _seed_project_with_episodes,
    _stub_language_and_tts,
    _wait_terminal,
)


def _wait_until(predicate: Any, timeout_s: float = 10.0) -> None:
    """评分在 job 落终态**之后**跑（job 时长不受评分影响）：断言前轮询到条件成立。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("等待条件超时（评分尾部步骤没有跑完）")


def _seed_project(conn: sqlite3.Connection) -> str:
    return str(projects_repo.create(conn, "评分剧", "D:/media/评分剧")["id"])


def _plan(index: int) -> PlanData:
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=2.0, audio="ducked",
                            narration_id=f"n{index}")
        ],
        narration_texts=[NarrationText(id=f"n{index}", text=f"第 {index} 条的解说")],
    )


# ── 仓储层：三列写入/读回（形状学 titles 列） ────────────────────────────────


def test_set_scores_roundtrips_three_columns(memory_db: sqlite3.Connection) -> None:
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db, project_id, "full_narration", ["ep1"], _plan(1).model_dump()
    )
    assert row["score_total"] is None and row["score_dims"] is None
    assert row["suggestion"] is None, "未评分 = 三列全 NULL"

    dims = {"hook_power": 9.0, "cta_pull": 8.0}
    plans_repo.set_scores(memory_db, str(row["id"]), 8.6, dims, "把身份反差提到第一句")
    fetched = plans_repo.get(memory_db, str(row["id"]))
    assert fetched is not None
    assert fetched["score_total"] == pytest.approx(8.6)
    assert fetched["score_dims"] == dims, "score_dims 应解析回 dict（学 titles 列）"
    assert fetched["suggestion"] == "把身份反差提到第一句"


def test_list_paths_carry_the_score_columns(memory_db: sqlite3.Connection) -> None:
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db, project_id, "full_narration", ["ep1"], _plan(1).model_dump(),
        batch_id="b1",
    )
    plans_repo.set_scores(memory_db, str(row["id"]), 7.5, {"hook_power": 8.0}, "建议")
    by_project = plans_repo.list_by_project(memory_db, project_id)
    by_batch = plans_repo.list_by_batch(memory_db, project_id, "b1")
    for listed in (by_project, by_batch):
        assert listed[0]["score_total"] == pytest.approx(7.5)
        assert listed[0]["score_dims"] == {"hook_power": 8.0}
        assert listed[0]["suggestion"] == "建议"


# ── 迁移：014 在清单里，旧行升级后三列为 NULL ────────────────────────────────


def test_migration_014_exists_in_the_manifest() -> None:
    from dramaclip.infra.storage import db

    names = [path.name for path in sorted(db.MIGRATIONS_DIR.glob("*.sql"))]
    assert any(name.startswith("014_") for name in names), names


# ── list_plans：软排序 + 逐字节降级 ──────────────────────────────────────────


def _harness(memory_db: sqlite3.Connection) -> Any:
    from types import SimpleNamespace

    from dramaclip.api import narration as narration_api
    from dramaclip.transport.rpc import Router, RpcRequest

    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]

    def rpc(method: str, params: dict[str, Any]) -> Any:
        response = router.dispatch(RpcRequest(id=method, method=method, params=params))
        if response.error is not None:
            raise AssertionError(f"{method}: [{response.error.code}] {response.error.message}")
        return response.result

    return SimpleNamespace(context=context, rpc=rpc)


def _create_pair(conn: sqlite3.Connection, project_id: str) -> tuple[str, str]:
    first = plans_repo.create(
        conn, project_id, "full_narration", ["ep1"], _plan(1).model_dump(),
        variant_index=1, batch_id="b1",
    )
    second = plans_repo.create(
        conn, project_id, "full_narration", ["ep1"], _plan(2).model_dump(),
        variant_index=2, batch_id="b1",
    )
    # created_at 毫秒并列时的兜底是 id：拉开时间戳，顺序断言不靠扫描顺序
    conn.executemany(
        "UPDATE narration_plans SET created_at = ? WHERE id = ?",
        [(1_700_000_000_000, str(first["id"])), (1_700_000_001_000, str(second["id"]))],
    )
    conn.commit()
    return str(first["id"]), str(second["id"])


def test_list_plans_without_scores_is_byte_identical_to_the_current_order(
    memory_db: sqlite3.Connection,
) -> None:
    """硬验收：无分数时 list_plans 与现状逐字节一致（repo 原序 + 只补 block_reason）。"""
    project_id = _seed_project(memory_db)
    first_id, second_id = _create_pair(memory_db, project_id)
    harness = _harness(memory_db)

    rows = harness.rpc("narration.list_plans", {"project_id": project_id})
    assert [row["id"] for row in rows] == [second_id, first_id], "created_at DESC 原序"
    for row in rows:
        assert row["score_total"] is None and row["suggestion"] is None
        assert row["score_dims"] is None


def test_list_plans_orders_by_score_total_when_scored(
    memory_db: sqlite3.Connection,
) -> None:
    project_id = _seed_project(memory_db)
    first_id, second_id = _create_pair(memory_db, project_id)
    plans_repo.set_scores(memory_db, first_id, 5.0, {"hook_power": 5.0}, "第一条建议")
    plans_repo.set_scores(memory_db, second_id, 8.0, {"hook_power": 9.0}, "第二条建议")
    harness = _harness(memory_db)

    rows = harness.rpc("narration.list_plans", {"project_id": project_id})
    assert [row["id"] for row in rows] == [second_id, first_id], "高分在前"
    assert rows[0]["score_total"] == 8.0 and rows[0]["suggestion"] == "第二条建议"
    assert rows[0]["score_dims"] == {"hook_power": 9.0}
    assert rows[1]["suggestion"] == "第一条建议"


def test_list_plans_puts_unscored_rows_last_without_reordering_them(
    memory_db: sqlite3.Connection,
) -> None:
    project_id = _seed_project(memory_db)
    first_id, second_id = _create_pair(memory_db, project_id)
    third = plans_repo.create(
        memory_db, project_id, "full_narration", ["ep1"], _plan(3).model_dump(),
        variant_index=3, batch_id="b1",
    )
    memory_db.execute(
        "UPDATE narration_plans SET created_at = ? WHERE id = ?",
        (1_700_000_002_000, str(third["id"])),
    )
    memory_db.commit()
    # 只给时间上最旧的第一条评分：它应跳到最前，其余两条保持相对原序
    plans_repo.set_scores(memory_db, first_id, 9.0, {"hook_power": 9.0}, "建议")
    harness = _harness(memory_db)

    rows = harness.rpc("narration.list_plans", {"project_id": project_id})
    assert [row["id"] for row in rows] == [first_id, str(third["id"]), second_id]


def test_list_plans_batch_filter_still_sorts_by_score(
    memory_db: sqlite3.Connection,
) -> None:
    project_id = _seed_project(memory_db)
    first_id, second_id = _create_pair(memory_db, project_id)
    plans_repo.set_scores(memory_db, first_id, 9.0, {"hook_power": 9.0}, "建议")
    plans_repo.set_scores(memory_db, second_id, 2.0, {"hook_power": 2.0}, "建议")
    harness = _harness(memory_db)
    rows = harness.rpc(
        "narration.list_plans", {"project_id": project_id, "batch_id": "b1"}
    )
    assert [row["id"] for row in rows] == [first_id, second_id]


def test_get_plan_exposes_score_fields(memory_db: sqlite3.Connection) -> None:
    project_id = _seed_project(memory_db)
    first_id, _second_id = _create_pair(memory_db, project_id)
    plans_repo.set_scores(memory_db, first_id, 7.2, {"rhythm": 7.0}, "收紧前两段")
    harness = _harness(memory_db)
    detail = harness.rpc("narration.get_plan", {"plan_id": first_id})
    assert detail["plan"]["score_total"] == pytest.approx(7.2)
    assert detail["plan"]["score_dims"] == {"rhythm": 7.0}
    assert detail["plan"]["suggestion"] == "收紧前两段"


# ── 生成链尾部：评分自动触发；失败不挡 job ───────────────────────────────────


def test_plan_variants_scores_the_batch_at_the_tail_of_the_job(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K 条落库后一次 score_variants 调用评分并落库；job 照常 completed。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    scored_batches: list[list[dict[str, Any]]] = []

    def fake_score(rows: list[dict[str, Any]], settings: dict[str, str], **kwargs: Any) -> Any:
        scored_batches.append(rows)
        return {
            str(row["id"]): {
                "dims": {dim: 7.0 for dim in variant_scoring.DIMENSIONS},
                "total": 7.0,
                "suggestion": f"建议·{row['angle']}",
            }
            for row in rows
        }

    monkeypatch.setattr(variant_scoring, "score_variants", fake_score)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    _wait_until(lambda: len(scored_batches) == 1)
    assert len(scored_batches[0]) == 2, "整批只评一次"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert all(row["score_total"] == pytest.approx(7.0) for row in plans)
    assert {row["suggestion"] for row in plans} == {"建议·角度1", "建议·角度2"}
    # 评分不得改变硬门禁：grade 仍由 defects 决定，与分数无关
    assert all(row["status"] == "ready" for row in plans)

    listed = harness.rpc(
        "narration.list_plans", {"project_id": project_id, "batch_id": result["batch_id"]}
    )
    assert all(row["score_total"] == pytest.approx(7.0) for row in listed)


def test_scoring_failure_does_not_fail_the_job(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评分炸了：job 仍 completed，方案三列保持 NULL，日志留一句归因。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("文案评分未产出可用结果：网关 502")

    monkeypatch.setattr(variant_scoring, "score_variants", boom)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", f"评分失败不该拖垮规划 job：{status}"
    _wait_until(lambda: any("评分" in str(item) for item in harness.sent))
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 1
    assert plans[0]["score_total"] is None and plans[0]["suggestion"] is None
    logged = [str(item) for item in harness.sent]
    assert any("评分" in item for item in logged), f"评分失败应留痕日志：{harness.sent}"


def test_llm_unconfigured_skips_scoring_silently(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 未配置的项目走 raw_clip 规划：不评分、不报错、job 照常 completed。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    # 不注入 _LLM_SETTINGS：angles 会因未配置抛 LlmUnavailable → 选题失败。
    # 所以桩掉选题，只让「成稿→落库→尾部评分」走完。
    from dramaclip.engines.narration import angles as angles_mod

    monkeypatch.setattr(
        angles_mod,
        "select_angles",
        lambda *a, **k: [
            angles_mod.AngleBrief(
                name="角度1", reason="理由", hook="钩子", episode_numbers=[1]
            )
        ],
    )

    def assert_not_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("LLM 未配置时不该进评分调用")

    monkeypatch.setattr(variant_scoring, "score_variants", assert_not_called)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["raw_clip"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")


def test_draft_plans_also_get_suggestions(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """draft 与 ready 都给改进建议；grade 不因评分变动（门禁隔离的可观察面）。"""
    project_id = _seed_project(memory_db)
    draft = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=3.0, narration_id="a"),
            TimelineSegment(episode_id="ep1", start=3.0, end=5.0, narration_id="b"),
        ],
        narration_texts=[
            NarrationText(id="a", text="开场钩子"),
            NarrationText(id="b", text="今天就讲到这里"),  # 无 CTA → draft
        ],
    )
    row = plans_repo.create(
        memory_db, project_id, "full_narration", ["ep1"], draft.model_dump(),
        status="draft",
    )
    plans_repo.set_scores(memory_db, str(row["id"]), 3.1, {"cta_pull": 1.0}, "收尾要指向看全集")
    harness = _harness(memory_db)
    rows = harness.rpc("narration.list_plans", {"project_id": project_id})
    assert rows[0]["status"] == "draft", "评分不得翻动 grade"
    assert "收尾没有指向看全集" in rows[0]["block_reason"], "defects 照常给"
    assert rows[0]["suggestion"] == "收尾要指向看全集", "draft 也要有改进建议"
    assert rows[0]["score_total"] == pytest.approx(3.1)


def test_scoring_leaves_a_trace_file(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评分走真引擎函数 + 桩 LLM 客户端：data/logs/llm 下必须落 llm_variant_scoring_*.json。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    class _ScoringLlm:
        def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
            self.timeout_s = timeout_s

        def chat_json(self, _system: str, user: str) -> Any:
            calls.append((_system, user))
            indexes = [
                int(match) for match in __import__("re").findall(r"\[方案 (\d+)\]", user)
            ]
            return {
                "scores": [
                    {
                        "index": index,
                        "dims": {dim: 6.0 for dim in variant_scoring.DIMENSIONS},
                        "suggestion": "建议",
                    }
                    for index in indexes
                ]
            }

    monkeypatch.setattr(variant_scoring, "LlmClient", _ScoringLlm)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    def _traced() -> bool:
        return bool(list((tmp_path / "logs" / "llm").glob("llm_variant_scoring_*.json")))

    _wait_until(_traced)
    traces = list((tmp_path / "logs" / "llm").glob("llm_variant_scoring_*.json"))
    assert len(traces) == 1, f"评分未留痕：{sorted(p.name for p in traces)}"
    blob = json.loads(traces[0].read_text(encoding="utf-8"))
    assert blob["engine"] == "variant_scoring"
    assert blob["accepted"] == 1


def test_no_new_rpc_method_is_registered(memory_db: sqlite3.Connection) -> None:
    """契约同步钉死 Router==schema x-methods：新增方法必须先过 protocol 两侧。"""
    from types import SimpleNamespace

    from dramaclip.api import narration as narration_api
    from dramaclip.transport.rpc import Router

    router = Router()
    narration_api.register(router, SimpleNamespace(conn=memory_db, settings={}))  # type: ignore[arg-type]
    assert set(router.method_names) == {
        "narration.recommend_modes",
        "narration.plan_variants",
        "narration.list_plans",
        "narration.get_plan",
        "narration.list_styles",
        "narration.generate_titles",
        "narration.update_titles",
    }
