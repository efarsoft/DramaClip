"""P0 修复核验：四个规则模式经真实 RPC 链的 status 必须回到 ready。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dramaclip.engines.narration import golden_lines as golden_lines_mod
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra.storage.repos import plans as plans_repo
from tests.api.test_plan_variants import (
    _LLM_SETTINGS,
    Harness,
    _seed_project_with_episodes,
    _stub_language_and_tts,
    _wait_terminal,
)


@pytest.mark.parametrize(
    "mode", ["intro_narration", "cross_narration", "ultra_short_hook", "subtitle_flow"]
)
def test_rule_mode_back_to_ready(
    mode: str,
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)
    # 金句提取走 LLM：测试桩按编号回填（与文案链打桩同款手法）
    monkeypatch.setattr(golden_lines_mod, "LlmClient", lambda *_a, **_k: type(
        "_GoldenFake", (), {"chat_json": staticmethod(lambda _s, _u: {"ids": [1, 2]})}
    )())

    result = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": [mode], "k": 1}
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    row = plans[0]
    plan = PlanData.model_validate(row["plan_data"])
    from dramaclip.engines.narration.conversion import defects

    assert row["status"] == "ready", (
        f"{mode} 仍 draft：defects={defects(plan)}——规则模式生产线断着"
    )
