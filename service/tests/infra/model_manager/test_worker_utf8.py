"""worker 协议是 UTF-8：子进程必须按 UTF-8 解码 stdin，否则中文变鬼字。

Windows 中文系统上子进程 stdin 默认走 GBK/surrogateescape，父进程写入的
UTF-8 字节会被解成带孤立代理项的字符串——CosyVoice3 的 Rust tokenizer
直接拒绝（TextEncodeInput），IndexTTS/Kokoro 则会安静地合成鬼话。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.engines.tts.engines import cosyvoice, indextts2
from dramaclip.infra.model_manager import tts_runtime, worker_bridge

_STUB_WORKER = """\
import json, sys
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    print(json.dumps({
        "id": req["id"], "ok": True,
        "match": req["text"] == "你好，世界",
    }, ensure_ascii=False), flush=True)
"""


def test_venv_worker_decodes_chinese_as_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = tmp_path / "stub_worker.py"
    stub.write_text(_STUB_WORKER, encoding="utf-8")
    monkeypatch.setattr(tts_runtime, "venv_python", lambda _d: Path(sys.executable))

    worker = worker_bridge.VenvWorker(stub, {})
    try:
        worker.start()
        reply = worker.request({"text": "你好，世界"})
        assert reply["match"] is True, "worker 读到的文本被非 UTF-8 解码污染"
    finally:
        worker.close()


class _FakeProc:
    def poll(self) -> None:
        return None


def _fake_subprocess(captured: dict[str, Any]) -> SimpleNamespace:
    def popen(_cmd: list[str], **kwargs: Any) -> _FakeProc:
        captured.update(kwargs)
        return _FakeProc()

    return SimpleNamespace(Popen=popen, PIPE=object(), CREATE_NO_WINDOW=0)


def test_cosyvoice_worker_is_launched_with_utf8_stdio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(cosyvoice, "_PROC", None)
    monkeypatch.setattr(cosyvoice, "_PROC_DEVICE", None)
    monkeypatch.setattr(cosyvoice, "_HELLO", {})
    monkeypatch.setattr(cosyvoice, "subprocess", _fake_subprocess(captured))

    assert cosyvoice._ensure_worker(tmp_path, "cpu") is not None
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


def test_indextts_worker_is_launched_with_utf8_stdio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(indextts2, "_PROC", None)
    monkeypatch.setattr(indextts2, "_PROC_DEVICE", None)
    monkeypatch.setattr(indextts2, "_HELLO", {})
    monkeypatch.setattr(indextts2, "_venv_python", lambda: tmp_path / "python.exe")
    monkeypatch.setattr(indextts2, "_src_dir", lambda: tmp_path)
    monkeypatch.setattr(indextts2, "subprocess", _fake_subprocess(captured))

    assert indextts2._ensure_worker(tmp_path, "cpu") is not None
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
