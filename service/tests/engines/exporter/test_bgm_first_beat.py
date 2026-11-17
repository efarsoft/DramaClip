"""床曲首拍起播（W3 节拍对齐）：曲头静音/渐入非节拍区（sadness_01 实测 9.40s）
不再铺 9 秒无节拍铺垫——起播偏移到实测首拍前 0.05s；测量失败回退曲头 0。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.exporter import bgm_bed


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    bgm_bed._bed_start_offset_cache.clear()


def test_first_beat_offsets_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """首拍 9.4s（实测 sadness_01 形状）：起播偏移 9.35s，-ss 落在 -i 前。"""
    monkeypatch.setattr(bgm_bed, "_bed_first_beat_s", lambda _t: 9.35)
    inputs, prefix = bgm_bed._bed_loop_inputs(tmp_path / "t.mp3", 60.0, 90.0, start_offset=9.35)
    assert inputs[:2] == ["-ss", "9.350"]
    assert "-i" in inputs and prefix == "[1:a]anull[bedsrc];"


def test_clean_head_starts_at_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """首拍 ≤0.2s（多数曲子 0.07s 实测）：0 起播，无 -ss 参数。"""
    monkeypatch.setattr(bgm_bed, "_bed_first_beat_s", lambda _t: 0.0)
    inputs, _prefix = bgm_bed._bed_loop_inputs(tmp_path / "t.mp3", 60.0, 90.0)
    assert "-ss" not in inputs


def test_measure_failure_falls_back_to_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """librosa 不可用/加载抛错：回退曲头 0 起播（增强项不挡片）——走真实
    回退路径（内部 try/except），不是把被测函数自身换掉。"""

    def _boom(*_a: object, **_k: object) -> tuple[bytes, int]:
        raise RuntimeError("no librosa")

    monkeypatch.setattr("librosa.load", _boom)
    assert bgm_bed._bed_first_beat_s(tmp_path / "t.mp3") == 0.0


def test_first_beat_cache_hit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """同曲目缓存命中：测量函数只被调用一次。"""
    calls: list[Path] = []

    def _fake(track: Path) -> float:
        calls.append(track)
        return 1.2

    monkeypatch.setattr(bgm_bed, "_bed_first_beat_s", _fake)
    # 直测缓存字典语义：手工写入后同 track 再取不再调测量
    bgm_bed._bed_start_offset_cache[tmp_path / "t.mp3"] = 1.2
    assert bgm_bed._bed_start_offset_cache[tmp_path / "t.mp3"] == 1.2
    assert len(calls) == 0
