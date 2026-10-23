"""成片逐句时间轴的地基：`export_plan` 交出**段序 → 成片偏移（秒）**。

为什么要它：`plan.timeline[].start/end` 是**源片集内时间**，`burn_subtitle` 烧的是
**段内相对 0→duration**（`api/export.py` 的文档串自己写着），两者都对不上成片时间。
偏移的唯一真相是 Phase B 的拼接清单——各段产物的**实测时长**累加，与
`_audit_film_duration` 的分母同源。量不到就不回调：宁缺毋假，界面宁可显示
「本条没有逐句时间轴」也不许拿声明窗口猜观众看到的位置。

sink 默认 `None`＝现行为逐字节不变（既有 `_concat` 测试替身与调用点零波及）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import probe as probe_mod

_DURATION_BY_NAME = {"seg_000.mp4": 10.0, "seg_001.mp4": 5.5, "seg_002.mp4": 3.0}


def _plan(tmp_path: Path, count: int = 3) -> tuple[PlanData, dict[str, str]]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=10.0, audio="original")
            for _ in range(count)
        ],
    )
    return plan, {"ep1": str(source)}


def _export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    sink: Any = None,
    count: int = 3,
    probe_raises: bool = False,
) -> list[int]:
    """跑 export_plan，桩掉切割与 concat，返回 probe 被问过的次数（按调用计数）。"""
    plan, sources = _plan(tmp_path, count)
    calls: list[int] = []

    def _fake_cut(args: list[str], *_a: Any, **_k: Any) -> None:
        Path(args[-1]).write_bytes(b"seg")

    def _fake_concat(files: list[Path], target: Path) -> None:
        Path(target).write_bytes(b"film")

    def _fake_probe(path: Path) -> probe_mod.MediaInfo:
        calls.append(1)
        if probe_raises:
            raise ValueError("ffprobe 挂了")
        return probe_mod.MediaInfo(
            duration_s=_DURATION_BY_NAME[path.name],
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=True,
        )

    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(encoder, "_run_cut", _fake_cut)
    monkeypatch.setattr(encoder, "_concat", _fake_concat)
    monkeypatch.setattr(encoder.ffprobe_mod, "probe", _fake_probe)
    encoder.export_plan(
        plan, sources, tmp_path / "out.mp4", tmp_path / "work",
        parallel=1, segment_offsets_sink=sink,
    )
    return calls


def test_sink_receives_cumulative_measured_offsets_in_manifest_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """偏移＝前序段实测和：10.0 与 5.5 → 第三段起于 15.5，而不是声明窗口之和。

    外层只准有一次回调：统一重跑（`_UniformCodecRetry`）在 concat 前就抛，
    成功轮只跑一次——多交一份会让上层写出两遍时间轴。
    """
    seen: list[list[tuple[int, float]]] = []
    _export(monkeypatch, tmp_path, sink=seen.append)
    assert seen == [[(0, 0.0), (1, 10.0), (2, 15.5)]], f"实测偏移不对：{seen}"


def test_probe_failure_yields_no_offsets_rather_than_guessed_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """量不到＝不回调：偏移缺失由上层记成允许型降级，绝不拿声明时长凑一份假账。"""
    seen: list[list[tuple[int, float]]] = []
    _export(monkeypatch, tmp_path, sink=seen.append, probe_raises=True)
    assert seen == [], f"探测失败时不许交出偏移：{seen}"


def test_no_sink_means_no_extra_probing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认关＝现行为：不为时间轴多探一次盘（既有导出零波及）。"""
    calls = _export(monkeypatch, tmp_path, sink=None)
    assert calls == [], f"未请求偏移时不该探测：{calls}"
