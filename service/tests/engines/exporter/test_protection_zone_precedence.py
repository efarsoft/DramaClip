"""切点保护区取源优先级：同名 .srt（手工字幕）胜过库内 ASR。

规约：「同名 .srt 优先（尊重手工字幕文件），缺失回退库内 ASR」
（docs/01-技术方案-原案 7.1、docs/06-经验参数表 §1、jitter 模块 docstring）。
手工放置的 .srt 通常是人工校对过的权威文本，而库内 ASR 在本项目里会繁简混排、
断句错位，用它覆盖手工文件等于把用户成果丢掉。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment

_ASR_ZONES = [SpeechZone(start=20.0, end=24.0)]


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    return source


def _plan(source_start: float = 1.0, source_end: float = 3.0) -> PlanData:
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=source_start, end=source_end, audio="original")
        ],
    )


def _zones_seen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, dialogue_zones: dict[str, list[SpeechZone]]
) -> list[tuple[float, float]]:
    """跑一遍 export_plan 的 Phase A 建令阶段，记录真正喂给 safe_times 的保护区。"""
    seen: list[tuple[float, float]] = []

    def _capture(
        start: float, end: float, zones: list[SpeechZone], **_kw: Any
    ) -> tuple[float, float]:
        seen.extend((zone.start, zone.end) for zone in zones)
        return start, end

    monkeypatch.setattr(encoder.jitter, "safe_times", _capture)
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)
    monkeypatch.setattr(encoder, "_concat", lambda _files, _out: None)
    encoder.export_plan(
        _plan(), {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", tmp_path / "work",
        dialogue_zones=dialogue_zones,
    )
    return seen


def test_manual_srt_wins_over_stored_asr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = _source(tmp_path)
    source.with_suffix(".srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n手工字幕\n", encoding="utf-8"
    )
    assert _zones_seen(monkeypatch, tmp_path, dialogue_zones={"ep1": list(_ASR_ZONES)}) == [
        (1.0, 2.0)
    ], "手工 .srt 被库内 ASR 覆盖 → 用户校对结果被静默丢弃"


def test_stored_asr_used_when_no_srt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """没有手工文件时回退库内 ASR（B4 接线不得因此退化）。"""
    _source(tmp_path)
    assert _zones_seen(monkeypatch, tmp_path, dialogue_zones={"ep1": list(_ASR_ZONES)}) == [
        (20.0, 24.0)
    ]


def test_empty_when_neither_source_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _source(tmp_path)
    assert _zones_seen(monkeypatch, tmp_path, dialogue_zones={}) == []
