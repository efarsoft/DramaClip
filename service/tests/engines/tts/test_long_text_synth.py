"""B7 引擎接线：长文本先 split_long_text 切块、逐块合成、拼接成**单个**落盘文件。

契约（批次一钉死，绝不许动）：synthesize(text, voice, out_path) -> out_path 单文件；
缓存 key 用整段原文（切分前），切分/拼接是 synthesize 内部实现细节。
重依赖全部替身：edge_tts 进 sys.modules 假货、kokoro 假 pipeline（真 numpy/soundfile
落盘，产物用 soundfile 复测）、indextts2 假 worker 进程（真 wave 落盘，产物复测）。
"""

from __future__ import annotations

import io
import json
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.tts.engines import indextts2 as indextts2_mod
from dramaclip.engines.tts.engines.edge import EdgeTtsEngine
from dramaclip.engines.tts.engines.indextts2 import IndexTts2Engine
from dramaclip.engines.tts.engines.kokoro import KokoroEngine
from dramaclip.engines.tts.text_split import split_long_text

# ---------------------------------------------------------------- edge（mp3 字节拼接）


class _FakeCommunicate:
    calls: list[str] = []

    def __init__(self, text: str, voice: str, **kwargs: Any) -> None:
        _FakeCommunicate.calls.append(text)
        self.text = text

    async def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.text.encode("utf-8"))


@pytest.fixture
def fake_edge_tts(monkeypatch: pytest.MonkeyPatch) -> type[_FakeCommunicate]:
    _FakeCommunicate.calls = []
    monkeypatch.setitem(
        sys.modules, "edge_tts", type("m", (), {"Communicate": _FakeCommunicate})
    )
    return _FakeCommunicate


def test_edge_long_text_is_split_synthesized_and_concatenated(
    tmp_path: Path, fake_edge_tts: type[_FakeCommunicate]
) -> None:
    text = "第一段解说。" * 80  # 480 字符 CJK → 上限 200 → 多块
    chunks, _ = split_long_text(text)
    assert len(chunks) > 1
    out = tmp_path / "n0.mp3"

    result = EdgeTtsEngine().synthesize(text, "zh-CN-YunxiNeural", out)

    assert result == out and out.is_file(), "契约：返回单个落盘文件"
    assert fake_edge_tts.calls == chunks, "逐块合成，块序不许乱"
    assert out.read_bytes() == "".join(chunks).encode("utf-8"), "拼接=各块按序连接"
    assert not list(tmp_path.glob("*parts*")), "分块临时目录必须清干净"


def test_edge_short_text_takes_the_single_request_path(
    tmp_path: Path, fake_edge_tts: type[_FakeCommunicate]
) -> None:
    out = tmp_path / "n0.mp3"
    EdgeTtsEngine().synthesize("就一句话。", "zh-CN-YunxiNeural", out)
    assert fake_edge_tts.calls == ["就一句话。"], "单块走旧路径：整段一次请求"


# ---------------------------------------------------------------- kokoro（numpy 拼接）


class _FakePipeline:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: Any, voice: str | None = None, **kw: Any) -> list:
        import numpy as np

        self.calls.append(text if isinstance(text, str) else "|".join(text))
        # 每字符 10 个采样点：拼接后总帧数可复测
        return [(None, None, np.ones(len(text) * 10, dtype="float32"))]


def _kokoro_with_fake(tmp_path: Path, pipeline: _FakePipeline) -> KokoroEngine:
    engine = KokoroEngine(tmp_path)
    engine._pipeline = pipeline
    engine._loaded = True
    return engine


def test_kokoro_long_text_is_split_and_written_as_one_wav(tmp_path: Path) -> None:
    import soundfile as sf

    text = "这一段旁白很长。" * 60  # 480 字符 CJK → 3 块
    chunks, _ = split_long_text(text)
    assert len(chunks) > 1
    pipeline = _FakePipeline()
    out = tmp_path / "n0.wav"

    result = _kokoro_with_fake(tmp_path, pipeline).synthesize(text, "zf_001", out)

    assert result == out and out.is_file()
    assert pipeline.calls == chunks, "逐块喂 pipeline"
    audio, sr = sf.read(out)
    assert sr == 24000
    assert len(audio) == sum(len(c) * 10 for c in chunks), "拼接后总帧数=各块之和"


def test_kokoro_short_text_single_pipeline_call(tmp_path: Path) -> None:
    pipeline = _FakePipeline()
    out = tmp_path / "n0.wav"
    _kokoro_with_fake(tmp_path, pipeline).synthesize("短句。", "zf_001", out)
    assert pipeline.calls == ["短句。"]


# ---------------------------------------------------------------- indextts2（wave 帧拼接）

_CLONE_MAX = indextts2_mod._CLONE_MAX_CHARS


class _FakeStdin(io.TextIOBase):
    def __init__(self, proc: _FakeProc) -> None:
        self._proc = proc

    def write(self, job_line: str) -> int:
        self._proc.handle(json.loads(job_line))
        return len(job_line)

    def flush(self) -> None: ...


class _FakeProc:
    """假 worker：每个 job 真写一个 22050Hz 单声道 wav（每字符 10 帧），按序回应答。"""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.replies: list[str] = ['{"ready": true, "device": "cpu"}']
        self.stdin = _FakeStdin(self)
        self.stdout = self

    def handle(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)
        text = job["text"]
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x01\x00" * (len(text) * 10))
        self.replies.append(json.dumps({"id": job["id"], "ok": True}))

    def readline(self) -> str:
        return self.replies.pop(0) + "\n"


@pytest.fixture
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> _FakeProc:
    proc = _FakeProc()
    monkeypatch.setattr(indextts2_mod, "runtime_ready", lambda: True)
    monkeypatch.setattr(indextts2_mod, "_ensure_worker", lambda _d: proc)
    return proc


def test_indextts2_long_text_uses_clone_budget_and_returns_one_wav(
    tmp_path: Path, fake_worker: _FakeProc
) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"riff")
    text = "克隆解说词。" * 100  # 600 字符 → 克隆预算 120 → 5 块
    chunks, _ = split_long_text(text, max_chars=_CLONE_MAX)
    assert len(chunks) == 5 and all(len(c) <= _CLONE_MAX for c in chunks)
    out = tmp_path / "n0.wav"

    result = IndexTts2Engine(tmp_path).synthesize(text, str(ref), out)

    assert result == out and out.is_file()
    assert [j["text"] for j in fake_worker.jobs] == chunks, "逐块送 worker"
    assert all(j["voice"] == str(ref.resolve()) for j in fake_worker.jobs)
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == 22050
        assert wav.getnframes() == sum(len(c) * 10 for c in chunks), "帧拼接无丢块"


def test_indextts2_short_text_single_job_to_out_path(
    tmp_path: Path, fake_worker: _FakeProc
) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"riff")
    out = tmp_path / "n0.wav"

    IndexTts2Engine(tmp_path).synthesize("短句。", str(ref), out)

    assert len(fake_worker.jobs) == 1
    assert fake_worker.jobs[0]["out"] == str(out), "单块直接写目标路径（旧路径）"
    assert out.is_file()
