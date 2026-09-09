"""GPU 探测解析与缓存状态机；transcriber CUDA 回退。"""

from __future__ import annotations

import sys
import types

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
