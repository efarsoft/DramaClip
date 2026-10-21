"""tts_runtime 分组探针：status 的能力分组与依赖组跳过判据（E-2 扩容）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import tts_runtime


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _prime_venv(tmp_path: Path) -> Path:
    py = tmp_path / "runtimes" / "tts-venv" / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"")
    return py


def test_status_reports_groups_and_keeps_installed_semantics(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """installed 维持双栈口径（前端判据零改动）；groups 按族如实上报。"""
    _prime_venv(tmp_path)
    payload = {"indextts": True, "funasr": False, "kokoro": False, "torch": True}

    def fake_run(*_a: Any, **_k: Any) -> Any:
        return _FakeCompleted(0, json.dumps(payload))

    monkeypatch.setattr(tts_runtime.subprocess, "run", fake_run)
    state = tts_runtime.status(tmp_path)
    assert state["installed"] is True, "双栈（indextts+torch）通过即 installed"
    assert state["groups"] == payload, "funasr/kokoro 缺组如实上报（升级补装的判据）"
    assert state["torch_variant"] == "unknown"


def test_status_all_groups_present(tmp_path: Path, monkeypatch: Any) -> None:
    _prime_venv(tmp_path)
    payload = {"indextts": True, "funasr": True, "kokoro": True, "torch": True}

    def fake_run(*_a: Any, **_k: Any) -> Any:
        return _FakeCompleted(0, json.dumps(payload))

    monkeypatch.setattr(tts_runtime.subprocess, "run", fake_run)
    state = tts_runtime.status(tmp_path)
    assert state["installed"] is True and state["groups"]["funasr"] is True


def test_status_probe_failure_means_not_installed(tmp_path: Path, monkeypatch: Any) -> None:
    _prime_venv(tmp_path)
    monkeypatch.setattr(tts_runtime.subprocess, "run", lambda *_a, **_k: _FakeCompleted(1))
    state = tts_runtime.status(tmp_path)
    assert state["installed"] is False
    assert state["groups"] == {}, "探针非零退出：组态不可知，不给假阳性"


def test_status_bad_json_means_not_installed(tmp_path: Path, monkeypatch: Any) -> None:
    _prime_venv(tmp_path)
    monkeypatch.setattr(
        tts_runtime.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "不是 JSON")
    )
    state = tts_runtime.status(tmp_path)
    assert state["installed"] is False


def _write_ort_marker(data_dir: Path, payload: dict[str, Any]) -> None:
    marker = tts_runtime._ort_marker(data_dir)  # noqa: SLF001
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload), encoding="utf-8")


def test_ort_state_unknown_without_marker(tmp_path: Path) -> None:
    state = tts_runtime.ort_state(tmp_path)
    assert state["variant"] == "unknown"
    assert state["gpu"] is False


def test_ort_state_reads_gpu_marker(tmp_path: Path) -> None:
    _write_ort_marker(
        tmp_path,
        {"variant": "gpu", "providers": ["CUDAExecutionProvider"], "version": "1.18.0"},
    )
    state = tts_runtime.ort_state(tmp_path)
    assert state["gpu"] is True
    assert state["providers"] == ["CUDAExecutionProvider"]


def test_ort_install_plan_requires_nvidia_and_cuda_runtime() -> None:
    plan = tts_runtime._ort_install_plan  # noqa: SLF001
    assert plan(nvidia_present=True, cuda_runtime_installed=True) == "gpu"
    assert plan(nvidia_present=True, cuda_runtime_installed=False) == "cpu"
    assert plan(nvidia_present=False, cuda_runtime_installed=True) == "cpu"


def test_status_reports_ort_state(tmp_path: Path, monkeypatch: Any) -> None:
    _prime_venv(tmp_path)
    _write_ort_marker(tmp_path, {"variant": "cpu", "reason": "CUDA 运行库未安装"})
    payload = {"indextts": True, "funasr": True, "kokoro": True, "torch": True}
    monkeypatch.setattr(
        tts_runtime.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, json.dumps(payload))
    )
    state = tts_runtime.status(tmp_path)
    assert state["ort_gpu"]["variant"] == "cpu"
    assert state["ort_gpu"]["reason"] == "CUDA 运行库未安装"


def test_install_ort_gpu_probe_pass_writes_gpu_marker(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _prime_venv(tmp_path)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(tts_runtime.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        tts_runtime.cuda_runtime, "status", lambda _d: {"installed": True}
    )
    monkeypatch.setattr(
        tts_runtime, "_run_uv", lambda _uv, _venv, *args: calls.append(args)
    )
    monkeypatch.setattr(
        tts_runtime,
        "_probe_ort_gpu",
        lambda _py, _d: {
            "ok": True,
            "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "version": "1.18.0",
        },
    )

    tts_runtime._install_ort(  # noqa: SLF001
        tmp_path / "uv.exe", tts_runtime.venv_dir(tmp_path), tmp_path,
        check_cancel=lambda: None, progress=lambda *_a: None,
    )

    flat = [arg for args in calls for arg in args]
    assert "onnxruntime-gpu==1.18.0" in flat
    assert any(args[1] == "uninstall" for args in calls), "装 GPU 轮前必须卸掉 CPU 轮"
    state = tts_runtime.ort_state(tmp_path)
    assert state["variant"] == "gpu" and state["gpu"] is True


def test_install_ort_gpu_probe_failure_rolls_back_to_cpu(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """探测失败必须回装 CPU 轮并留原因：不能把「装上了」当成「能跑」。"""
    _prime_venv(tmp_path)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(tts_runtime.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        tts_runtime.cuda_runtime, "status", lambda _d: {"installed": True}
    )
    monkeypatch.setattr(
        tts_runtime, "_run_uv", lambda _uv, _venv, *args: calls.append(args)
    )
    monkeypatch.setattr(
        tts_runtime,
        "_probe_ort_gpu",
        lambda _py, _d: {"ok": False, "error": "LoadLibrary failed: 126"},
    )

    tts_runtime._install_ort(  # noqa: SLF001
        tmp_path / "uv.exe", tts_runtime.venv_dir(tmp_path), tmp_path,
        check_cancel=lambda: None, progress=lambda *_a: None,
    )

    flat = [arg for args in calls for arg in args]
    assert "onnxruntime-gpu==1.18.0" in flat
    assert "onnxruntime==1.18.0" in flat, "GPU 探测失败后必须回装 CPU 轮"
    state = tts_runtime.ort_state(tmp_path)
    assert state["variant"] == "cpu"
    assert "LoadLibrary failed: 126" in state["reason"]


def test_venv_imports_ok_requires_zero_exit(tmp_path: Path, monkeypatch: Any) -> None:
    py = _prime_venv(tmp_path)
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: Any) -> Any:
        seen.append(cmd)
        return _FakeCompleted(0 if "kokoro" in cmd[-1] else 1)

    monkeypatch.setattr(tts_runtime.subprocess, "run", fake_run)
    assert tts_runtime._venv_imports_ok(py, ("kokoro",)) is True
    assert tts_runtime._venv_imports_ok(py, ("funasr",)) is False
    assert seen[0][-1] == "import kokoro", "探针按模块逐个 import"
