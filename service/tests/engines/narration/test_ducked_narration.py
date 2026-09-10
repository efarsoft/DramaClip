"""旁白回填必须覆盖 narration 与 ducked 两类段，并显式记录段→旁白映射。

回归动机（两轴审查 B1）：`modes_w8` 把 `full_narration` 每一段都标成 `ducked`，
而 `pipeline` 的回填循环只认 `"narration"` —— 于是全片解说的段长与解说字幕
永不回填；导出侧再靠「第 N 条 narration 段」重推映射，`ducked` 一段也拿不到。
本文件锁死回填语义：两类角色都回填，且每段显式写下自己的 `narration_id`。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.models import ConflictScore

_TTS_DURATION_S = 1.25


class _StubTts:
    """落一个空文件即返回路径；时长探测已被打桩，不碰网络也不碰真音频。"""

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


class _BrokenTts:
    """云端不可达：每次合成都抛错，走回填的失败降级分支。"""

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        raise RuntimeError("云端不可达")


def _plan(roles: list[str]) -> PlanData:
    """按角色序列造一条等长旁白文案的编排（下标即文案 id 尾号）。"""
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=float(i), end=float(i) + 1.0, audio=role)
            for i, role in enumerate(roles)
        ],
        narration_texts=[
            NarrationText(id=f"n{i}", text=f"旁白{i}") for i in range(len(roles))
        ],
    )


def _stub_tts(monkeypatch: pytest.MonkeyPatch, duration: float | None) -> None:
    """桩的两个落点以 pipeline 顶部 import 行为准：模块级 create_tts、tts_base 探测。"""
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: duration)


def _broken_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _BrokenTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: None)


def test_ducked_segments_get_backfilled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    result = pipeline.synthesize_narration_texts(
        _plan(["ducked", "ducked"]), {"tts.engine": "edge"}, tmp_path
    )
    assert [segment.narration_id for segment in result.timeline] == ["n0", "n1"]
    assert [segment.subtitle_text for segment in result.timeline] == ["旁白0", "旁白1"]
    assert [segment.end - segment.start for segment in result.timeline] == [
        _TTS_DURATION_S,
        _TTS_DURATION_S,
    ]
    assert [segment.audio for segment in result.timeline] == ["ducked", "ducked"]


def test_original_segments_are_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """原声段不该被牵走旁白：既无 id 也不改时长与字幕。"""
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    result = pipeline.synthesize_narration_texts(
        _plan(["original", "ducked"]), {"tts.engine": "edge"}, tmp_path
    )
    assert [segment.narration_id for segment in result.timeline] == [None, "n0"]
    assert result.timeline[0].end - result.timeline[0].start == 1.0
    assert result.timeline[0].subtitle_text is None


def test_alternating_roles_map_to_owning_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """原声/旁白交替（cross_narration）：旁白必须落在第 1、3 段，且取到自己的文案。"""
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    result = pipeline.synthesize_narration_texts(
        _plan(["original", "narration", "original", "narration"]),
        {"tts.engine": "edge"},
        tmp_path,
    )
    assert [segment.narration_id for segment in result.timeline] == [None, "n0", None, "n1"]
    assert [segment.audio for segment in result.timeline] == [
        "original", "narration", "original", "narration",
    ]
    assert result.timeline[1].subtitle_text == "旁白0"
    assert result.timeline[3].subtitle_text == "旁白1"


def test_failed_tts_falls_back_and_clears_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """合成失败 → 段回退原声，且不得留下会错配的 narration_id 与残留字幕。"""
    _broken_tts(monkeypatch)
    result = pipeline.synthesize_narration_texts(
        _plan(["narration", "ducked"]), {"tts.engine": "edge"}, tmp_path
    )
    for segment in result.timeline:
        assert segment.audio == "original"
        assert segment.narration_id is None
        assert segment.subtitle_text is None
    assert result.narration_texts == [], "无音频的文案不回填进 plan_data"


def test_stale_id_cleared_when_later_synthesis_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """重跑回填（重试语义）：本次失败的段必须清掉上一轮写下的 id，不能留陈旧映射。"""
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    first = pipeline.synthesize_narration_texts(
        _plan(["ducked"]), {"tts.engine": "edge"}, tmp_path
    )
    assert first.timeline[0].narration_id == "n0"

    _broken_tts(monkeypatch)
    second = pipeline.synthesize_narration_texts(first, {"tts.engine": "edge"}, tmp_path)
    assert second.timeline[0].narration_id is None
    assert second.timeline[0].audio == "original"


def test_full_narration_plan_maps_every_segment_to_own_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真实 full_narration 编排（build_full 产出的全 ducked 时间轴）逐段配到自己的旁白。"""
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    scenes = [
        ConflictScore(scene_index=index, start=index * 12.0, end=index * 12.0 + 10.0, score=score)
        for index, score in enumerate([60, 85, 45, 90, 55, 75, 40, 95, 50, 65])
    ]
    plan = build_full("ep1", scenes, StrategySpec(min_duration_s=10, max_duration_s=120), "透视眼")
    result = pipeline.synthesize_narration_texts(plan, {"tts.engine": "edge"}, tmp_path)

    assert len(result.timeline) > 1, "本用例要多段才有意义"
    assert [segment.narration_id for segment in result.timeline] == [
        text.id for text in result.narration_texts
    ]
    assert all(segment.audio == "ducked" for segment in result.timeline)
    assert all(segment.subtitle_text for segment in result.timeline)
    assert [round(segment.end - segment.start, 3) for segment in result.timeline] == [
        _TTS_DURATION_S
    ] * len(result.timeline)


def test_backfilled_plan_still_round_trips_through_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """plan_data 落库/读库后映射不丢（导出层读的是库里的那份）。"""
    _stub_tts(monkeypatch, _TTS_DURATION_S)
    result = pipeline.synthesize_narration_texts(
        _plan(["ducked", "narration"]), {"tts.engine": "edge"}, tmp_path
    )
    reloaded = PlanData.model_validate(result.model_dump())
    assert [segment.narration_id for segment in reloaded.timeline] == ["n0", "n1"]
    assert [type(segment).__name__ for segment in result.timeline] == [
        "TimelineSegment",
        "TimelineSegment",
    ], "回填后的 plan 必须是校验过的模型，不能是裸 dict"
