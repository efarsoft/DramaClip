"""funasr venv worker 桥：协议往返、生命周期、引擎双分支装配（E-2）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dramaclip.engines.analysis import transcriber
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.infra.model_manager import tts_runtime, worker_bridge

# 桩 worker：按协议应答，raw 固定为一条两字词的 funasr 形状输出（ndarray 之外的
# 最小形状）；"boom" 入参命中错误路径。
_STUB_WORKER = """\
import json, sys
cfg = json.loads(sys.argv[1])
print(json.dumps({"ready": True, "device": cfg.get("device_probe", "cpu")}), flush=True)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if req["kwargs"].get("boom"):
        print(json.dumps({"id": req["id"], "ok": False, "error": "boom 命中"}), flush=True)
        continue
    print(json.dumps({"id": req["id"], "ok": True, "raw": [
        {"text": "铺垫 反转", "timestamp": [[100, 400], [400, 900]]}
    ]}), flush=True)
"""


@pytest.fixture()
def stub_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = tmp_path / "stub_worker.py"
    stub.write_text(_STUB_WORKER, encoding="utf-8")
    monkeypatch.setattr(tts_runtime, "venv_python", lambda _d: Path(sys.executable))
    from dramaclip.engines.tts.workers import funasr_worker

    monkeypatch.setattr(funasr_worker, "__file__", str(stub))


def test_bridge_roundtrip_error_path_and_close(stub_runtime: None) -> None:
    worker = transcriber._spawn_funasr_worker({
        "engine": "sensevoice", "device_probe": "cuda",
    })
    try:
        assert worker.device == "cuda", "就绪行回带 worker 实际解析到的 device"
        raw = worker.generate(input="x.wav", cache={}, language="zh", output_timestamp=True)
        assert raw[0]["text"] == "铺垫 反转"
        with pytest.raises(RuntimeError, match="boom"):
            worker.generate(input="x.wav", boom=True)
    finally:
        transcriber.shutdown_funasr_workers()
    assert worker._proc is None, "shutdown 后进程句柄收走"


def test_sensevoice_takes_worker_branch_when_inproc_missing(
    stub_runtime: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcriber, "_inproc_funasr", lambda: None)
    engine = transcriber.SenseVoiceEngine(models_dir=Path("unused"))
    segments = engine.transcribe(Path("x.wav"))
    assert segments == [AsrSegment(start=0.1, end=0.9, text="铺垫反转")]
    assert engine._model is not None and isinstance(engine._model, transcriber._FunasrWorker)
    transcriber.shutdown_funasr_workers()


def test_worker_missing_runtime_gives_install_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无进程内 funasr 且 venv 未装：启动失败文案必须指向安装入口，不许裸 OSError。"""
    monkeypatch.setattr(transcriber, "_inproc_funasr", lambda: None)
    monkeypatch.setattr(tts_runtime, "venv_python", lambda _d: tmp_path / "nope" / "python.exe")
    engine = transcriber.SenseVoiceEngine(models_dir=tmp_path)
    with pytest.raises(RuntimeError, match="安装运行环境"):
        engine.transcribe(Path("x.wav"))


def test_analysis_ready_is_pure_file_check(tmp_path: Path) -> None:
    assert tts_runtime.analysis_ready(tmp_path) is False
    py = tmp_path / "runtimes" / "tts-venv" / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    assert tts_runtime.analysis_ready(tmp_path) is False, "只有解释器不算装好"
    pkg = tmp_path / "runtimes" / "tts-venv" / "Lib" / "site-packages" / "funasr"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    assert tts_runtime.analysis_ready(tmp_path) is True


def test_supported_follows_runtime_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    from dramaclip.engines.analysis import runtime

    monkeypatch.setitem(sys.modules, "funasr", None)  # import funasr → ImportError
    monkeypatch.setattr(tts_runtime, "analysis_ready", lambda _d: True)
    assert {"sensevoice", "paraformer"} <= runtime.supported()
    monkeypatch.setattr(tts_runtime, "analysis_ready", lambda _d: False)
    assert "sensevoice" not in runtime.supported(), "两处都不可用时不进清单（引导安装）"


def test_worker_shutdown_registry_drains(stub_runtime: None) -> None:
    first = transcriber._spawn_funasr_worker({"engine": "sensevoice"})
    second = transcriber._spawn_funasr_worker({"engine": "sensevoice"})
    transcriber.shutdown_funasr_workers()
    assert first._proc is None and second._proc is None
    assert worker_bridge._ACTIVE_WORKERS == [], "注册表排空：二次 shutdown 空操作不炸"
    transcriber.shutdown_funasr_workers()
