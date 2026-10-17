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
