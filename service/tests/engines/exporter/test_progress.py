"""B3b 段内进度平滑：export_plan 把 runner 的 -progress 段内比例接进 on_progress。

调研②（两家）：ffmpeg `-progress pipe:1` 解析 out_time 得段内真实编码百分比，
解决单段大文件时进度条长时间冻结。runner.run 已具备该能力
（on_progress + total_duration_s → 自动加 -progress pipe:1 -nostats，见 test_runner）；
本文件钉的是 encoder.export_plan 那一段接线：

    总进度 = (已完成段 + 当前段内比例) / 总段数 × 90

且必须单调不减（Phase A 并行 2 段，收集序与完成序不同，逐段 max 钳住回退）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _two_segment_plan(tmp_path: Path) -> tuple[PlanData, dict[str, str]]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=10.0, audio="original"),
            TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original"),
        ],
    )
    return plan, {"ep1": str(source)}


def _run_export_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_cut: Any,
    *,
    parallel: int = 1,
) -> list[tuple[float, str]]:
    plan, sources = _two_segment_plan(tmp_path)
    # 切点抖动会挪 start/end（rng 未播种），钉死恒等以让期望时长可断言
    monkeypatch.setattr(
        encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e)
    )
    monkeypatch.setattr(encoder, "_run_cut", fake_cut)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    seen: list[tuple[float, str]] = []
    encoder.export_plan(
        plan,
        sources,
        tmp_path / "out.mp4",
        tmp_path / "work",
        on_progress=lambda p, m: seen.append((p, m)),
        parallel=parallel,
    )
    return seen


def test_run_cut_receives_expected_segment_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每段切割必须把预期段时长传下去，runner 才能把 out_time 换算成 0-1 比例。"""
    durations: list[float | None] = []
    progress_args: list[Any] = []

    def fake_cut(args: list[str], cancel: Any = None, **kwargs: Any) -> None:
        durations.append(kwargs.get("total_duration_s"))
        progress_args.append(kwargs.get("on_progress"))

    _run_export_plan(monkeypatch, tmp_path, fake_cut)
    assert durations == [pytest.approx(10.0), pytest.approx(5.0)], (
        f"段预期时长按时间轴声明（变速 ≤0.4% 忽略）：{durations}"
    )
    assert all(callable(cb) for cb in progress_args), "每段都要挂段内进度回调"


def test_intra_segment_progress_smooths_the_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """段内 50% 必须反映到总进度：不再只在整段完成时跳一格。"""

    def fake_cut(args: list[str], cancel: Any = None, **kwargs: Any) -> None:
        cb = kwargs.get("on_progress")
        if cb is not None:
            cb(0.5)

    seen = _run_export_plan(monkeypatch, tmp_path, fake_cut)
    percents = [p for p, _ in seen]
    # 段0 内 50%：(0.5+0)/2*90 = 22.5 —— 旧行为（只在段完成时报）里不存在这个值
    assert any(abs(p - 22.5) < 0.01 for p in percents), f"段内比例没接进总进度：{seen}"
    # 段1 内 50%：(1+0.5)/2*90 = 67.5
    assert any(abs(p - 67.5) < 0.01 for p in percents), f"第二段段内比例缺失：{seen}"
    assert percents == sorted(percents), f"进度必须单调不减：{percents}"
    assert seen[-1] == (100.0, "导出完成")


def test_progress_monotonic_under_parallel_cuts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并行 2 段、乱序报比例：收集序与完成序不同也不许回退。"""
    calls: list[float] = []

    def fake_cut(args: list[str], cancel: Any = None, **kwargs: Any) -> None:
        cb = kwargs.get("on_progress")
        calls.append(1.0)
        if cb is not None:
            # 第一段先报高比例，第二段低比例后到——sum 只增，仍须单调
            cb(0.9 if len(calls) == 1 else 0.2)

    seen = _run_export_plan(monkeypatch, tmp_path, fake_cut, parallel=2)
    percents = [p for p, _ in seen]
    assert percents == sorted(percents), f"并行下进度回退了：{percents}"


def test_no_on_progress_keeps_run_cut_kwargs_harmless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不给 on_progress（默认）：行为与现在完全一致，_run_cut 照常收 kwargs 不炸。"""
    plan, sources = _two_segment_plan(tmp_path)
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(encoder, "_run_cut", lambda *_a, **_k: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    out = encoder.export_plan(plan, sources, tmp_path / "out.mp4", tmp_path / "work")
    assert out == tmp_path / "out.mp4"
