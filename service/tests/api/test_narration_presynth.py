"""C1 后台预合成的接线面：规划收官 → narration_presynth 入队 → 导出零真合成。

管线层契约见 tests/engines/narration/test_presynthesize.py；这里钉的是
plan_runner 的入队纪律（干净收官才入队、渲染类作业在跑不抢资源）和
「预热键=导出键」这条端到端等式。
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from dramaclip.api import narration as narration_api
from dramaclip.engines.narration import synthesis as synthesis
from dramaclip.engines.narration.models import PlanData
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from tests.api.test_plan_variants import (
    _LLM_SETTINGS,
    Harness,
    _seed_project_with_episodes,
    _stub_language_and_tts,
    _wait_terminal,
)
from tests.tts_stub import write_audio


class _CountingTextTts:
    """把文案写进音频并计数：预热/导出两端谁调了真引擎，数就说话。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, _voice: Any, out_path: Any) -> Any:
        self.calls.append(str(text))
        write_audio(out_path, text.encode("utf-8"))  # 与真引擎同契约：连词界边车一起落
        return out_path


def _wait_presynth_settled(context: Any, timeout_s: float = 10.0) -> None:
    """等预合成作业进终态：daemon 线程不等人，测试收尾前必须等完，
    防止它拿着本用例的内存库在下一用例里写（跨用例噪声）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        active = [
            row
            for row in context.job_store.list_recent(active_only=True)
            if row["type"] == "narration_presynth"
        ]
        if not active:
            return
        time.sleep(0.05)
    raise AssertionError("预合成作业 10 秒未收官")


def _presynth_rows(context: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in context.job_store.list_recent()
        if row["type"] == "narration_presynth"
    ]


def test_clean_completion_prewarms_and_export_skips_the_engine(
    memory_db: Any, tmp_path: Any, sample_video: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规划干净收官 → 入队预合成 → 出片全链不再调真引擎。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    engine = _CountingTextTts()
    _stub_language_and_tts(monkeypatch, [])  # 语言链打桩 + audio_duration_s 桩
    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: engine)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    presynth = _presynth_rows(harness.context)
    assert len(presynth) == 1, f"应恰好入队一条预合成，实得 {presynth}"
    presynth_status = _wait_terminal(harness, str(presynth[0]["id"]))
    assert presynth_status["status"] == "completed", presynth_status.get("error")
    assert any(
        rec.get("method") == "log.append"
        and "后台预合成完成" in str(rec.get("params", {}).get("message", ""))
        for rec in harness.sent
    ), f"完成话术没上日志面板: {harness.sent}"

    warmed_calls = len(engine.calls)
    assert warmed_calls >= 1, "预热至少真合成了一段"

    # 出片全链（_voice 与生产同路径）：方案从库里读、设置同源——零新增真合成
    plan_row = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))[0]
    plan = PlanData.model_validate(plan_row["plan_data"])
    sources = {
        str(ep["id"]): 120.0 for ep in episodes_repo.list_by_project(memory_db, project_id)
    }
    voiced = narration_api._voice(
        harness.context, plan, dict(harness.context.settings), sources
    )
    assert len(engine.calls) == warmed_calls, (
        f"预热命中后导出不得再调真引擎（{warmed_calls} → {len(engine.calls)}）"
    )
    for item in voiced.narration_texts:
        assert item.audio_path, "导出后 audio_path 必须落位"

    _wait_presynth_settled(harness.context)


def test_export_in_flight_suppresses_presynth(
    memory_db: Any, tmp_path: Any, sample_video: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """渲染类作业在跑：预合不入队，不与导出抢 TTS worker 与显存。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    _stub_language_and_tts(monkeypatch, [])

    busy = harness.context.job_store.create("export", ref_id=project_id)
    harness.context.job_store.mark_running(busy)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")
    assert _presynth_rows(harness.context) == [], "渲染在跑时不得入队预合成"
