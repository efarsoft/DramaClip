"""数据根目录锚点：成品必须落在 <data>/outputs/，且全服务不得再从 work_dir 上跳推导。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.api.test_produce import Harness, _seed_project_with_analysis

_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "dramaclip"


def test_export_output_lands_under_data_dir(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    produce = harness.rpc("narration.produce", {"project_id": project_id, "modes": ["raw_clip"]})
    status = harness.wait_job(str(produce["job_id"]))
    assert status["status"] == "completed", status.get("error")

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
