"""数据根目录锚点：成品必须落在 <data>/outputs/，且全服务不得再从 work_dir 上跳推导。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import angles
from dramaclip.infra.storage.repos import plans as plans_repo
from tests.api.test_plan_variants import _LLM_SETTINGS, Harness, _seed_project_with_analysis

_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "dramaclip"


def _stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """单集种子的选题替身：共享替身固定产出两集角度，这里给唯一合法集。"""

    class _Llm:
        def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
            self.timeout_s = timeout_s

        def chat_json(self, system: str, user: str, temperature: float = 0.3) -> dict[str, Any]:
            if "选题操盘手" in system:  # angles._SYSTEM_PROMPT
                return {
                    "angles": [
                        {
                            "name": "单集角度",
                            "reason": "全剧仅此一集",
                            "hook": "开场钩子",
                            "episode_numbers": [1],
                        }
                    ]
                }
            return {}

    monkeypatch.setattr(angles, "LlmClient", _Llm)


def test_export_output_lands_under_data_dir(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    # 统一选题后 raw_clip 产出同样要求 LLM（57ac5a1）；替身给单集合法角度
    harness.context.settings.update(_LLM_SETTINGS)
    _stub_llm(monkeypatch)
    produce = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["raw_clip"], "k": 1},
    )
    status = harness.wait_job(str(produce["job_id"]))
    assert status["status"] == "completed", status.get("error")

    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, produce["batch_id"])[0]["id"])
    submit = harness.rpc("export.submit", {"plan_ids": [plan_id]})
    harness.wait_job(str(submit["exports"][0]["job_id"]))

    exported = harness.rpc("export.list", {"project_id": project_id})
    out = Path(str(exported[0]["output_path"]))
    assert out.is_file(), "成品未生成"
    assert out.parent.parent == tmp_path / "outputs", f"成品位置错误: {out}"
    assert "cache" not in out.parts, f"成品仍落在缓存目录: {out}"


def test_no_fragile_parent_walks_remain() -> None:
    """永久守卫：路径一律由 AppContext.data_dir / work_dir 直接给出，禁止 .parent 上跳。"""
    offenders = [
        str(py.relative_to(_SERVICE_ROOT))
        for py in sorted(_SERVICE_ROOT.rglob("*.py"))
        if "work_dir.parent" in py.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"出现新的 work_dir 上跳: {offenders}"
