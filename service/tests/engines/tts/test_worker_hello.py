"""worker 就绪行必须带 requested/device/fallback/reason；父进程不得丢弃。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.tts.engines import indextts2


class _FakeStdin:
    def write(self, _text: str) -> None: ...

    def flush(self) -> None: ...


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def readline(self) -> str:
        return next(self._lines, "")


class _FakeProc:
    stdin = _FakeStdin()
    pid = 1


def _proc_with(lines: list[dict[str, Any]]) -> subprocess.Popen[str]:
    proc = _FakeProc()
    proc.stdout = _FakeStdout([json.dumps(line) + "\n" for line in lines])  # type: ignore[attr-defined]
    return proc  # type: ignore[return-value]


def test_hello_device_is_kept_for_later_instances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = _proc_with([
        {"ready": True, "requested": "auto", "device": "cuda",
         "fallback": False, "reason": ""},
        {"id": "0", "ok": True},
        {"id": "0", "ok": True},
    ])
    monkeypatch.setattr(indextts2, "_PROC", proc)
    monkeypatch.setattr(indextts2, "_HELLO", {})
    monkeypatch.setattr(indextts2, "_ensure_worker", lambda _d, _device="auto": proc)
    monkeypatch.setattr(indextts2, "runtime_ready", lambda: True)

    path = tmp_path / "out.wav"
    indextts2.IndexTts2Engine(tmp_path, device="auto")._synth_one("你好", "ref.wav", path)
    other = indextts2.IndexTts2Engine(tmp_path, device="auto")
    other._synth_one("你好", "ref.wav", path)

    report = other.compute()
    assert report is not None
    assert (report.resolved, report.actual) == ("cuda", "cuda")
    assert indextts2._HELLO[proc]["device"] == "cuda", "第二个实例复用了同一进程的就绪行"


def test_hello_failure_raises_with_worker_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = _proc_with([
        {"ready": False, "error": "请求 CUDA 但探针失败：cuda 不可用"},
    ])
    monkeypatch.setattr(indextts2, "_PROC", proc)
    monkeypatch.setattr(indextts2, "_HELLO", {})
    monkeypatch.setattr(indextts2, "_ensure_worker", lambda _d, _device="auto": proc)

    with pytest.raises(RuntimeError, match="请求 CUDA"):
        indextts2.IndexTts2Engine(tmp_path, device="cuda")._synth_one(
            "词", "ref.wav", tmp_path / "o.wav"
        )
