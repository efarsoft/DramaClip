"""llama_device：--list-devices 解析、选卡规则与显存估算（纯函数 + 探测容错）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from dramaclip.infra import llama_device

_CUDA_LIST = """Available devices:
  CUDA0: Quadro M4000 (8191 MiB, 7305 MiB free)
"""

_MIXED_LIST = """Available devices:
  Vulkan0: Radeon RX 5500 XT (8176 MiB, 7382 MiB free)
  Vulkan1: Quadro M4000 (8346 MiB, 7575 MiB free)
  CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB, 11000 MiB free)
"""


def test_parse_devices_takes_cuda_rows_only() -> None:
    """Vulkan 行出现在清单里（构建带多后端）也不选——只解析 CUDA 设备。"""
    devices = llama_device.parse_devices(_MIXED_LIST)
    assert devices == [
        llama_device.CudaDevice(
            device_id="CUDA0", name="NVIDIA GeForce RTX 3060",
            total_mb=12288, free_mb=11000,
        )
    ]
    assert llama_device.parse_devices("Available devices:\n  (none)\n") == []
    assert llama_device.parse_devices("") == []


def test_parse_devices_tolerates_noise() -> None:
    """噪声行（日志前缀/空行/坏格式）跳过，不炸也不吞掉好行。"""
    text = (
        "0.00 load: initializing\n"
        "  CUDA0: Quadro M4000 (8191 MiB, 7305 MiB free)\n"
        "  CUDA1: bad line without memory\n"
        "warning: something\n"
    )
    assert [d.device_id for d in llama_device.parse_devices(text)] == ["CUDA0"]


def test_choose_picks_most_free_and_gates_on_vram() -> None:
    two = [
        llama_device.CudaDevice("CUDA0", "Quadro M4000", 8191, 1000),
        llama_device.CudaDevice("CUDA1", "RTX 3060", 12288, 11000),
    ]
    picked = llama_device.choose(two, 5374, explicit=False, cuda_build=True)
    assert picked.device is not None and picked.device.device_id == "CUDA1"

    starved = llama_device.choose(
        [llama_device.CudaDevice("CUDA0", "Quadro M4000", 8191, 2048)],
        5374, explicit=False, cuda_build=True,
    )
    assert starved.device is None
    assert "显存余量不足" in starved.reason

    # 显式 cuda 不做余量把关：承诺交给启动失败去如实报错
    kept = llama_device.choose(
        [llama_device.CudaDevice("CUDA0", "Quadro M4000", 8191, 2048)],
        5374, explicit=True, cuda_build=True,
    )
    assert kept.device is not None


def test_choose_empty_list_reasons_by_build() -> None:
    cpu_only = llama_device.choose([], 5374, explicit=False, cuda_build=False)
    assert cpu_only.device is None
    assert "CPU 构建" in cpu_only.reason

    no_runtime = llama_device.choose([], 5374, explicit=False, cuda_build=True)
    assert no_runtime.device is None
    assert "CUDA 运行库" in no_runtime.reason


def test_required_mb_is_weights_plus_headroom(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    model.write_bytes(b"\0" * (3 * 1024 * 1024))
    mmproj.write_bytes(b"\0" * (1024 * 1024))
    assert llama_device.required_mb(model, mmproj) == 3 + 1 + 2560
    # 文件缺位按 0 计，不炸
    assert llama_device.required_mb(tmp_path / "gone.gguf", mmproj) == 1 + 2560


def test_has_cuda_build_is_file_presence(tmp_path: Path) -> None:
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"MZ")
    assert llama_device.has_cuda_build(exe) is False
    (tmp_path / "ggml-cuda.dll").write_bytes(b"MZ")
    assert llama_device.has_cuda_build(exe) is True
    assert llama_device.server_exe(tmp_path) == (
        tmp_path / "tools" / "llama.cpp" / "llama-server.exe"
    )


def test_runtime_env_prepends_existing_dirs(tmp_path: Path) -> None:
    assert llama_device.runtime_env(None) is None
    assert llama_device.runtime_env(tmp_path) is None, "目录不落位就别动环境"
    for name in ("cublas", "cudart"):
        (tmp_path / "models" / "cuda" / name).mkdir(parents=True)
    env = llama_device.runtime_env(tmp_path)
    assert env is not None
    head = env["PATH"].split(os.pathsep)[:2]
    assert head == [
        str((tmp_path / "models" / "cuda" / name).resolve()) for name in ("cublas", "cudart")
    ]


def test_list_cuda_devices_swallows_probe_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """探测失败按空清单处理（调用方落 CPU 并留原因），不许把异常抛进视觉轨。"""

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("起不来")

    def slow(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["x"], timeout=1)

    exe = tmp_path / "llama-server.exe"
    for failure in (boom, slow):
        monkeypatch.setattr(llama_device.subprocess, "run", failure)
        assert llama_device.list_cuda_devices(exe) == []

    class _FakeRun:
        def __init__(self, out: str) -> None:
            self.stdout, self.stderr, self.returncode = out, "", 0

    monkeypatch.setattr(
        llama_device.subprocess, "run", lambda *_a, **_k: _FakeRun(_CUDA_LIST)
    )
    devices = llama_device.list_cuda_devices(exe, env=None)
    assert [d.name for d in devices] == ["Quadro M4000"]
