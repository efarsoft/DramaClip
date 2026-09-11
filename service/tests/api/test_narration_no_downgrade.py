"""降级禁止的可执行定义：文案为空、配音失败、段与文案对不上，三种情况都必须炸。

回归动机：这三条路过去全都"悄悄继续"——空文案照样排、合成失败照样回退原声、
旁白段与文案表按位置硬配。门禁测的是成片，这里测的是"坏片为什么没能被拦住"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import PlanData, StrategySpec, TimelineSegment
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.models import ConflictScore

_SCENES = [
    ConflictScore(scene_index=i, start=i * 12.0, end=i * 12.0 + 10.0, score=s)
    for i, s in enumerate([60, 85, 45, 90])
]


class _StubTts:
    def __init__(self, fail_ids: tuple[str, ...] = ()) -> None:
        self.fail_ids = fail_ids

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        if text.strip() == "":  # 真引擎对空文案会失败（ffprobe check=True）：替身必须一样
            raise RuntimeError("TTS 空文案：槽位未被语言层填充")
        if any(bad in str(out_path) for bad in self.fail_ids):
            raise RuntimeError("云端不可达")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp3")
        return out_path


def _plan_with_copy() -> PlanData:
    plan = build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))
    return plan.model_copy(update={
        "narration_texts": [
            t.model_copy(update={"text": f"第 {i} 段解说文案"})
            for i, t in enumerate(plan.narration_texts)
        ]
    })


def _synth(monkeypatch, plan, engine, work_dir: Path, duration: float = 1.25) -> PlanData:
    """`work_dir` 必须由调用方给 `tmp_path`——替身会真的 mkdir+落文件，
    传相对路径就是把测试产物写进共享工作树（`git status` 里凭空多一个 tts/）。"""
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: duration)
    return pipeline.synthesize_narration_texts(plan, {"tts.engine": "edge"}, work_dir / "tts")


def test_empty_copy_raises_before_tts(monkeypatch, tmp_path: Path) -> None:
    plan = build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))
    with pytest.raises(RuntimeError, match="文案为空"):
        _synth(monkeypatch, plan, _StubTts(), tmp_path)


def test_one_failed_segment_fails_whole_plan(monkeypatch, tmp_path: Path) -> None:
    plan = _plan_with_copy()
    with pytest.raises(RuntimeError, match="full-2"):
        _synth(monkeypatch, plan, _StubTts(fail_ids=("full-2",)), tmp_path)


def test_zero_duration_fails(monkeypatch, tmp_path: Path) -> None:
    plan = _plan_with_copy()
    with pytest.raises(RuntimeError, match="时长"):
        _synth(monkeypatch, plan, _StubTts(), tmp_path, duration=0.0)


def test_segment_without_narration_id_fails(monkeypatch, tmp_path: Path) -> None:
    plan = _plan_with_copy()
    broken = plan.model_copy(update={
        "timeline": [s.model_copy(update={"narration_id": None}) for s in plan.timeline]
    })
    with pytest.raises(RuntimeError, match="narration_id"):
        _synth(monkeypatch, broken, _StubTts(), tmp_path)


def test_backfill_writes_duration_subtitle_and_id(monkeypatch, tmp_path: Path) -> None:
    plan = _synth(monkeypatch, _plan_with_copy(), _StubTts(), tmp_path)
    assert all(s.narration_id for s in plan.timeline)
    assert all(s.subtitle_text for s in plan.timeline)
    assert all(abs((s.end - s.start) - 1.25) < 0.01 for s in plan.timeline)
    assert all(t.audio_path and t.duration == 1.25 for t in plan.narration_texts)


def test_narration_segments_with_empty_text_table_fail(monkeypatch, tmp_path: Path) -> None:
    """有旁白段却没有文案表：这是静音片，必须炸——空表不等于"没旁白"。

    回填层原先在扫段之前就 `if not plan.narration_texts: return plan`，于是这种方案
    原样返回：段上写着 narration/ducked，音频一个都没配，导出层照常合成一条无声轨。
    这正是本文件要消灭的形状——只是它藏在"提前返回"里，比其余三条更不容易看见。
    """
    plan = _plan_with_copy().model_copy(update={"narration_texts": []})
    assert any(s.audio in ("narration", "ducked") for s in plan.timeline), "种子必须含旁白段"
    with pytest.raises(RuntimeError, match="编排自相矛盾"):
        _synth(monkeypatch, plan, _StubTts(), tmp_path)


def test_plan_without_narration_segments_skips_tts(monkeypatch, tmp_path: Path) -> None:
    """一段旁白都没有时，空文案表是合法的：纯剪辑方案不该被配音层拦下或付费。"""
    silent = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=2.0, audio="original")],
        strategy=StrategySpec(min_duration_s=10),
    )

    def no_engine(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("没有旁白段的方案不该构造 TTS 引擎")

    monkeypatch.setattr(pipeline, "create_tts", no_engine)
    assert pipeline.synthesize_narration_texts(silent, {}, tmp_path / "tts") == silent
