"""导出回执：硬编失败统一重跑后 actual=libx264、fallback=true、reason 非空。"""

from __future__ import annotations

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.infra import compute


def test_uniform_retry_reports_fallback(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    reports: list[compute.ComputeReport] = []

    def fake_once(
        _plan, _paths, out, _work, *, video_codec="libx264", _allow_uniform_retry=True, **_kw
    ):
        calls.append(video_codec)
        if _allow_uniform_retry:
            raise encoder._UniformCodecRetry()
        out.write_bytes(b"film")
        return out

    monkeypatch.setattr(encoder, "_export_plan_once", fake_once)
    path = encoder.export_plan(
        type("Plan", (), {"timeline": [object()], "mode": "intro"})(),
        {},
        tmp_path / "out.mp4",
        tmp_path,
        video_codec="h264_nvenc",
        compute_sink=reports.append,
        encoder_requested="auto",
    )
    assert path.is_file()
    assert calls == ["h264_nvenc", "libx264"]
    report = reports[0]
    assert (report.requested, report.actual, report.fallback) == ("auto", "libx264", True)
    assert report.reason


def test_hardware_success_reports_the_codec_that_encoded(monkeypatch, tmp_path) -> None:
    reports: list[compute.ComputeReport] = []

    def fake_once(_plan, _paths, out, _work, **_kw):
        out.write_bytes(b"film")
        return out

    monkeypatch.setattr(encoder, "_export_plan_once", fake_once)
    encoder.export_plan(
        type("Plan", (), {"timeline": [object()], "mode": "intro"})(),
        {},
        tmp_path / "out.mp4",
        tmp_path,
        video_codec="h264_nvenc",
        compute_sink=reports.append,
        encoder_requested="auto",
    )
    report = reports[0]
    assert (report.resolved, report.actual, report.fallback) == (
        "h264_nvenc",
        "h264_nvenc",
        False,
    )
    compute.assert_success(report)


def test_first_attempt_does_not_emit_a_receipt(monkeypatch, tmp_path) -> None:
    """导出一半失败（非回退）不得先出成功回执：账只落终态。"""
    reports: list[compute.ComputeReport] = []

    def fake_once(_plan, _paths, _out, _work, **_kw):
        raise RuntimeError("编码器挂了")

    monkeypatch.setattr(encoder, "_export_plan_once", fake_once)
    with pytest.raises(RuntimeError):
        encoder.export_plan(
            type("Plan", (), {"timeline": [object()], "mode": "intro"})(),
            {},
            tmp_path / "out.mp4",
            tmp_path,
            video_codec="h264_nvenc",
            compute_sink=reports.append,
            encoder_requested="cuda",
        )
    assert reports == []


def test_cpu_line_reports_libx264_without_fallback(monkeypatch, tmp_path) -> None:
    reports: list[compute.ComputeReport] = []

    def fake_once(_plan, _paths, out, _work, **_kw):
        out.write_bytes(b"film")
        return out

    monkeypatch.setattr(encoder, "_export_plan_once", fake_once)
    encoder.export_plan(
        type("Plan", (), {"timeline": [object()], "mode": "intro"})(),
        {},
        tmp_path / "out.mp4",
        tmp_path,
        video_codec="libx264",
        compute_sink=reports.append,
        encoder_requested="cpu",
    )
    report = reports[0]
    assert (report.requested, report.actual, report.fallback) == ("cpu", "libx264", False)
    compute.assert_success(report)
