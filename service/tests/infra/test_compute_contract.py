"""compute 契约：回执形状、回退不变量、显式 cuda 的硬门。"""

from __future__ import annotations

import pytest

from dramaclip.infra import compute


def test_normalize_requested_defaults_to_auto() -> None:
    assert compute.normalize_requested(None) == "auto"
    assert compute.normalize_requested("") == "auto"
    assert compute.normalize_requested(" CUDA ") == "cuda"
    with pytest.raises(ValueError):
        compute.normalize_requested("gpu")


def test_fallback_requires_tried_cuda_and_reason() -> None:
    with pytest.raises(ValueError):
        compute.ComputeReport(
            component="asr.whisper", requested="auto", resolved="cuda",
            actual="cpu", fallback=True, reason="",
        )
    report = compute.ComputeReport(
        component="asr.whisper", requested="auto", resolved="cuda",
        actual="cpu", fallback=True, reason="cublas 缺失",
    )
    assert report.device == "cpu"


def test_unsupported_is_not_a_fallback() -> None:
    report = compute.unsupported("asr.whisper", "auto", "CT2 需要 sm_61")
    assert (report.resolved, report.actual, report.fallback) == ("cpu", "cpu", False)
    assert "sm_61" in report.reason


def test_explicit_cuda_success_requires_actual_cuda() -> None:
    bad = compute.ComputeReport(
        component="tts.kokoro", requested="cuda", resolved="cuda", actual="cpu",
        reason="静默回退",
    )
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(bad)


def test_success_rejects_unknown_but_accepts_video_codec() -> None:
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="asr.whisper", requested="auto", resolved="cpu", actual="unknown",
        ))
    report = compute.ComputeReport(
        component="video.encode", requested="auto", resolved="h264_nvenc",
        actual="h264_nvenc",
    )
    compute.assert_success(report)
    assert report.device == "h264_nvenc"


def test_video_encode_fallback_is_a_visible_software_retry() -> None:
    """视频编码的段级回退是既有可用性保护：允许，但必须带非空原因且落在 libx264。"""
    report = compute.ComputeReport(
        component="video.encode", requested="auto", resolved="h264_nvenc",
        actual="libx264", fallback=True, reason="第 2 段硬编失败，整片统一 libx264 重跑",
    )
    compute.assert_success(report)
    assert report.device == "libx264"
    with pytest.raises(ValueError):
        compute.ComputeReport(
            component="video.encode", requested="auto", resolved="h264_nvenc",
            actual="libx264", fallback=True, reason=" ",
        )


def test_video_encode_codec_swap_without_fallback_is_a_breach() -> None:
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="video.encode", requested="auto", resolved="h264_nvenc",
            actual="libx264",
        ))


def test_video_encode_cpu_line_must_stay_on_libx264() -> None:
    compute.assert_success(compute.ComputeReport(
        component="video.encode", requested="cpu", resolved="libx264", actual="libx264",
    ))
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="video.encode", requested="cpu", resolved="libx264", actual="h264_nvenc",
        ))


def test_cloud_ignores_local_requested() -> None:
    report = compute.cloud("tts.cloud", requested="cuda")
    assert (report.resolved, report.actual, report.fallback) == ("cloud", "cloud", False)
    compute.assert_success(report)


def test_cpu_request_cannot_resolve_cuda() -> None:
    with pytest.raises(ValueError):
        compute.ComputeReport(
            component="asr.funasr", requested="cpu", resolved="cuda", actual="cuda",
        )
