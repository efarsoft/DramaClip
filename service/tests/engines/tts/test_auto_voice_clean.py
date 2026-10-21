"""自动参考音色的清洗回执：分离失败回退滤镜时必须说破，不能当作分离完成。"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.tts import auto_voice, reference_clean, vocal_separation
from dramaclip.engines.tts.vocal_separation import SeparationResult
from dramaclip.infra.compute import ComputeReport


def _run_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    source = tmp_path / "episode.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        auto_voice, "pick_best_span",
        lambda _conn, _episodes: ({"id": "e1", "source_path": str(source)}, 0.0, 8.0, "角色A"),
    )

    def fake_ffmpeg(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        Path(cmd[-1]).write_bytes(b"raw")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(auto_voice.subprocess, "run", fake_ffmpeg)
    return auto_voice._extract_locked(None, tmp_path, [])  # noqa: SLF001


def test_extract_always_starts_separation_at_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tts.device 只承诺 torch 那条栈：分离恒 auto，由 worker 自己探 CUDA EP。

    继承 tts.device 会造出两个方向都错的结论（规格 §3.5）：为躲 IndexTTS 报错把
    tts.device 设成 CPU 的主机顺手关掉可用的 GPU 分离；设成 CUDA 而 ORT 是 CPU 轮的
    主机则让分离硬失败并直接掉到滤镜——CUDA 一失败就跳滤镜那条路必须不可达。
    """
    seen: dict[str, object] = {}
    report = ComputeReport(
        component="tts.separation", requested="auto", resolved="cpu", actual="cpu",
        reason="CUDA EP 缺失",
    )

    def fake_separation(_models: Path, _src: Path, **kwargs: Any) -> SeparationResult:
        seen.update(kwargs)
        out = tmp_path / "clean.wav"
        out.write_bytes(b"clean")
        return SeparationResult(path=out, compute=report)

    monkeypatch.setattr(vocal_separation, "clean_reference", fake_separation)

    result = _run_extract(tmp_path, monkeypatch)

    assert seen["device"] == "auto"
    assert result["cleaned_with"] == "separation"
    assert result["compute"]["actual"] == "cpu"
    assert result["compute"]["reason"] == "CUDA EP 缺失"


def test_extract_signature_has_no_device() -> None:
    """`device` 参数整个删掉：留着就是给「顺手传 tts.device」留门。"""
    params = inspect.signature(auto_voice.extract_auto_voice).parameters
    assert "device" not in params


def test_extract_filter_fallback_reports_cpu_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """滤镜兜底也要有回执：component 说方法，reason 说分离为什么没用。"""
    def fail_separation(_models: Path, _src: Path, **_kwargs: Any) -> SeparationResult:
        raise RuntimeError("TTS 运行环境未安装")

    def fake_filter(src: Path) -> Path:
        out = src.with_name("filtered.wav")
        out.write_bytes(b"filtered")
        return out

    monkeypatch.setattr(vocal_separation, "clean_reference", fail_separation)
    monkeypatch.setattr(reference_clean, "clean_reference", fake_filter)

    result = _run_extract(tmp_path, monkeypatch)

    assert result["cleaned_with"] == "filter"
    assert "TTS 运行环境未安装" in result["clean_reason"]
    report = result["compute"]
    assert report["component"] == "tts.reference_clean.filter"
    assert (report["requested"], report["resolved"], report["actual"]) == ("auto", "cpu", "cpu")
    assert report["fallback"] is False, "滤镜从没试过 GPU，写 fallback 就是造假账"
    assert "TTS 运行环境未安装" in report["reason"]
