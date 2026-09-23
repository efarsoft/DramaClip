"""B4 导出段级断点续跑：sidecar 签名（seg_NNN.sig）决定哪些段可以不重编。

选型（b）的钉法：签名覆盖**声明输入**（源身份 path+size+mtime_ns、episode_id、
声明 start/end、codec、seam/ zones / tts 内容 hash、字幕 ass 内容 hash），
不含 jitter 后的实际切点——复用即接受上次的抖动切点与消重参数（rng 无种子是
消重语义的一部分，不许按 export_id 播种）。任何影响产物字节的输入变了都不许复用；
只查文件存在不查签名 = autoclip 的反例，这里逐条钉住。

真机那条（文件末尾）用 lavfi 源真跑两次 export_plan：第二次零重编、段与成片
逐字节一致——断点续跑的正确性最终要真 ffmpeg 背书。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # noqa: S404 - 参数为受控列表
import time
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra.ffmpeg import runner


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "ep1.mp4"
    if not source.exists():
        source.write_bytes(b"source-bytes")
    return source


def _plan(
    start: float = 0.0, end: float = 10.0, subtitle_text: str | None = None
) -> PlanData:
    return PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=start, end=end,
                audio="original", subtitle_text=subtitle_text,
            ),
            TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original"),
        ],
    )


class _Spy:
    """替身 _run_cut：真写产物（确定性内容）并计数。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cancel: Any = None, **_k: Any) -> None:
        self.calls.append(list(args))
        seg = Path(args[-1])
        seg.parent.mkdir(parents=True, exist_ok=True)
        seg.write_bytes(b"encoded:" + seg.name.encode())


def _seg_names(calls: list[list[str]]) -> list[str]:
    return [Path(args[-1]).name for args in calls]


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan: PlanData,
    spy: _Spy,
    *,
    video_codec: str = "libx264",
    on_progress: Any = None,
    subtitle_burner: Any = None,
    original_subtitle_provider: Any = None,
) -> Path:
    work = tmp_path / "work"
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(encoder, "_run_cut", spy)
    encoder.export_plan(
        plan,
        {"ep1": str(_source(tmp_path))},
        tmp_path / "out.mp4",
        work,
        video_codec=video_codec,
        parallel=1,
        on_progress=on_progress,
        subtitle_burner=subtitle_burner,
        original_subtitle_provider=original_subtitle_provider,
    )
    return work


def _sig(work: Path, index: int) -> dict[str, Any]:
    payload = json.loads((work / f"seg_{index:03d}.sig").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


# ---- 1. 新鲜渲染：全编 + 每段写成对签名 ----

def test_fresh_run_encodes_all_and_writes_sig_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy()
    work = _run(monkeypatch, tmp_path, _plan(), spy)
    assert len(spy.calls) == 2, "空 work_dir 必须全编"
    for index in (0, 1):
        seg = work / f"seg_{index:03d}.mp4"
        sig = work / f"seg_{index:03d}.sig"
        assert seg.is_file() and sig.is_file(), "seg 与 sig 必须成对"
    payload = _sig(work, 0)
    assert payload["recorded"]["actual_codec"] == "libx264"
    assert payload["inputs"]["episode_id"] == "ep1"
    assert payload["inputs"]["source"]["size"] > 0
    assert not list(work.glob("*.tmp")), "签名原子落盘不许留 tmp 残骸"


def test_second_run_skips_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _Spy()
    _run(monkeypatch, tmp_path, _plan(), first)
    assert len(first.calls) == 2
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert second.calls == [], f"输入全同的第二次运行必须零重编：{_seg_names(second.calls)}"


# ---- 2. 输入变了就不许复用 ----

def test_source_mtime_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(monkeypatch, tmp_path, _plan(), _Spy())
    stat = _source(tmp_path).stat()
    os.utime(_source(tmp_path), ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert len(second.calls) == 2, "源文件身份变了（mtime），两段都必须重编"


def test_declared_window_change_reencodes_only_that_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(monkeypatch, tmp_path, _plan(), _Spy())
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(start=0.5), second)
    assert _seg_names(second.calls) == ["seg_000.mp4"], "只有声明窗口变了的段重编"


def test_codec_request_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(monkeypatch, tmp_path, _plan(), _Spy(), video_codec="libx264")
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second, video_codec="h264_nvenc")
    assert len(second.calls) == 2, "请求 codec 与 sig 记录的实际 codec 不同→重编"


def test_subtitle_text_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ass = tmp_path / "burn.ass"

    def burner(_i: int, _t: str, _d: float) -> str:
        ass.write_text("[Script Info]\n恒定内容", encoding="utf-8")
        return str(ass)

    _run(monkeypatch, tmp_path, _plan(subtitle_text="甲"), _Spy(), subtitle_burner=burner)
    second = _Spy()
    _run(
        monkeypatch, tmp_path, _plan(subtitle_text="乙"), second, subtitle_burner=burner
    )
    assert _seg_names(second.calls) == ["seg_000.mp4"], "字幕文本变了只重编带字幕那段"


def test_ass_content_change_with_same_text_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预设/拆行逻辑变化模拟：声明文本没变，但 burner 产出的 ass 字节变了。

    跳过判定必须**用上次的窗口重新生成 ass 并比对内容 hash**，只比声明字段抓不住。
    """
    content = {"ass": "[Script Info]\n版本A"}
    ass = tmp_path / "burn.ass"

    def burner(_i: int, _t: str, _d: float) -> str:
        ass.write_text(content["ass"], encoding="utf-8")
        return str(ass)

    _run(monkeypatch, tmp_path, _plan(subtitle_text="甲"), _Spy(), subtitle_burner=burner)
    content["ass"] = "[Script Info]\n版本B"
    second = _Spy()
    _run(
        monkeypatch, tmp_path, _plan(subtitle_text="甲"), second, subtitle_burner=burner
    )
    assert _seg_names(second.calls) == ["seg_000.mp4"], (
        "ass 内容 hash 不一致必须重编；无字幕的 seg_001 仍须复用"
    )
    third = _Spy()
    _run(monkeypatch, tmp_path, _plan(subtitle_text="甲"), third, subtitle_burner=burner)
    assert third.calls == [], "内容稳定之后第三次运行恢复复用"


def test_provider_ass_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """原声段台词字幕（provider 路）：DB 里 ASR 文本变了（zones 时间不变）也要重编。"""
    content = {"ass": "Dialogue: 甲"}
    ass = tmp_path / "prov.ass"

    def provider(_i: int, _s: float, _e: float) -> str:
        ass.write_text(content["ass"], encoding="utf-8")
        return str(ass)

    _run(
        monkeypatch, tmp_path, _plan(), _Spy(), original_subtitle_provider=provider
    )
    content["ass"] = "Dialogue: 乙"
    second = _Spy()
    _run(
        monkeypatch, tmp_path, _plan(), second, original_subtitle_provider=provider
    )
    assert _seg_names(second.calls) == ["seg_000.mp4", "seg_001.mp4"], (
        "两段都是原声无字幕段、都走 provider：台词内容变了必须都重编"
    )


def test_tts_audio_content_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """混音形状：TTS 路径不变、内容变了（同路径重新合成）也不许复用旧段。"""
    from dramaclip.engines.narration.models import NarrationText, PlanData

    tts = tmp_path / "voice.mp3"
    tts.write_bytes(b"tts-v1")
    plan = PlanData(
        mode="full_narration",
        narration_texts=[NarrationText(id="n1", text="解说", audio_path=str(tts))],
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=4.0,
                audio="narration", narration_id="n1",
            )
        ],
    )
    work = tmp_path / "work"
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(
        encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film")
    )
    first = _Spy()
    monkeypatch.setattr(encoder, "_run_cut", first)
    encoder.export_plan(
        plan, {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        tts_audio_by_segment={0: str(tts)}, parallel=1,
    )
    assert len(first.calls) == 1

    tts.write_bytes(b"tts-v2-longer")  # 同路径新内容（A5 缓存重新合成后落位）
    second = _Spy()
    monkeypatch.setattr(encoder, "_run_cut", second)
    encoder.export_plan(
        plan, {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        tts_audio_by_segment={0: str(tts)}, parallel=1,
    )
    assert len(second.calls) == 1, "TTS 内容 hash 变了必须重编（只比路径会漏）"

    third = _Spy()
    monkeypatch.setattr(encoder, "_run_cut", third)
    encoder.export_plan(
        plan, {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        tts_audio_by_segment={0: str(tts)}, parallel=1,
    )
    assert third.calls == [], "内容稳定后恢复复用"


def test_zone_fingerprint_change_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """台词保护区（srt/ASR zones）变了→切点语义变了，不许复用。"""
    from dramaclip.engines.analysis.models import SpeechZone

    plan = _plan()
    work = tmp_path / "work"
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(
        encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film")
    )
    first = _Spy()
    monkeypatch.setattr(encoder, "_run_cut", first)
    zones_a = {"ep1": [SpeechZone(start=1.0, end=2.0)]}
    encoder.export_plan(
        plan, {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        dialogue_zones=zones_a, parallel=1,
    )
    assert len(first.calls) == 2

    second = _Spy()
    monkeypatch.setattr(encoder, "_run_cut", second)
    zones_b = {"ep1": [SpeechZone(start=1.0, end=2.5)]}  # ASR 重跑后保护区变了
    encoder.export_plan(
        plan, {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        dialogue_zones=zones_b, parallel=1,
    )
    assert len(second.calls) == 2, "保护区内容哈希变了必须重编"


# ---- 3. 成对性：一边丢了就重编 ----

def test_sig_missing_reencodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = _run(monkeypatch, tmp_path, _plan(), _Spy())
    (work / "seg_000.sig").unlink()
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert _seg_names(second.calls) == ["seg_000.mp4"], "产物在签名不在→重编"


def test_seg_missing_reencodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = _run(monkeypatch, tmp_path, _plan(), _Spy())
    (work / "seg_000.mp4").unlink()
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert _seg_names(second.calls) == ["seg_000.mp4"], "签名在产物不在→重编"


def test_corrupt_sig_reencodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = _run(monkeypatch, tmp_path, _plan(), _Spy())
    (work / "seg_001.sig").write_text("{ not json", encoding="utf-8")
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert _seg_names(second.calls) == ["seg_001.mp4"], "签名损坏按不可复用处理，不许炸"


def test_zero_byte_product_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 字节残留产物不是缓存命中（与 A5 `_usable` 同判据）：有 sig 也要重编。"""
    work = _run(monkeypatch, tmp_path, _plan(), _Spy())
    (work / "seg_000.mp4").write_bytes(b"")
    second = _Spy()
    _run(monkeypatch, tmp_path, _plan(), second)
    assert _seg_names(second.calls) == ["seg_000.mp4"], "空产物必须重编"


# ---- 4. 进度语义：跳过的段计入完成进度 ----

def test_skipped_segments_count_into_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = _run(monkeypatch, tmp_path, _plan(), _Spy())
    (work / "seg_001.sig").unlink()  # 只让第二段重编
    seen: list[tuple[float, str]] = []
    _run(
        monkeypatch, tmp_path, _plan(), _Spy(),
        on_progress=lambda p, m: seen.append((p, m)),
    )
    assert seen[0][0] == pytest.approx(45.0), (
        f"续跑首个进度事件必须从已完成段起算（1/2×90=45），不许从 0 爬：{seen[:3]}"
    )
    percents = [p for p, _ in seen]
    assert percents == sorted(percents), f"进度必须单调不减：{percents}"
    assert seen[-1] == (100.0, "导出完成")


def test_all_skipped_still_finishes_at_100(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(monkeypatch, tmp_path, _plan(), _Spy())
    seen: list[tuple[float, str]] = []
    _run(
        monkeypatch, tmp_path, _plan(), _Spy(),
        on_progress=lambda p, m: seen.append((p, m)),
    )
    percents = [p for p, _ in seen]
    assert percents[0] == pytest.approx(90.0), "全复用时首个事件即 Phase A 满格（2/2×90）"
    assert seen[-1] == (100.0, "导出完成")


# ---- 5. 与 A4 段级回退自洽：sig 记实际成功 codec ----

def test_fallback_records_actual_codec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        seg = Path(args[-1])
        codec = args[args.index("-c:v") + 1]
        if codec in encoder._HW_ENCODERS:
            seg.parent.mkdir(parents=True, exist_ok=True)
            seg.write_bytes(b"partial")
            raise runner.FfmpegError("Unknown encoder", kind="codec")
        seg.parent.mkdir(parents=True, exist_ok=True)
        seg.write_bytes(b"ok")

    work = tmp_path / "work"
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(
        encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(encoder, "_run_cut", fake_cut)
    calls: list[list[str]] = []

    def counting_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        calls.append(list(args))
        fake_cut(args, cancel, **_k)

    monkeypatch.setattr(encoder, "_run_cut", counting_cut)
    encoder.export_plan(
        _plan(), {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        video_codec="h264_nvenc", parallel=1,
    )
    assert _sig(work, 0)["recorded"]["actual_codec"] == "libx264", (
        "回退段必须记**实际成功**的 codec，不是请求的"
    )

    # 同 codec（nvenc）请求→实际是 libx264，不同→重编
    calls.clear()
    encoder.export_plan(
        _plan(), {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        video_codec="h264_nvenc", parallel=1,
    )
    assert len(calls) == 4, "请求 nvenc 而产物是 libx264：两段都重编（各含回退共 4 次）"

    # 请求 libx264→与 sig 记录的实际 codec 相同→跳过
    calls.clear()
    encoder.export_plan(
        _plan(), {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
        video_codec="libx264", parallel=1,
    )
    assert calls == [], "请求与实际产物 codec 一致→复用"


# ---- 6. cancel 语义零改动：半成品无 sig→下次重编 ----

def test_cancelled_partial_has_no_sig_and_reencodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cancelling_cut(args: list[str], cancel: Any = None, **_k: Any) -> None:
        seg = Path(args[-1])
        seg.parent.mkdir(parents=True, exist_ok=True)
        seg.write_bytes(b"partial")  # ffmpeg 被杀时留下的半成品
        raise runner.FfmpegError("ffmpeg 已取消", cancelled=True)

    work = tmp_path / "work"
    monkeypatch.setattr(encoder.jitter, "safe_times", lambda s, e, _z, **_k: (s, e))
    monkeypatch.setattr(
        encoder, "_concat", lambda _f, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(encoder, "_run_cut", cancelling_cut)
    with pytest.raises(runner.FfmpegError) as excinfo:
        encoder.export_plan(
            _plan(), {"ep1": str(_source(tmp_path))}, tmp_path / "out.mp4", work,
            parallel=1,
        )
    assert excinfo.value.cancelled
    assert (work / "seg_000.mp4").is_file(), "半成品还在（cancel 不清场，与现状一致）"
    assert not (work / "seg_000.sig").exists(), "取消的段绝不许有签名"

    spy = _Spy()
    _run(monkeypatch, tmp_path, _plan(), spy)
    assert _seg_names(spy.calls) == ["seg_000.mp4", "seg_001.mp4"], (
        "半成品无 sig→下次整段重编覆盖"
    )


# ---- 7. 陈旧尾段清理：上次更长的计划留下的 seg 不许被 concat 捡走 ----

def test_stale_tail_segments_are_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir(parents=True)
    (work / "seg_005.mp4").write_bytes(b"stale")
    (work / "seg_005.sig").write_text("{}", encoding="utf-8")
    _run(monkeypatch, tmp_path, _plan(), _Spy())
    assert not (work / "seg_005.mp4").exists(), "计划缩短后陈旧尾段必须清掉"
    assert not (work / "seg_005.sig").exists()


# ---- 8. 真机验证：lavfi 源真跑两次，第二次全跳过且产物一致 ----

def test_real_ffmpeg_second_run_skips_and_reuses_bytes(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = repo_root / "resources" / "ffmpeg" / (
        "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    )
    if not ffmpeg.is_file():
        pytest.skip("随包 ffmpeg 不存在")
    source = tmp_path / "ep1.mp4"
    subprocess.run(  # noqa: S603
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(source),
        ],
        check=True, capture_output=True, timeout=180,
    )
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=2.0, audio="original"),
            TimelineSegment(episode_id="ep1", start=2.0, end=4.0, audio="original"),
            TimelineSegment(episode_id="ep1", start=4.0, end=6.0, audio="original"),
        ],
    )
    real_cut = encoder._run_cut
    calls: list[list[str]] = []

    def spy(args: list[str], cancel: Any = None, **kwargs: Any) -> None:
        calls.append(list(args))
        real_cut(args, cancel, **kwargs)

    monkeypatch.setattr(encoder, "_run_cut", spy)
    work = tmp_path / "work"
    out1, out2 = tmp_path / "out1.mp4", tmp_path / "out2.mp4"

    t0 = time.perf_counter()
    encoder.export_plan(
        plan, {"ep1": str(source)}, out1, work,
        video_codec="libx264", out_size=(360, 640), parallel=2,
    )
    first_s = time.perf_counter() - t0
    assert len(calls) == 3
    seg_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(work.glob("seg_*.mp4"))
    }
    assert len(seg_hashes) == 3
    film1 = out1.read_bytes()

    calls.clear()
    t0 = time.perf_counter()
    encoder.export_plan(
        plan, {"ep1": str(source)}, out2, work,
        video_codec="libx264", out_size=(360, 640), parallel=2,
    )
    second_s = time.perf_counter() - t0
    assert calls == [], f"真机第二次运行必须零段重编：{_seg_names(calls)}"
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(work.glob("seg_*.mp4"))
    } == seg_hashes, "段文件不许被动过"
    assert out2.read_bytes() == film1, "同一批段 concat 出的成片必须逐字节一致"
    assert second_s < first_s, f"续跑必须更快（首跑 {first_s:.2f}s vs 续跑 {second_s:.2f}s）"
