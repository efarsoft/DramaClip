"""engines.dedup：SRT 解析与保护区安全化。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.analysis.models import SpeechZone
from dramaclip.engines.dedup import jitter


def test_parse_srt_times_and_zones(tmp_path: Path) -> None:
    srt = tmp_path / "ep1.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\n你给我滚出去！\n\n"
        "2\n00:00:10,200 --> 00:00:12,000\n废物。\n",
        encoding="utf-8",
    )
    zones = jitter.parse_srt(srt)
    assert zones == [
        SpeechZone(start=1.0, end=3.5),
        SpeechZone(start=10.2, end=12.0),
    ]


def test_parse_srt_bad_file_returns_empty(tmp_path: Path) -> None:
    assert jitter.parse_srt(tmp_path / "missing.srt") == []


def test_safe_times_snaps_into_protection() -> None:
    zones = [SpeechZone(start=3.5, end=6.0)]
    # 入点落在台词中间、保护区起点在 1s 内 → snap 到保护区外（-0.2s）
    start, end = jitter.safe_times(3.7, 7.0, zones)
    assert start == 3.3
    assert end == 7.0


def test_safe_times_long_span_keeps_original() -> None:
    zones = [SpeechZone(start=2.0, end=6.0)]
    # 保护区起点距离入点 >1s：保持原切点（无上限会把 5s 切片吞成 40s+）
    start, end = jitter.safe_times(4.0, 7.0, zones)
    assert (start, end) == (4.0, 7.0)


def test_safe_end_extends_within_cap_only() -> None:
    # 出点在台词内、距段尾 0.45s → 顺延补完字尾
    assert jitter.safe_end(7.2, [SpeechZone(start=6.0, end=7.5)]) == 7.65
    # 连续对白超长 ASR 段：距段尾 10.15s → 保持原切点
    assert jitter.safe_end(7.0, [SpeechZone(start=2.0, end=17.0)]) == 7.0


def test_safe_times_too_short_falls_back() -> None:
    import random

    zones = [SpeechZone(start=2.0, end=6.0)]
    # 切点在保护区外的窄间隙：抖动后 <0.45s → 回退原值
    start, end = jitter.safe_times(6.5, 6.7, zones, rng=random.Random(1))
    assert (start, end) == (6.5, 6.7)


def test_srt_for_source_convention(tmp_path: Path) -> None:
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"x")
    assert jitter.srt_for_source(video) is None
    srt = tmp_path / "ep1.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    assert jitter.srt_for_source(video) == srt
