"""响度影子读数（v3 成绩单）：导出链 loudness.py 复核门禁已硬失败守门，成绩单
只记归一后的复核实测做历史账——三钉：正常读数/量不到发灰/未配目标不触测量。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.exporter import loudness, selfcheck


@pytest.fixture()
def measurement() -> loudness.LoudnessMeasurement:
    return loudness.LoudnessMeasurement(
        integrated_lufs=-14.6,
        true_peak_dbtp=-1.2,
        lra=8.4,
        threshold=-24.3,
        offset_lu=0.0,
    )


def test_measured_reading_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, measurement: loudness.LoudnessMeasurement
) -> None:
    monkeypatch.setattr(
        loudness, "measure_integrated_lufs", lambda _p: measurement
    )
    row = selfcheck.check_loudness(tmp_path / "film.mp4", target=(-14.0, -1.5))
    assert row is not None
    assert row["status"] == "measured"
    assert row["measured_i"] == pytest.approx(-14.6)
    assert row["measured_tp"] == pytest.approx(-1.2)
    assert row["deviation_lu"] == pytest.approx(0.6)


def test_measure_error_reads_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """量不到（近乎无声/LoudnessError）写 None——诚实纪律，宁灰勿假数。"""

    def _boom(_p: Path) -> loudness.LoudnessMeasurement:
        raise loudness.LoudnessError("音轨近乎无声")

    monkeypatch.setattr(loudness, "measure_integrated_lufs", _boom)
    assert selfcheck.check_loudness(tmp_path / "film.mp4", target=(-14.0, -1.5)) is None


def test_no_target_skips_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配目标：None 且不触测量（哑弹断言证明未调用）。"""

    def _boom(_p: Path) -> loudness.LoudnessMeasurement:
        raise AssertionError("未配目标不应发起测量")

    monkeypatch.setattr(loudness, "measure_integrated_lufs", _boom)
    assert selfcheck.check_loudness(tmp_path / "film.mp4", target=None) is None


def test_run_payload_carries_loudness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, measurement: loudness.LoudnessMeasurement
) -> None:
    """run 接线影子验证：payload 带 loudness 项、version 升 3——其余项走既有灰态
    路径（不传可选样本），此处只盯新项形状。"""
    monkeypatch.setattr(loudness, "measure_integrated_lufs", lambda _p: measurement)
    # measure_audio_video 真解码太贵：monkeypatch 成零成本假读数
    monkeypatch.setattr(
        selfcheck, "measure_audio_video", lambda *_a, **_k: (-70.0, None)
    )
    payload = selfcheck.run(
        tmp_path / "film.mp4",
        measured_s=60.0,
        has_audio=True,
        mode="raw_clip",
        budget_s=None,
        planned_segments=None,
        segment_count=0,
        loudness_target=(-14.0, -1.5),
    )
    assert payload["version"] == 4
    row = payload["loudness"]
    assert row is not None and row["status"] == "measured"
    assert row["deviation_lu"] == pytest.approx(0.6)
