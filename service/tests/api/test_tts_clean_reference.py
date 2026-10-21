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
from typing import Any

import pytest

from dramaclip.api import tts as tts_api
from dramaclip.engines.tts.vocal_separation import SeparationResult
from dramaclip.infra.compute import ComputeReport
from dramaclip.transport.rpc import RpcDomainError


class _FakeJobStore:
    """jobs 行的记账替身：「账在库」这条纪律只能这样验——看写进去的终态与回执。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def create(self, job_type: str, ref_id: str | None = None) -> str:
        job_id = f"job{len(self.rows) + 1}"
        self.rows[job_id] = {
            "type": job_type, "ref_id": ref_id, "status": "pending",
            "compute": None, "error": None,
        }
        return job_id

    def mark_running(self, job_id: str) -> None:
        self.rows[job_id]["status"] = "running"

    def mark_completed(self, job_id: str) -> None:
        self.rows[job_id]["status"] = "completed"

    def mark_failed(self, job_id: str, error: str) -> None:
        self.rows[job_id]["status"] = "failed"
        self.rows[job_id]["error"] = error

    def set_compute(self, job_id: str, reports: list[dict[str, Any]]) -> None:
        self.rows[job_id]["compute"] = reports

    def set_ref_id(self, job_id: str, ref_id: str) -> None:
        self.rows[job_id]["ref_id"] = ref_id

    def only_row(self) -> dict[str, Any]:
        """本次调用应只留一行；行数不对就让断言自己炸，而不是静默取第一行。"""
        assert len(self.rows) == 1, f"期望一行任务，实际 {list(self.rows)}"
        return next(iter(self.rows.values()))


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=tmp_path, settings={}, job_store=_FakeJobStore())


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


def test_separate_mode_ignores_tts_device_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """方向翻转：旧用例证明 tts.device 传得下去，这条证明传不下去。

    透传 cuda 等于把「CUDA 一失败就跳滤镜」变成常规路径——分离的降级链是
    CUDA 分离 → CPU 分离 → 滤镜，中间那档只有调用方不承诺时才够得到（规格 §3.5）。
    """
    context = _context(tmp_path)
    context.settings = {"tts.device": "cuda"}
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=2.0)
    seen: dict[str, object] = {}
    report = ComputeReport(
        component="tts.separation", requested="auto", resolved="cpu", actual="cpu",
        reason="CUDA EP 缺失",
    )
    monkeypatch.setattr(
        tts_api.vocal_separation, "clean_reference",
        lambda models_dir, path, **kwargs: seen.update(kwargs)
        or SeparationResult(path=artifact, compute=report),
    )

    result = tts_api.clean_reference(context, {"path": str(src)})

    assert seen["device"] == "auto", "tts.device=cuda 不许透传到分离"
    assert result["compute"]["component"] == "tts.separation"
    assert result["job_id"] in context.job_store.rows
    row = context.job_store.only_row()
    assert (row["type"], row["status"]) == ("voice_clean", "completed")
    assert row["compute"] == [report.to_dict()]
    assert row["ref_id"] == str(artifact), "任务行要指向产物，不然后查无从下手"


def test_fast_mode_reports_filter_compute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """滤镜档也留痕：requested=auto + resolved=cpu + fallback=False（从没试过 GPU）。"""
    context = _context(tmp_path)
    src = _write_wav(tmp_path / "src.wav")
    artifact = _write_wav(tmp_path / "src.cleaned.wav", seconds=2.0)
    monkeypatch.setattr(
        tts_api.reference_clean, "clean_reference", lambda path: artifact
    )

    result = tts_api.clean_reference(context, {"path": str(src), "mode": "fast"})

    assert result["compute"]["component"] == "tts.reference_clean.filter"
    assert result["compute"]["actual"] == "cpu"
    assert result["compute"]["reason"] == "用户选择快速滤镜清洗"
    row = context.job_store.only_row()
    assert row["status"] == "completed"
    assert row["compute"] is not None


def test_failed_clean_keeps_a_failed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败同样落账并把原因写进任务行：账在库，通知流不作真相源。"""
    context = _context(tmp_path)
    src = _write_wav(tmp_path / "src.wav")

    def boom(_models_dir: Path, _src: Path, **_kwargs: object) -> SeparationResult:
        raise RuntimeError("模型下载失败")

    monkeypatch.setattr(tts_api.vocal_separation, "clean_reference", boom)
    with pytest.raises(RpcDomainError) as info:
        tts_api.clean_reference(context, {"path": str(src)})

    assert info.value.code == -32322
    row = context.job_store.only_row()
    assert row["status"] == "failed"
    assert "模型下载失败" in row["error"]
    assert row["compute"] is None, "没跑成的事不能留一条看起来跑过的回执"


def test_unknown_mode_leaves_no_failed_row(tmp_path: Path) -> None:
    """参数错误在建行之前就挡掉：不该为一次点错留一条失败任务。"""
    context = _context(tmp_path)
    src = _write_wav(tmp_path / "src.wav")
    with pytest.raises(RpcDomainError):
        tts_api.clean_reference(context, {"path": str(src), "mode": "magic"})
    assert context.job_store.rows == {}
