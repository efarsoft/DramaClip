"""C1 后台预合成：`presynthesize_plan_audio` 的管线层契约。

与导出合成走同一 `_EnginePool`、同一 work_dir、同一内容寻址键——价值主张只有
一句话：**预热过的方案出片时真引擎一次都不调**。失败只留痕不抛、取消静默返回、
空方案零动作三条纪律也在这里钉死。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration import synthesis as synthesis
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    TimelineSegment,
)
from tests.tts_stub import write_audio

_DURATION_S = 1.25
_SOURCE = {"ep1": 120.0}


class _CountingTts:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        self.calls.append(text)
        write_audio(out_path, text.encode("utf-8"))
        return out_path


class _BoomTts:
    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        raise RuntimeError("引擎炸了")


def _plan(*texts: str) -> PlanData:
    items = [NarrationText(id=f"n{i}", text=text) for i, text in enumerate(texts)]
    timeline = [
        TimelineSegment(
            episode_id="ep1",
            start=i * 10.0,
            end=i * 10.0 + 8.0,
            audio="narration",
            narration_id=f"n{i}",
        )
        for i in range(len(texts))
    ]
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=items)


def _stub(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: engine)
    # 导出全链要读时长；替身 wav 不进 ffprobe，与 test_tts_cache 同款桩
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: _DURATION_S)


def _warm(
    plan: PlanData,
    tts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: Any,
    *,
    cancel: threading.Event | None = None,
    settings: dict[str, str] | None = None,
) -> tuple[int, int]:
    return pipeline.presynthesize_plan_audio(
        plan,
        dict(settings or {"tts.engine": "edge"}),
        tts_dir,
        cancel=cancel,
    )


def test_warmed_plan_exports_without_touching_the_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """核心契约：预热过的方案走完整导出合成，真引擎零调用。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    plan = _plan("开场一句话", "转折一句话")

    warmed, total = _warm(plan, tts_dir, monkeypatch, engine)
    assert (warmed, total) == (2, 2)
    assert len(engine.calls) == 2

    # 同一 plan + 同一目录走导出全链（配音→回填→时长），不再调引擎
    voiced = pipeline.synthesize_narration_texts(
        plan, {"tts.engine": "edge"}, tts_dir, source_durations=_SOURCE
    )
    assert len(engine.calls) == 2, "预热命中后导出不得再调真引擎"
    for item in voiced.narration_texts:
        assert item.audio_path, "导出后 audio_path 必须落位"


def test_pause_when_yields_between_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """逐段让位（导出开跑即停）：首段备完即 break，返回值不区分停因。"""
    engine = _CountingTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"
    warmed_one = {"done": False}

    def _pause_after_first() -> bool:
        return warmed_one["done"]

    class _FlaggingTts(_CountingTts):
        def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
            path = super().synthesize(text, voice, out_path)
            warmed_one["done"] = True
            return path

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _FlaggingTts())
    warmed, total = pipeline.presynthesize_plan_audio(
        _plan("第一句", "第二句", "第三句"),
        {"tts.engine": "edge"},
        tts_dir,
        pause_when=_pause_after_first,
    )
    assert (warmed, total) == (1, 3), "让位即停：已备段保留，剩余段出片时照常真合成"


def test_presynth_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """预热失败只留痕：不许把一个成功的规划反咬成失败。"""
    engine = _BoomTts()
    _stub(monkeypatch, engine)
    logs: list[tuple[str, str]] = []
    warmed, total = pipeline.presynthesize_plan_audio(
        _plan("这句话", "那句话"),
        {"tts.engine": "edge"},
        tmp_path / "tts",
        log=lambda level, message: logs.append((level, message)),
    )
    assert (warmed, total) == (0, 2)
    assert any("预合成 n0 失败" in msg for _level, msg in logs)
    assert all(level == "warn" for level, _msg in logs)


def test_cancel_stops_quietly_between_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """取消静默返回不抛：已预热段保留，作业层落「部分完成」话术。"""
    cancel = threading.Event()

    class _CancelAfterFirstTts(_CountingTts):
        def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
            path = super().synthesize(text, voice, out_path)
            cancel.set()
            return path

    engine = _CancelAfterFirstTts()
    _stub(monkeypatch, engine)
    tts_dir = tmp_path / "tts"

    warmed, total = pipeline.presynthesize_plan_audio(
        _plan("第一句", "第二句", "第三句"),
        {"tts.engine": "edge"},
        tts_dir,
        cancel=cancel,
    )
    assert warmed == 1, "取消前的段要算已预热"
    assert total == 3


def test_empty_plan_is_a_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """纯台词批（无旁白）零动作：连引擎都不构造。"""
    built: list[str] = []

    def _tracking_create(*args: Any, **kwargs: Any) -> _CountingTts:
        built.append("built")
        return _CountingTts()

    monkeypatch.setattr(synthesis, "create_tts", _tracking_create)
    plan = _plan()
    plan.narration_texts = []
    warmed, total = pipeline.presynthesize_plan_audio(
        plan, {"tts.engine": "edge"}, tmp_path / "tts"
    )
    assert (warmed, total) == (0, 0)
    assert built == [], "空方案不该构造引擎"
