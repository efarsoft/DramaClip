"""retell 驱动的文案重写循环：gate 报告择优 + 反馈注入（批 ① 下半）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)
from dramaclip.engines.narration.retell import RetellReport


class _FakeNotifier:
    def log(self, *args, **kwargs):
        pass


def _report(confusions: int, *, passed: bool = False) -> RetellReport:
    return RetellReport(
        retell="复述",
        confusions=[{"note": f"卡点{i}"} for i in range(confusions)],
        passed=passed,
    )


def _plan(text: str) -> PlanData:
    segment = TimelineSegment(
        episode_id="ep", start=0.0, end=2.0, audio="narration", narration_id="n0"
    )
    return PlanData(
        mode="cross_narration",
        timeline=[segment],
        narration_texts=[NarrationText(id="n0", text=text, brief="")],
    )


def test_gate_returns_report_and_writes_trace(tmp_path, monkeypatch):
    """gate 返回报告本体（重写循环取卡点），trace 落盘。"""
    import dramaclip.engines.semantic.llm_client as llm_client_mod
    from dramaclip.api import narration_plans
    from dramaclip.engines.narration import retell as retell_mod

    def fake_retell(text, client):
        return RetellReport(retell="复述", confusions=[{"note": "没听懂"}], passed=False)

    class _Client:
        def chat_json(self, *args, **kwargs):
            return {"retell": "复述", "confusions": [], "passed": True, "reasons": []}

    monkeypatch.setattr(retell_mod, "retell_check", fake_retell)
    monkeypatch.setattr(llm_client_mod, "client_for", lambda _settings: _Client())

    report = narration_plans._retell_gate(
        _plan("文本"), {"narration.retell_check": "1"}, tmp_path, _FakeNotifier()
    )
    assert report is not None and report.passed is False
    assert (tmp_path / "retell.json").is_file()
    saved = json.loads((tmp_path / "retell.json").read_text(encoding="utf-8"))
    assert saved["confusions"][0]["note"] == "没听懂"


def test_rewrite_loop_adopts_passing_rewrite(tmp_path, monkeypatch):
    """重写循环：初稿不达标 → 带卡点重写一次 → 重写稿复述达标才换血。"""
    from dramaclip.api import narration_plans

    plan = _plan("初稿文本")
    reports = iter([_report(4), _report(1, passed=True)])
    copies = iter(["重写稿文本"])

    def fake_gate(_plan, _settings, _trace, _notifier):
        return next(reports)

    def fake_write(_plan, _material, _settings, *, mode_label, angle_block,
                   trace_dir, rewrite_notes=""):
        assert "复述卡点" in rewrite_notes, "重写必须携带卡点反馈"
        return _plan.model_copy(update={
            "narration_texts": [NarrationText(id="n0", text=next(copies), brief="")]
        })

    monkeypatch.setattr(narration_plans, "_retell_gate", fake_gate)
    monkeypatch.setattr(narration_plans.copywriter, "write_plan_copy", fake_write)
    out = narration_plans._rewrite_copy_until_retellable(
        SimpleNamespace(notifier=_FakeNotifier()),
        plan, {}, {}, mode_label="交叉解说", angle_block="", trace_dir=None,
    )
    assert out.narration_texts[0].text == "重写稿文本"


def test_rewrite_loop_injects_scoring_suggestion(tmp_path, monkeypatch):
    """①审计落地：重写反馈并流评分器六维诊断——复述抓听不懂，评分抓不吸引。"""
    from dramaclip.api import narration_plans
    from dramaclip.engines.narration import variant_scoring as vs

    plan = _plan("初稿文本")
    reports = iter([_report(4), _report(1, passed=True)])
    copies = iter(["重写稿文本"])

    def fake_gate(_plan, _settings, _trace, _notifier):
        return next(reports)

    def fake_write(_plan, _material, _settings, *, mode_label, angle_block,
                   trace_dir, rewrite_notes=""):
        assert "评分建议：钩子再具体一点" in rewrite_notes, "评分诊断必须随卡点入重写"
        return _plan.model_copy(update={
            "narration_texts": [NarrationText(id="n0", text=next(copies), brief="")]
        })

    def fake_score_one(plan_data, angle, settings, *, trace_dir=None):
        assert angle == "角度名"
        return {"dims": {"hook_power": 6.0}, "total": 6.0, "suggestion": "钩子再具体一点"}

    monkeypatch.setattr(narration_plans, "_retell_gate", fake_gate)
    monkeypatch.setattr(narration_plans.copywriter, "write_plan_copy", fake_write)
    monkeypatch.setattr(vs, "score_one", fake_score_one)
    out = narration_plans._rewrite_copy_until_retellable(
        SimpleNamespace(notifier=_FakeNotifier()),
        plan, {}, {}, mode_label="交叉解说", angle_block="", trace_dir=None,
        angle_name="角度名",
    )
    assert out.narration_texts[0].text == "重写稿文本"


def test_rewrite_loop_survives_scoring_failure(tmp_path, monkeypatch):
    """评分诊断是增益不是依赖：score_one 抛异常时只缺建议，重写照常进行。"""
    from dramaclip.api import narration_plans
    from dramaclip.engines.narration import variant_scoring as vs

    plan = _plan("初稿文本")
    reports = iter([_report(4), _report(1, passed=True)])
    copies = iter(["重写稿文本"])
    seen_notes: list[str] = []

    def fake_gate(_plan, _settings, _trace, _notifier):
        return next(reports)

    def fake_write(_plan, _material, _settings, *, mode_label, angle_block,
                   trace_dir, rewrite_notes=""):
        seen_notes.append(rewrite_notes)
        return _plan.model_copy(update={
            "narration_texts": [NarrationText(id="n0", text=next(copies), brief="")]
        })

    monkeypatch.setattr(narration_plans, "_retell_gate", fake_gate)
    monkeypatch.setattr(narration_plans.copywriter, "write_plan_copy", fake_write)
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(vs, "score_one", _boom)
    out = narration_plans._rewrite_copy_until_retellable(
        SimpleNamespace(notifier=_FakeNotifier()),
        plan, {}, {}, mode_label="交叉解说", angle_block="", trace_dir=None,
        angle_name="角度名",
    )
    assert out.narration_texts[0].text == "重写稿文本"
    assert seen_notes and "评分建议" not in seen_notes[0], "诊断失败不挡重写"


def test_rewrite_loop_keeps_original_when_rewrite_worse(tmp_path, monkeypatch):
    """重写稿复述仍未达标 → 择优保留原稿，不盲采。"""
    from dramaclip.api import narration_plans

    plan = _plan("初稿文本")
    reports = iter([_report(1), _report(6)])
    writes = iter(["重写稿文本"])

    def fake_gate(_plan, _settings, _trace, _notifier):
        return next(reports)

    def fake_write(_plan, _material, _settings, *, mode_label, angle_block,
                   trace_dir, rewrite_notes=""):
        return _plan.model_copy(update={
            "narration_texts": [NarrationText(id="n0", text=next(writes), brief="")]
        })

    monkeypatch.setattr(narration_plans, "_retell_gate", fake_gate)
    monkeypatch.setattr(narration_plans.copywriter, "write_plan_copy", fake_write)
    out = narration_plans._rewrite_copy_until_retellable(
        SimpleNamespace(notifier=_FakeNotifier()),
        plan, {}, {}, mode_label="交叉解说", angle_block="", trace_dir=None,
    )
    assert out.narration_texts[0].text == "初稿文本", "重写更差：保留原稿"
