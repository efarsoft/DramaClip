"""A4-1 硬编探测：平台候选序 + 同形状质量参数 + 15s 超时 + 会话级缓存选中编码器名。

探针必须带**与正式合成同形状**的质量参数（不能只 -f null）：否则「编码器列表里有、
真编挂掉」（驱动残缺/会话数满）探不出来，导出到 90% 才崩。
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.infra.ffmpeg import runner


@pytest.fixture(autouse=True)
def _reset_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试从「未探测」状态开始；monkeypatch 负责还原全局缓存。"""
    monkeypatch.setattr(encoder, "_HW_ENCODER_CACHE", None)


def _stub_run_cut(
    monkeypatch: pytest.MonkeyPatch, fail: set[str]
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """桩掉 _run_cut：记录每次调用的 args/kwargs；-c:v 落在 fail 集里就抛。"""
    seen_args: list[list[str]] = []
    seen_kwargs: list[dict[str, Any]] = []

    def fake_run_cut(args: list[str], cancel: Any = None, **kwargs: Any) -> None:
        seen_args.append(list(args))
        seen_kwargs.append(kwargs)
        codec = args[args.index("-c:v") + 1]
        if codec in fail:
            raise runner.FfmpegError(f"Unknown encoder {codec}", kind="codec")

    monkeypatch.setattr(encoder, "_run_cut", fake_run_cut)
    return seen_args, seen_kwargs


def test_candidate_order_by_platform() -> None:
    assert encoder._hw_candidates("win32") == ["h264_nvenc", "h264_qsv"]
    assert encoder._hw_candidates("darwin") == ["h264_videotoolbox"]
    assert encoder._hw_candidates("linux") == ["h264_nvenc", "h264_qsv"]


def test_probe_encodes_black_frame_with_production_params_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc"])
    seen_args, seen_kwargs = _stub_run_cut(monkeypatch, fail=set())

    assert encoder.pick_hw_encoder() == "h264_nvenc"
    probe = seen_args[0]
    assert "color=black:s=256x256:d=0.1" in probe, "0.1s 黑帧真试编"
    assert probe[-3:] == ["-f", "null", "-"], "探针不落盘（-f null 必须带输出目标）"
    prod = encoder._video_codec_params("h264_nvenc")
    assert prod == ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "22"]
    i = probe.index("-c:v")
    assert probe[i + 2 : i + 2 + len(prod)] == prod, "探针必须带正式合成的同形状质量参数"
    assert seen_kwargs[0].get("timeout_s") == pytest.approx(15.0), "驱动挂起要有 15s 兜底"


@pytest.mark.parametrize("codec", ["h264_nvenc", "h264_qsv", "h264_videotoolbox"])
def test_probe_params_identical_to_cut_params(codec: str) -> None:
    """探针与正式段编码读**同一处**质量参数构造——一处改了另一处必须跟着变。"""
    cut = encoder.cut_segment_args(
        "src.mp4", "seg.mp4", start=0, end=1, audio="original",
        tts_audio=None, rng=random.Random(0), video_codec=codec,
    )
    prod = cut[cut.index("-c:v") + 1 : cut.index("-c:a")]
    probe = encoder._hw_probe_args(codec)
    tail = probe[probe.index("-c:v") + 1 :]
    assert prod == [codec, *encoder._video_codec_params(codec)]
    assert tail[: len(prod)] == prod, f"{codec} 探针参数与正式合成不同形状"


def test_first_working_encoder_selected_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_qsv"]
    )
    seen_args, _ = _stub_run_cut(monkeypatch, fail={"h264_nvenc"})

    assert encoder.pick_hw_encoder() == "h264_qsv"
    assert len(seen_args) == 2, "nvenc 失败后必须继续试 qsv"
    assert encoder.pick_hw_encoder() == "h264_qsv"
    assert len(seen_args) == 2, "会话级缓存：不许二次真编"


def test_all_candidates_fail_returns_none_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_qsv"]
    )
    seen_args, _ = _stub_run_cut(monkeypatch, fail={"h264_nvenc", "h264_qsv"})

    assert encoder.pick_hw_encoder() is None
    assert encoder.nvenc_available() is False, "旧签名兼容：无硬编时仍返回 False"
    assert len(seen_args) == 2, "失败结果同样缓存，不反复真编"


def test_nvenc_available_true_is_bool_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc"])
    _stub_run_cut(monkeypatch, fail=set())
    assert encoder.nvenc_available() is True


def test_probe_crash_swallowed_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """探测自身的任何异常（OSError/驱动崩）都按不可用处理，绝不外抛。"""
    monkeypatch.setattr(encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc"])

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("驱动挂起")

    monkeypatch.setattr(encoder, "_run_cut", boom)
    assert encoder.pick_hw_encoder() is None
