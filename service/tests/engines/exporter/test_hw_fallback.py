"""A4-2 主编码运行时回退：硬编段失败→清半成品→libx264 重跑一次；cancelled/io/invalid 不回退。

「导出到 90% 崩」的成因之一：探测时编码器可用、真编某段时驱动挂/会话满。
回退是 best-effort 增强：重跑仍失败才抛；取消不是编码失败，不触发回退。
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import runner


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


def _export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_cut: Any,
    *,
    video_codec: str = "h264_nvenc",
    caplog: pytest.LogCaptureFixture | None = None,
) -> Path:
    plan, sources = _two_segment_plan(tmp_path)
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(encoder, "_run_cut", fake_cut)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    if caplog is not None:
        caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")
    return encoder.export_plan(
        plan,
        sources,
        tmp_path / "out.mp4",
        tmp_path / "work",
        video_codec=video_codec,
        parallel=1,
    )


def _attempts_by_seg(attempts: list[list[str]]) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for args in attempts:
        out.setdefault(args[-1], []).append(args)
    return out


def test_hw_failure_cleans_partial_and_retries_with_libx264(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    attempts: list[list[str]] = []
    cleaned_at_retry: list[bool] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        seg = Path(args[-1])
        is_retry = any(a[-1] == args[-1] for a in attempts)
        attempts.append(list(args))
        if not is_retry:
            seg.parent.mkdir(parents=True, exist_ok=True)
            seg.write_bytes(b"partial")  # 模拟硬编中途写坏的半成品
            raise runner.FfmpegError("Unknown encoder 'h264_nvenc'", kind="codec")
        cleaned_at_retry.append(not seg.exists())
        seg.write_bytes(b"ok")

    out = _export(monkeypatch, tmp_path, fake_cut, caplog=caplog)
    assert out == tmp_path / "out.mp4"
    per_seg = _attempts_by_seg(attempts)
    assert len(per_seg) == 2, "两段各自回退重跑一次"
    for seg_attempts in per_seg.values():
        assert len(seg_attempts) == 2, f"每段恰好两次尝试：{seg_attempts}"
        retry = " ".join(seg_attempts[1])
        assert "-c:v libx264" in retry, f"重跑必须换 libx264：{retry}"
        assert "-crf 20" in retry and "-preset veryfast" in retry, "重跑带软编质量参数"
        assert "-c:v h264_nvenc" in " ".join(seg_attempts[0])
    assert cleaned_at_retry == [True, True], "重跑前必须清掉半成品 seg_NNN.mp4"
    messages = [r.getMessage() for r in caplog.records]
    assert any("回退" in m for m in messages), f"回退必须留痕：{messages}"


def test_retry_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[list[str]] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        attempts.append(list(args))
        raise runner.FfmpegError("Unknown encoder", kind="codec")

    with pytest.raises(runner.FfmpegError):
        _export(monkeypatch, tmp_path, fake_cut)
    per_seg = _attempts_by_seg(attempts)
    seg_attempts = per_seg[min(per_seg)]  # parallel=1，第一段失败即抛
    assert len(seg_attempts) == 2, "硬编 + libx264 重跑各一次，重跑仍失败才抛"
    assert "-c:v libx264" in " ".join(seg_attempts[1])


def test_cancelled_error_does_not_trigger_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[list[str]] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        attempts.append(list(args))
        raise runner.FfmpegError("ffmpeg 已取消", cancelled=True)

    with pytest.raises(runner.FfmpegError) as excinfo:
        _export(monkeypatch, tmp_path, fake_cut)
    assert excinfo.value.cancelled
    assert not any("libx264" in " ".join(a) for a in attempts), "取消不是编码失败：不许回退重跑"


@pytest.mark.parametrize("kind", ["io", "invalid"])
def test_input_side_errors_do_not_trigger_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A4-3 分类接进回退决策：输入文件坏了/参数非法，换编码器重跑也没用，直接抛。"""
    attempts: list[list[str]] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        attempts.append(list(args))
        raise runner.FfmpegError("No such file or directory", kind=kind)

    with pytest.raises(runner.FfmpegError):
        _export(monkeypatch, tmp_path, fake_cut)
    assert not any("libx264" in " ".join(a) for a in attempts), f"kind={kind} 不该触发回退"


def test_unknown_kind_still_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分类不出来的失败（如超时被杀，stderr 空）按可回退处理——best-effort。"""
    attempts: list[list[str]] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        if not attempts:
            attempts.append(list(args))
            raise runner.FfmpegError("ffmpeg 退出码 1：")
        attempts.append(list(args))

    _export(monkeypatch, tmp_path, fake_cut)
    assert len(attempts) == 3, "段0 回退成功后段1 正常跑：1+1+1 次"
    assert "-c:v libx264" in " ".join(attempts[1])


def test_software_codec_failure_raises_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[list[str]] = []

    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        attempts.append(list(args))
        raise runner.FfmpegError("boom")

    with pytest.raises(runner.FfmpegError):
        _export(monkeypatch, tmp_path, fake_cut, video_codec="libx264")
    per_seg = _attempts_by_seg(attempts)
    assert all(len(v) == 1 for v in per_seg.values()), "本来就是 libx264，没有可回退的目标"


def test_args_with_codec_splices_params_only() -> None:
    args = encoder.cut_segment_args(
        "src.mp4", "seg.mp4", start=0, end=1, audio="original",
        tts_audio=None, rng=random.Random(0), video_codec="h264_nvenc",
    )
    swapped = encoder._args_with_codec(args, "libx264")
    joined = " ".join(swapped)
    assert "-c:v libx264 -preset veryfast -crf 20 -c:a aac" in joined
    assert "h264_nvenc" not in joined and "-cq 22" not in joined
    assert swapped[0] == args[0] and swapped[-1] == args[-1], "只动 -c:v..-c:a 之间"
