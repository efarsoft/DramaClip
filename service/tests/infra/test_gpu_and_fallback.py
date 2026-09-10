"""GPU 探测解析与缓存状态机；transcriber CUDA 回退。"""

from __future__ import annotations

import sys
import types
from collections.abc import Generator
from pathlib import Path

from dramaclip.engines.analysis.transcriber import FasterWhisperEngine
from dramaclip.infra import gpu


def test_parse_query_output() -> None:
    assert gpu.parse_query_output("NVIDIA GeForce RTX 4060, 546.33\n") == (
        "NVIDIA GeForce RTX 4060",
        "546.33",
    )
    assert gpu.parse_query_output("") == ("", "")
    assert gpu.parse_query_output("NVIDIA A100\nNVIDIA A10\n") == ("NVIDIA A100", "")


def test_parse_max_cuda_tolerates_umd_rename() -> None:
    assert gpu.parse_max_cuda("| CUDA Version : 12.4 |") == "12.4"
    assert gpu.parse_max_cuda("| CUDA UMD Version : 13.0 |") == "13.0"
    assert gpu.parse_max_cuda("no driver info") == ""


def test_detect_reports_cpu_when_smi_missing(monkeypatch) -> None:
    monkeypatch.setattr(gpu, "_smi_paths", lambda: [])
    result = gpu.detect()
    assert result["ready"] is True
    assert result["vendor"] == "none"


class _FakeWhisper:
    created: list[str] = []

    def __init__(self, size: str, device: str = "cpu", download_root: str | None = None) -> None:
        _FakeWhisper.created.append(device)
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found")
        self.device = device


def test_cuda_failure_falls_back_to_cpu(monkeypatch) -> None:
    fake = types.SimpleNamespace(WhisperModel=_FakeWhisper)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _FakeWhisper.created.clear()
    engine = FasterWhisperEngine("base", device="cuda")
    model = engine._ensure_model()
    assert model.device == "cpu"  # type: ignore[attr-defined]
    assert _FakeWhisper.created == ["cuda", "cpu"]


def test_cpu_errors_are_not_swallowed(monkeypatch) -> None:
    class _Boom:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("disk full")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=_Boom))
    engine = FasterWhisperEngine("base", device="cpu")
    try:
        engine._ensure_model()
    except RuntimeError as exc:
        assert "disk full" in str(exc)
    else:  # pragma: no cover - 断言失败
        raise AssertionError("CPU 构建错误不应被吞掉")


class _FakeLazyWhisper:
    """构造成功、首次推理才抛 CUDA 缺库（CTranslate2 惰性计算的真实行为）。"""

    created: list[str] = []

    def __init__(self, _size: str, device: str = "cpu", download_root: str | None = None) -> None:
        self.device = device
        _FakeLazyWhisper.created.append(device)

    def transcribe(self, _wav: object, language: str = "zh", vad_filter: bool = False):  # type: ignore[no-untyped-def]
        if self.device == "cuda":
            def _boom() -> Generator[None, None, None]:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield  # pragma: no cover

            return _boom(), None
        seg = types.SimpleNamespace(start=0.0, end=1.0, text=" 你好 ")
        return iter([seg]), None


def test_cuda_failure_during_inference_falls_back(monkeypatch) -> None:
    fake = types.SimpleNamespace(WhisperModel=_FakeLazyWhisper)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _FakeLazyWhisper.created.clear()
    engine = FasterWhisperEngine("base", device="cuda")
    segments = engine.transcribe(Path("x.wav"))
    assert [s.text for s in segments] == ["你好"]
    assert _FakeLazyWhisper.created == ["cuda", "cpu"]
    # CPU 模型已缓存：第二集直接复用，不再重复走失败的 CUDA 路径
    engine.transcribe(Path("x.wav"))
    assert _FakeLazyWhisper.created == ["cuda", "cpu"]
