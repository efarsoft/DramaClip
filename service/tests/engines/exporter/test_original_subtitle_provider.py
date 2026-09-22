"""encoder.export_plan 的 original_subtitle_provider 接线（批次二·方案 B）。

原声段（audio=="original"）没有 subtitle_text，subtitle_burner 不会触发；
provider 按**实际切割窗口**（jitter 安全化之后的 safe_start/safe_end）给原声段
生成台词字幕 ass。narration/ducked 段与已有 subtitle_text 的段不走 provider。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _source(tmp_path: Path) -> str:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    return str(source)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan: PlanData,
    provider: Any,
    *,
    tts: dict[int, str] | None = None,
    burner: Any = None,
) -> list[tuple[int, list[str]]]:
    """跑 Phase A 建令 + 假切割，返回 [(段序, ffmpeg args)]。"""
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s + 0.5, e - 0.25))
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    calls: list[tuple[int, list[str]]] = []

    def fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        index = int(
            next(arg for arg in args if arg.endswith(".mp4") and "seg_" in arg)
            .split("seg_")[1][:3]
        )
        calls.append((index, args))

    monkeypatch.setattr(encoder, "_run_cut", fake_cut)
    encoder.export_plan(
        plan,
        {"ep1": _source(tmp_path)},
        tmp_path / "out.mp4",
        tmp_path / "work",
        subtitle_burner=burner,
        original_subtitle_provider=provider,
        tts_audio_by_segment=tts,
    )
    return sorted(calls, key=lambda item: item[0])


def test_provider_receives_the_jittered_cut_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """provider 拿到的是 safe_times 之后的真实窗口，不是时间轴声明值。

    词级裁剪按窗口重定基：拿声明值的话，抖动挪过切点的段字幕会整体错位。
    """
    plan = PlanData(
        mode="intro_narration",
        timeline=[TimelineSegment(episode_id="ep1", start=1.0, end=3.0, audio="original")],
    )
    seen: list[tuple[int, float, float]] = []

    def provider(index: int, win_start: float, win_end: float) -> None:
        seen.append((index, win_start, win_end))
        return None

    _run(monkeypatch, tmp_path, plan, provider)
    assert seen == [(0, pytest.approx(1.5), pytest.approx(2.75))]


def test_provider_result_is_wired_into_the_ass_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ass_file = tmp_path / "seg_000.ass"
    ass_file.write_text("[Script Info]\n", encoding="utf-8")
    plan = PlanData(
        mode="intro_narration",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    calls = _run(monkeypatch, tmp_path, plan, lambda *_a: str(ass_file))
    joined = " ".join(calls[0][1])
    assert "ass=" in joined and "seg_000.ass" in joined, f"provider 的 ass 没进滤镜链：{joined}"


def test_provider_returning_none_leaves_the_segment_without_subtitles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = PlanData(
        mode="intro_narration",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    calls = _run(monkeypatch, tmp_path, plan, lambda *_a: None)
    assert "ass=" not in " ".join(calls[0][1])


def test_provider_skips_narration_and_subtitled_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """narration/ducked 段（走 TTS 字幕）与已有 subtitle_text 的段都不进 provider。"""
    tts_audio = tmp_path / "tts.mp3"
    tts_audio.write_bytes(b"mp3")
    plan = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="narration",
                narration_id="n1", subtitle_text="解说词",
            ),
            TimelineSegment(
                episode_id="ep1", start=2.0, end=4.0, audio="original",
                subtitle_text="已有字幕",
            ),
            TimelineSegment(episode_id="ep1", start=4.0, end=6.0, audio="original"),
        ],
    )
    seen: list[int] = []
    burner_ass = tmp_path / "burn.ass"
    burner_ass.write_text("x", encoding="utf-8")

    def provider(index: int, _s: float, _e: float) -> None:
        seen.append(index)
        return None

    _run(
        monkeypatch,
        tmp_path,
        plan,
        provider,
        tts={0: str(tts_audio)},
        burner=lambda _i, _t, _d: str(burner_ass),
    )
    assert seen == [2], f"provider 只该看到无字幕的原声段：{seen}"


def test_no_provider_keeps_original_segments_subtitle_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """不传 provider（默认 None）：原声段照旧无字幕，行为与本批之前一致。"""
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    calls = _run(monkeypatch, tmp_path, plan, None)
    assert "ass=" not in " ".join(calls[0][1])
