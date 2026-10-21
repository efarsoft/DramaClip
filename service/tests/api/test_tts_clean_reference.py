"""api/tts.clean_reference：参考音频清洗的参数门与两档分发。

清洗是「改善参考」不是门禁（B6 同款）：任何模式失败都把原因原样带出（-32322），
不静默降级到另一档——「以为洗过了」比「没洗」更糟。质检报告只如实返回产物档位。
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import tts as tts_api
from dramaclip.engines.tts.vocal_separation import SeparationResult
from dramaclip.infra.compute import ComputeReport
from dramaclip.transport.rpc import RpcDomainError


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=tmp_path, settings={})


def _write_wav(path: Path, seconds: float = 4.0, sr: int = 16000) -> Path:
    """纯 stdlib 写一段 220Hz 正弦：QC 的 soundfile 读得动，测试零新依赖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / sr)))
            for i in range(int(sr * seconds))
        ))
    return path


def test_missing_path_is_param_error(tmp_path: Path) -> None:
    with pytest.raises(RpcDomainError) as info:
        tts_api.clean_reference(_context(tmp_path), {})
    assert info.value.code == -32320


def test_nonexistent_path_is_param_error(tmp_path: Path) -> None:
    with pytest.raises(RpcDomainError) as info:
        tts_api.clean_reference(_context(tmp_path), {"path": str(tmp_path / "nope.wav")})
    assert info.value.code == -32320


def test_unknown_mode_is_param_error(tmp_path: Path) -> None:
    src = _write_wav(tmp_path / "src.wav")
    with pytest.raises(RpcDomainError) as info:
        tts_api.clean_reference(_context(tmp_path), {"path": str(src), "mode": "magic"})
    assert info.value.code == -32320
    assert "未知清洗模式" in info.value.message


def test_fast_mode_returns_artifact_with_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=5.0)
    monkeypatch.setattr(
        tts_api.reference_clean, "clean_reference", lambda path: artifact
    )

    result = tts_api.clean_reference(_context(tmp_path), {"path": str(src), "mode": "fast"})

    assert result["path"] == str(artifact)
    assert result["quality"]["grade"] in {"good", "fair", "poor"}
    assert result["quality"]["metrics"]["duration_s"] == 5.0


def test_separate_mode_failure_carries_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _write_wav(tmp_path / "src.wav")

    def boom(_models_dir: Path, _src: Path, **_kwargs: object) -> SeparationResult:
        raise RuntimeError("TTS 运行环境未安装")

    monkeypatch.setattr(tts_api.vocal_separation, "clean_reference", boom)
    with pytest.raises(RpcDomainError) as info:
        tts_api.clean_reference(_context(tmp_path), {"path": str(src)})
    assert info.value.code == -32322
    assert "TTS 运行环境未安装" in info.value.message


def test_separate_mode_returns_artifact_and_compute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=5.0)
    seen: dict[str, object] = {}
    report = ComputeReport(
        component="tts.separation", requested="auto", resolved="cuda",
        actual="cuda", device="cuda",
    )
    monkeypatch.setattr(
        tts_api.vocal_separation, "clean_reference",
        lambda models_dir, path, **kwargs: seen.update(
            models=models_dir, src=path, **kwargs
        ) or SeparationResult(path=artifact, compute=report),
    )

    result = tts_api.clean_reference(context, {"path": str(src)})

    assert seen["models"] == context.data_dir / "models"
    assert seen["src"] == src
    assert seen["device"] == "auto", "未设置 tts.device 时走 auto（允许试 GPU 后回退）"
    assert result["path"] == str(artifact)
    assert result["compute"]["actual"] == "cuda"
    assert "reasons" in result["quality"] and "suggestions" in result["quality"]


def test_separate_mode_honors_explicit_device_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    context.settings = {"tts.device": "cpu"}
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=2.0)
    seen: dict[str, object] = {}
    report = ComputeReport(
        component="tts.separation", requested="cpu", resolved="cpu", actual="cpu",
    )
    monkeypatch.setattr(
        tts_api.vocal_separation, "clean_reference",
        lambda models_dir, path, **kwargs: seen.update(kwargs)
        or SeparationResult(path=artifact, compute=report),
    )

    result = tts_api.clean_reference(context, {"path": str(src)})

    assert seen["device"] == "cpu"
    assert result["compute"]["requested"] == "cpu"


def test_fast_mode_does_not_report_compute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=2.0)
    monkeypatch.setattr(
        tts_api.reference_clean, "clean_reference", lambda path: artifact
    )

    result = tts_api.clean_reference(_context(tmp_path), {"path": str(src), "mode": "fast"})

    assert result.get("compute") is None
