"""CosyVoice 桥协议纪律：串行化（IO 锁）、就绪行按进程身份记账、关停钩子、
本地目录/仓库回退、长文本切块。不需要隔离 venv——_ensure_worker/runtime_ready
全部替身，只钉协议与并发行为（与 test_indextts2_bridge 同一套钉法）。"""

from __future__ import annotations

import io
import json
import subprocess
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.engines.tts import factory as tts_factory
from dramaclip.engines.tts.engines import cosyvoice as mod
from dramaclip.engines.tts.engines.cosyvoice import CosyVoiceEngine
from dramaclip.infra.model_manager.registry import builtin_specs


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
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(mod._SAMPLE_RATE)
            wav.writeframes(b"\x01\x00" * (len(job["text"]) * 10))
        self.replies.append(json.dumps({"id": job["id"], "ok": True}))

    def readline(self) -> str:
        return self.replies.pop(0) + "\n"

    def poll(self) -> int | None:
        return 1 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture
def bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeProc:
    proc = _FakeProc()
    monkeypatch.setattr(mod, "runtime_ready", lambda: True)
    monkeypatch.setattr(mod, "_ensure_worker", lambda _d: proc)
    return proc


def _ref(tmp_path: Path) -> str:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"riff")
    return str(ref)


def test_ready_line_consumed_once_across_engine_instances(
    tmp_path: Path, bridge: _FakeProc
) -> None:
    ref = _ref(tmp_path)
    CosyVoiceEngine(tmp_path).synthesize("a", ref, tmp_path / "a.wav")
    CosyVoiceEngine(tmp_path).synthesize("b", ref, tmp_path / "b.wav")

    assert len(bridge.jobs) == 2
    assert bridge.replies == [], "就绪行只被首个实例消费一次，第二个实例不再读"


def test_concurrent_synth_all_complete_and_ready_read_once(
    tmp_path: Path, bridge: _FakeProc
) -> None:
    ref = _ref(tmp_path)
    engines = [CosyVoiceEngine(tmp_path) for _ in range(4)]
    errors: list[BaseException] = []

    def run(index: int) -> None:
        try:
            engines[index].synthesize(f"t{index}", ref, tmp_path / f"o{index}.wav")
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
        CosyVoiceEngine(tmp_path)._synth_one("x", "r.wav", tmp_path / "x.wav")


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

    fake_subprocess = SimpleNamespace(Popen=fake_popen, PIPE=subprocess.PIPE, CREATE_NO_WINDOW=0)
    monkeypatch.setattr(mod, "subprocess", fake_subprocess)

    CosyVoiceEngine(tmp_path)._synth_one("x", "r.wav", tmp_path / "x.wav")

    assert fresh.replies == [], "新进程的就绪行被重新读过（不是沿用旧进程状态）"
    assert len(fresh.jobs) == 1


def test_long_text_is_split_into_clone_budget_and_concatenated(
    tmp_path: Path, bridge: _FakeProc
) -> None:
    ref = _ref(tmp_path)
    text = "克隆解说词。" * 100  # 600 字符 → 预算 150 → 4 块
    out = tmp_path / "n0.wav"

    result = CosyVoiceEngine(tmp_path).synthesize(text, ref, out)

    assert result == out and out.is_file()
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == mod._SAMPLE_RATE
        assert wav.getnframes() == len(text) * 10, "各块帧数之和，无丢块"


def test_missing_reference_audio_blocks(tmp_path: Path, bridge: _FakeProc) -> None:
    with pytest.raises(ValueError, match="参考音频"):
        CosyVoiceEngine(tmp_path).synthesize("词", str(tmp_path / "nope.wav"), tmp_path / "o.wav")


# ---- 工厂 / 清单一致性（接线收口）----


def test_factory_model_dir_matches_registry_placement(tmp_path: Path) -> None:
    """两代各自对上清单 placement：300M 与 v3 同桥不同目录，互不串模型。"""
    for engine in ("cosyvoice", "cosyvoice3"):
        spec = next(s for s in builtin_specs() if s.engine == engine)
        assert tts_factory.model_dir(tmp_path, engine) == tmp_path / spec.placement


def test_tts_text_prefix_by_generation() -> None:
    """v1/v2 带语言标签、v3 带系统提示词前缀（两代约定不同，混用即哑火）。"""
    from dramaclip.engines.tts.workers.cosyvoice_worker import _tts_text

    assert _tts_text("台词", "zh", False) == "<|zh|>台词"
    assert _tts_text("台词", "zh", True) == "You are a helpful assistant.<|endofprompt|>台词"
    assert _tts_text("A<|endofprompt|>B", "zh", True) == "A<|endofprompt|>B", "已有前缀不二次包"


def test_engine_requires_files_declared_in_bridge(tmp_path: Path) -> None:
    """桥的判据文件表与 registry._REQUIREMENTS 同口径：任一侧单独漂移都会红。"""
    from dramaclip.infra.model_manager import registry

    spec = next(s for s in builtin_specs() if s.engine == "cosyvoice")
    assert set(mod._REQUIRED_FILES) == set(registry._REQUIREMENTS["cosyvoice"])  # noqa: SLF001
    assert spec.placement.endswith("cosyvoice300m"), "目录名跟随清单 placement"


def test_capabilities_declare_cloning_without_emotion(tmp_path: Path) -> None:
    caps = CosyVoiceEngine(tmp_path).capabilities()
    assert caps.supports_cloning is True
    assert caps.supports_emotion is False, "cross_lingual 桥不透传情绪——接进来才算数"
    assert caps.speed_control == "none"
    assert caps.available is False, "env 未装时如实不可用"


def test_runtime_ready_false_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_RUNTIME_OK", None)
    monkeypatch.setattr(
        mod, "_env_python", lambda: Path("D:/no-such-runtimes/cosyvoice-venv/Scripts/python.exe")
    )
    assert mod.runtime_ready() is False


def test_worker_without_src_env_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有源码目录变量时必须报错说清来路，而不是假装能跑（诚实探测）。"""
    monkeypatch.delenv("DRAMACLIP_COSYVOICE_SRC", raising=False)
    from dramaclip.engines.tts.workers import cosyvoice_worker

    with pytest.raises(RuntimeError, match="DRAMACLIP_COSYVOICE_SRC"):
        cosyvoice_worker._src_dir()
