"""桥协议纪律：共享 worker 的串行化（IO 锁）、就绪行只消费一次、关停钩子。

不需要隔离 venv——_ensure_worker/runtime_ready 全部替身，只钉协议与并发行为。
锁的「不插队」本身无法从外部观测（应答只带 ok 与否），这里钉住的是并发下
协议不炸、就绪行恰好读一次、失败应答原文上抛、关停幂等。
"""

from __future__ import annotations

import io
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.engines.tts.engines import indextts2 as mod
from dramaclip.engines.tts.engines.indextts2 import IndexTts2Engine


class _FakeStdin(io.TextIOBase):
    def __init__(self, proc: _FakeProc) -> None:
        self._proc = proc

    def write(self, job_line: str) -> int:
        self._proc.handle(json.loads(job_line))
        return len(job_line)

    def flush(self) -> None: ...


class _FakeProc:
    """同步应答的假 worker：write 即处理并排应答；terminate 记账。"""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.replies: list[str] = ['{"ready": true, "device": "cpu"}']
        self.terminated = False
        self.stdin = _FakeStdin(self)
        self.stdout = self

    def handle(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)
        self.replies.append(json.dumps({"id": job["id"], "ok": True}))

    def readline(self) -> str:
        return self.replies.pop(0) + "\n"

    def poll(self) -> int | None:
        return 1 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> _FakeProc:
    proc = _FakeProc()
    monkeypatch.setattr(mod, "runtime_ready", lambda: True)
    monkeypatch.setattr(mod, "_ensure_worker", lambda _d: proc)
    return proc


def test_ready_line_consumed_once_across_engine_instances(
    tmp_path: Path, bridge: _FakeProc
) -> None:
    IndexTts2Engine(tmp_path)._synth_one("a", "r.wav", tmp_path / "a.wav")
    IndexTts2Engine(tmp_path)._synth_one("b", "r.wav", tmp_path / "b.wav")

    assert len(bridge.jobs) == 2
    assert bridge.replies == [], "就绪行只被首个实例消费一次，第二个实例不再读"


def test_concurrent_synth_all_complete_and_ready_read_once(
    tmp_path: Path, bridge: _FakeProc
) -> None:
    engines = [IndexTts2Engine(tmp_path) for _ in range(4)]
    errors: list[BaseException] = []

    def run(index: int) -> None:
        try:
            engines[index]._synth_one(f"t{index}", "r.wav", tmp_path / f"o{index}.wav")
        except BaseException as exc:  # noqa: BLE001 - 线程内异常收集后统一断言
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(bridge.jobs) == 4
    assert bridge.replies == []


def test_failure_reply_raises_with_worker_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(mod, "runtime_ready", lambda: True)
    monkeypatch.setattr(mod, "_ensure_worker", lambda _d: proc)
    proc.replies.append(json.dumps({"ok": False, "error": "boom"}))

    with pytest.raises(RuntimeError, match="boom"):
        IndexTts2Engine(tmp_path)._synth_one("x", "r.wav", tmp_path / "x.wav")


def test_shutdown_worker_terminates_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(mod, "_PROC", proc)

    mod.shutdown_worker()

    assert proc.terminated
    assert mod._PROC is None
    mod.shutdown_worker()  # 再收一次：无进程在场也不炸


def test_worker_respawn_resets_hello_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = _FakeProc()
    dead.terminated = True  # poll() -> 1：旧进程已死，强制走重拉分支
    monkeypatch.setattr(mod, "_PROC", dead)
    monkeypatch.setattr(mod, "_HELLOED_FOR", dead)  # 旧进程的就绪状态
    monkeypatch.setattr(mod, "runtime_ready", lambda: True)
    fresh = _FakeProc()

    def fake_popen(*_args: Any, **_kwargs: Any) -> _FakeProc:
        return fresh

    fake_subprocess = SimpleNamespace(
        Popen=fake_popen,
        PIPE=subprocess.PIPE,
        CREATE_NO_WINDOW=0,
    )
    monkeypatch.setattr(mod, "subprocess", fake_subprocess)

    IndexTts2Engine(tmp_path)._synth_one("x", "r.wav", tmp_path / "x.wav")

    assert fresh.replies == [], "新进程的就绪行被重新读过（不是沿用旧进程状态）"
    assert len(fresh.jobs) == 1
