"""torch 轮安装来源链（xpu 镜像 fallback）：官方源失败必须回落阿里镜像——
2.5GB 级大轮不能单点（官方源国内 SSL 握手失败有前科）。monkeypatch _run_uv
记录命令序列，钉死三变体的来源结构与回落次序。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.infra.model_manager import tts_runtime

UV = Path("uv.exe")
VENV = Path("venv")


def _record(calls: list[list[str]], fail_first: int = 0):
    """_run_uv 桩：前 fail_first 次抛 RuntimeError，其余成功并记录命令。"""
    def fake(_uv: Path, _venv: Path, *args: str) -> None:
        calls.append(list(args))
        if len(calls) <= fail_first:
            raise RuntimeError("模拟官方源被掐")
    return fake


def test_xpu_falls_back_to_aliyun_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 xpu 索引失败 → 第二次带 --find-links 阿里 xpu 目录。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(tts_runtime, "_run_uv", _record(calls, fail_first=1))
    tts_runtime._install_torch(UV, VENV, "xpu")
    assert len(calls) == 2
    first, second = calls
    assert tts_runtime._TORCH_XPU_INDEX in first
    assert "--find-links" in second
    assert tts_runtime._TORCH_XPU_MIRROR in second
    assert tts_runtime._PYPI_MIRROR in second


def test_xpu_all_sources_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(tts_runtime, "_run_uv", _record(calls, fail_first=2))
    with pytest.raises(RuntimeError, match="全部来源失败"):
        tts_runtime._install_torch(UV, VENV, "xpu")
    assert len(calls) == 2


def test_cuda_keeps_cu128_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """cuda 变体回归钉：官方 cu 源 + 阿里 cu128 目录，语义不因 xpu 批次漂移。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(tts_runtime, "_run_uv", _record(calls, fail_first=1))
    tts_runtime._install_torch(UV, VENV, "cuda")
    second = calls[1]
    assert tts_runtime._TORCH_CU128_MIRROR in second


def test_cpu_is_single_source(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(tts_runtime, "_run_uv", _record(calls))
    tts_runtime._install_torch(UV, VENV, "cpu")
    assert len(calls) == 1 and tts_runtime._PYPI_MIRROR in calls[0]
