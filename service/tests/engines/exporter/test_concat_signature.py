"""A4-2 Phase B 签名守卫：段流签名齐→-c copy；不齐/测不出→整体重编码；时长闸超容差即抛。

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
    film_duration: float = 20.0,
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

    def fake_heartbeat(cmd: list[str], **_kwargs: Any) -> None:
        calls.append([str(part) for part in cmd])
        Path(cmd[-1]).write_bytes(b"")

    # 心跳封装接管长 ffmpeg：记录同一形状的调用并把暂存产物写出来供 os.replace
    monkeypatch.setattr(encoder, "_run_ffmpeg_with_heartbeat", fake_heartbeat)

    def fake_probe(path: Path) -> Any:
        # 段各 10s；成片时长默认取各段实测和，让时长闸在纯形状测试里保持放行
        return encoder.ffprobe_mod.MediaInfo(
            duration_s=10.0 if path.name.startswith("seg_") else film_duration,
            width=1080, height=1920, fps=30.0, has_audio=True,
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
    calls = _stub(monkeypatch, film_duration=10.0)
    seg = _segments(tmp_path, 1)[0]
    out = tmp_path / "out.mp4"
    encoder._concat([seg], out)
    assert out.read_bytes() == b"seg", "单段仍直接 copy bytes"
    assert not [c for c in calls if c[0] == "ffmpeg"], "单段不该起 ffmpeg"


def test_duration_audit_fails_on_large_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """concat 后实测与各段实测和差超 max(8%,3s)：抛错不出片（§3.3.1 禁止级降级）。

    旧口径是 warn 放行，前提是「审计不该反过来挡已成功的导出」；但缺一段/多一段正是
    这条审计在抓的东西，放行等于把缺陷片推到发布位——与响度实测超容差同判据，改抛。
    """
    _stub(monkeypatch)
    durations = {"seg": 10.0, "out": 60.0}

    def fake_probe(path: Path) -> Any:
        return encoder.ffprobe_mod.MediaInfo(
            duration_s=durations["out" if path.name.startswith("out") else "seg"],
            width=1080, height=1920, fps=30.0, has_audio=True,
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", fake_probe)
    with pytest.raises(encoder.FilmIntegrityError, match="时长审计"):
        encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")  # 各段和 20s，成片 60s


def test_duration_audit_boundary_is_the_shared_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """阈值内（段 20s / 实测 20.5s）照常交付，且不留 warn——闸门不制造噪音。"""
    _stub(monkeypatch)
    caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")

    def fake_probe(path: Path) -> Any:
        return encoder.ffprobe_mod.MediaInfo(
            # 原子交付后审计跑在 .part 暂存名上：out 前缀（含 part）都按成片档
            duration_s=20.5 if path.name.startswith("out") else 10.0,
            width=1080, height=1920, fps=30.0, has_audio=True,
        )

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", fake_probe)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")
    assert not [r for r in caplog.records if "时长审计" in r.getMessage()]


def test_duration_audit_probe_crash_leaves_a_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """审计自己测不出来：不挡已拼好的片（允许级），但必须留痕——「没量到」不等于「合格」。"""
    _stub(monkeypatch)
    caplog.set_level(logging.WARNING, logger="dramaclip.engines.exporter.encoder")

    def boom(_path: Path) -> Any:
        raise ValueError("ffprobe 挂了")

    monkeypatch.setattr(encoder.ffprobe_mod, "probe", boom)
    encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")  # 不抛即过
    messages = [r.getMessage() for r in caplog.records]
    assert any("未能测量" in m for m in messages), f"测不出必须留痕：{messages}"


# ---- 清单文件：并发隔离 / 转义 / 失败也收走 ----


def test_concat_list_file_is_per_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """清单名跟着 out_path 走：固定 `concat.txt` 落在同项目目录里会被并发导出互盖。

    api 层只换文件名、不换目录（`api/export.render_export`：
    `data/outputs/<project_id>/<项目>_<模式>_<id前6位>.mp4`），同一剧的 K 条方案同时
    拼片时，后写的清单决定前者拼出什么——那是「A 的成片装着 B 的段」级别的事故。
    """
    calls = _stub(monkeypatch)
    out = tmp_path / "projA_full_narration_ab12cd.mp4"
    encoder._concat(_segments(tmp_path), out)
    ffmpeg_call = next(c for c in calls if c[0] == "ffmpeg")
    list_path = Path(ffmpeg_call[ffmpeg_call.index("-i") + 1])
    assert list_path.name.startswith(out.stem), f"清单必须按产物命名：{list_path}"
    assert list_path.name != "concat.txt", "固定名 = 并发作业共用同一个文件"
    assert not list_path.exists(), "拼完收走，不在成片目录里留垃圾"


def test_concat_list_removed_when_ffmpeg_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg 非零退出（check=True 抛错）也要在 finally 里清掉清单。"""
    _stub(monkeypatch)

    def boom(cmd: list[str], **_kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(1, [str(part) for part in cmd])

    monkeypatch.setattr(encoder, "_run_ffmpeg_with_heartbeat", boom)
    with pytest.raises(subprocess.CalledProcessError):
        encoder._concat(_segments(tmp_path), tmp_path / "out.mp4")
    assert [p.name for p in tmp_path.iterdir() if "concat" in p.name] == [], (
        "失败路径漏在盘上=下次渲染的幽灵输入"
    )


def test_concat_list_escapes_single_quotes_in_paths(tmp_path: Path) -> None:
    r"""路径里的单引号必须写成 `'\''`，否则清单从该处断开、后半截被 ffmpeg 当语法垃圾。"""
    quoted_dir = tmp_path / "it's"
    quoted_dir.mkdir()
    segment = quoted_dir / "seg_000.mp4"
    segment.write_bytes(b"seg")
    line = encoder._concat_list_line(segment)
    assert line.startswith("file '") and line.endswith("'\n"), line
    body = line[len("file '") : -len("'\n")]
    assert "'\\''" in body, f"单引号未按 ffmpeg 约定转义：{body}"
    assert "'" not in body.replace("'\\''", ""), f"残留裸单引号会提前终结字符串：{body}"


def test_concat_publishes_atomically_and_never_touches_old_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """原子交付（T0）：concat 失败时旧成片原样保留、.part 收走、不产生半成品成片。"""
    import dramaclip.engines.exporter.encoder as encoder

    old_film = tmp_path / "film.mp4"
    old_film.write_bytes(b"OLD")
    seg_a = tmp_path / "seg-a.mp4"
    seg_b = tmp_path / "seg-b.mp4"
    for seg in (seg_a, seg_b):
        seg.write_bytes(b"X" * 64)
    _SIG = ("h264", "High", 40, "yuv420p", 8, 1080, "1:1")
    monkeypatch.setattr(encoder, "_video_signature", lambda _p: _SIG)
    monkeypatch.setattr(encoder, "_audit_film_duration", lambda _p, _s: None)

    def boom(cmd, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("ffmpeg 失败（code=1）：mock")

    monkeypatch.setattr(encoder, "_run_ffmpeg_with_heartbeat", boom)
    with pytest.raises(RuntimeError):
        encoder._concat([seg_a, seg_b], old_film)
    assert old_film.read_bytes() == b"OLD", "旧成片不得被半成品覆盖"
    assert not (tmp_path / "film.part.mp4").exists(), "失败 .part 必须收走"


def test_concat_success_replaces_via_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dramaclip.engines.exporter.encoder as encoder

    seg_a = tmp_path / "seg-a.mp4"
    seg_b = tmp_path / "seg-b.mp4"
    for seg in (seg_a, seg_b):
        seg.write_bytes(b"X" * 64)
    out = tmp_path / "film.mp4"
    _SIG = ("h264", "High", 40, "yuv420p", 8, 1080, "1:1")
    monkeypatch.setattr(encoder, "_video_signature", lambda _p: _SIG)
    monkeypatch.setattr(encoder, "_audit_film_duration", lambda _p, _s: None)

    def fake_run(cmd, **kw):  # noqa: ANN001, ANN003
        staged = Path(cmd[-1])
        staged.write_bytes(b"NEWFILM")

    monkeypatch.setattr(encoder, "_run_ffmpeg_with_heartbeat", fake_run)
    encoder._concat([seg_a, seg_b], out)
    assert out.read_bytes() == b"NEWFILM"
    assert not (tmp_path / "film.part.mp4").exists()
