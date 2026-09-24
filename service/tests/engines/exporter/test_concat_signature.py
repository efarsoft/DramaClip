"""A4-2 Phase B 签名守卫：段流签名齐→-c copy；不齐/测不出→整体重编码；时长审计 warn。

回退段是 libx264、其余段是硬编时，concat -c copy 混拼不同流签名会出「导出到 90% 崩」。
ffmpeg/ffprobe 全用 monkeypatch 桩（不真跑），量的是命令形状与决策分支。
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _streams_json(
    codec: str = "h264", profile: str = "High", sar: str = "1:1"
) -> str:
    return json.dumps(
        {"streams": [{
            "codec_name": codec, "profile": profile, "level": 40,
            "pix_fmt": "yuv420p", "width": 1080, "height": 1920,
            "sample_aspect_ratio": sar,
        }]}
    )


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    signature_by_path: dict[Path, str] | None = None,
    sar_by_path: dict[Path, str] | None = None,
    probe_fail: bool = False,
) -> list[list[str]]:
    """桩掉 resolve_ffmpeg/ffprobe/subprocess.run/probe.probe，返回 ffmpeg 调用命令。"""
    monkeypatch.setattr(encoder, "resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(encoder, "resolve_ffprobe", lambda: "ffprobe")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        calls.append([str(part) for part in cmd])
        if cmd[0] == "ffprobe":
            if probe_fail:
                return _FakeCompleted(1, stderr="probe 挂了")
            target = Path(cmd[-1])
            return _FakeCompleted(
                0,
                stdout=_streams_json(
                    codec=(signature_by_path or {}).get(target, "h264"),
                    sar=(sar_by_path or {}).get(target, "1:1"),
                ),
            )
        return _FakeCompleted(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_probe(path: Path) -> Any:
        return encoder.ffprobe_mod.MediaInfo(
            duration_s=10.0, width=1080, height=1920, fps=30.0, has_audio=True
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", fake_probe)
    return calls


def _segments(tmp_path: Path, count: int = 2) -> list[Path]:
    files = []
    for index in range(count):
        seg = tmp_path / f"seg_{index:03d}.mp4"
        seg.write_bytes(b"seg")
        files.append(seg)
    return files


def test_uniform_signatures_keep_stream_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub(monkeypatch)
    segments = _segments(tmp_path)
    out = tmp_path / "out.mp4"
    encoder._concat(segments, out)
    ffmpeg_call = next(c for c in calls if c[0] == "ffmpeg")
    assert "-c" in ffmpeg_call and "copy" in ffmpeg_call, "签名齐必须保持 -c copy"
    assert "-crf" not in ffmpeg_call, "不许顺手重编码"


def test_mixed_signatures_force_reencode_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """回退段（libx264）混进硬编段：签名不齐→整体重编码 concat 而非 -c copy。"""
    segments = _segments(tmp_path)
    sig = {segments[0]: "h264", segments[1]: "mpeg4"}  # 模拟一段换了编码器
    calls = _stub(monkeypatch, signature_by_path=sig)
    caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")
    encoder._concat(segments, tmp_path / "out.mp4")
    ffmpeg_call = next(c for c in calls if c[0] == "ffmpeg")
    assert "copy" not in ffmpeg_call, "签名不齐不许流复制"
    assert "-c:v" in ffmpeg_call and "libx264" in ffmpeg_call, "整体重编码用 libx264"
    assert any("签名不齐" in r.getMessage() for r in caplog.records), "重编码要留痕"


def test_mixed_pixel_aspect_forces_reencode_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存储尺寸相同、像素比不同（setsar 修复前的旧段混进新段）：也算签名不齐。

    `-c copy` 混拼 SAR 不一致的段 = 播放器按首段横向拉伸整片，且完全静默；
    SAR 进签名后这种混合走整体重编码，把几何钉回一条。
    """
    segments = _segments(tmp_path)
    calls = _stub(monkeypatch, sar_by_path={segments[0]: "4:3", segments[1]: "1:1"})
    encoder._concat(segments, tmp_path / "out.mp4")
    ffmpeg_call = next(c for c in calls if c[0] == "ffmpeg")
    assert "copy" not in ffmpeg_call, "像素比不齐不许流复制"
    assert "-c:v" in ffmpeg_call and "libx264" in ffmpeg_call


def test_probe_failure_falls_back_to_reencode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """签名探测自身失败（ffprobe 挂）→保守走重编码，绝不因探测失败挡导出。"""
    calls = _stub(monkeypatch, probe_fail=True)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")
    ffmpeg_call = next(c for c in calls if c[0] == "ffmpeg")
    assert "copy" not in ffmpeg_call and "libx264" in ffmpeg_call


def test_single_segment_copy_bytes_still_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub(monkeypatch)
    seg = _segments(tmp_path, 1)[0]
    out = tmp_path / "out.mp4"
    encoder._concat([seg], out)
    assert out.read_bytes() == b"seg", "单段仍直接 copy bytes"
    assert not [c for c in calls if c[0] == "ffmpeg"], "单段不该起 ffmpeg"


def test_duration_audit_warns_on_large_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """concat 后时长审计：实测与段声明和差超 max(8%,3s) 阈值→warn 明账，不失败。"""
    _stub(monkeypatch)
    caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")
    durations = {"seg": 10.0, "out": 60.0}

    def fake_probe(path: Path) -> Any:
        return encoder.ffprobe_mod.MediaInfo(
            duration_s=durations["out" if path.name == "out.mp4" else "seg"],
            width=1080, height=1920, fps=30.0, has_audio=True,
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", fake_probe)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")  # 声明 20s，实测 60s
    assert any("时长审计" in r.getMessage() for r in caplog.records), "超阈值必须 warn"


def test_duration_audit_silent_within_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub(monkeypatch)  # 段 10s×2=20s，成片 10s→改让成片 20.5s
    caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")

    def fake_probe(path: Path) -> Any:
        return encoder.ffprobe_mod.MediaInfo(
            duration_s=20.5 if path.name == "out.mp4" else 10.0,
            width=1080, height=1920, fps=30.0, has_audio=True,
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", fake_probe)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")
    assert not [r for r in caplog.records if "时长审计" in r.getMessage()]


def test_duration_audit_probe_crash_never_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """审计自身异常（probe 崩）静默吞掉：concat 照常成功。"""
    _stub(monkeypatch)

    def boom(_path: Path) -> Any:
        raise ValueError("ffprobe 挂了")

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", boom)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")  # 不抛即过
