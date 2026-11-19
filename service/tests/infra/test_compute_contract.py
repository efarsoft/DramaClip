"""compute 契约：回执形状、回退不变量、显式承诺的硬门。

词汇（2026-11-19 裁决）：用户词汇 auto/gpu/cpu；cuda/xpu/dml 是后端钉子，
cuda 兼作设置表存量值的遗留别名（归一时映射 gpu）。
"""

from __future__ import annotations

import pytest

from dramaclip.infra import compute


def test_normalize_requested_defaults_to_auto() -> None:
    assert compute.normalize_requested(None) == "auto"
    assert compute.normalize_requested("") == "auto"
    assert compute.normalize_requested(" GPU ") == "gpu"
    with pytest.raises(ValueError):
        compute.normalize_requested("npu")


def test_legacy_cuda_alias_normalizes_to_gpu() -> None:
    """设置表存量值 cuda：归一为 gpu（承诺语义跟随 gpu，线路由解析层给真值）。"""
    assert compute.normalize_requested("cuda") == "gpu"
    assert compute.normalize_requested(" CUDA ") == "gpu"


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


def test_explicit_gpu_success_requires_a_gpu_line() -> None:
    bad = compute.ComputeReport(
        component="tts.kokoro", requested="gpu", resolved="cuda", actual="cpu",
        reason="静默回退",
    )
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(bad)


def test_gpu_promise_fulfilled_by_any_gpu_line() -> None:
    """gpu 承诺不钉死后端：N 卡机兑现 cuda、Arc 机兑现 xpu/dml 都算兑现。"""
    for actual in ("cuda", "xpu", "dml"):
        compute.assert_success(compute.ComputeReport(
            component="asr.funasr", requested="gpu", resolved=actual, actual=actual,
        ))


def test_backend_pins_are_strict() -> None:
    """xpu/dml/cuda 钉子：请求具体后端就兑现具体后端（门禁钉线路用）。"""
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="asr.funasr", requested="xpu", resolved="dml", actual="dml",
        ))
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="asr.funasr", requested="dml", resolved="xpu", actual="xpu",
        ))
    compute.assert_success(compute.ComputeReport(
        component="asr.funasr", requested="xpu", resolved="xpu", actual="xpu",
    ))


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
    report = compute.cloud("tts.cloud", requested="gpu")
    assert (report.resolved, report.actual, report.fallback) == ("cloud", "cloud", False)
    compute.assert_success(report)


def test_cpu_request_cannot_resolve_gpu_lines() -> None:
    for line in ("cuda", "xpu", "dml"):
        with pytest.raises(ValueError):
            compute.ComputeReport(
                component="asr.funasr", requested="cpu", resolved=line, actual=line,
            )


def test_gpu_fallback_reports_like_auto() -> None:
    """dml 是解析结果：auto 下试 GPU 后落 CPU 照旧记账（承诺词汇不变式）。"""
    report = compute.ComputeReport(
        component="tts.separation", requested="auto", resolved="dml",
        actual="cpu", fallback=True, reason="DML session 失败",
    )
    assert report.device == "cpu"
    compute.assert_success(report)
