"""funasr 进程内路径的算力真相：actual 必须由模型落点证明，不许从请求串猜。

funasr 的 AutoModel 在 torch 无 CUDA 时把 device 静默改成 cpu（auto_model.py
只打一条 warning），而引擎旧实现按请求串记 actual=cuda——tts-venv（torch
2.8.0+cpu）因此产出 `asr.funasr.cuda PASS actual=cuda` 的假绿。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.engines.analysis import transcriber
from dramaclip.engines.analysis.transcriber import ParaformerEngine, SenseVoiceEngine
from dramaclip.infra import compute


class _Parameter:
    def __init__(self, kind: str) -> None:
        self.device = SimpleNamespace(type=kind)


class _Inner:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def parameters(self) -> Any:
        yield _Parameter(self.kind)


def _install_fake_funasr(
    monkeypatch: pytest.MonkeyPatch, *, placement: str, resolved: str
) -> type:
    """假 AutoModel：按 funasr 形状暴露 .model 参数与解析后的 .kwargs["device"]。"""

    class _FakeAutoModel:
        instances: list[_FakeAutoModel] = []

        def __init__(self, model: str, **kwargs: Any) -> None:
            self.model = _Inner(placement)
            self.kwargs = {"device": resolved}
            self.init_kwargs = kwargs
            _FakeAutoModel.instances.append(self)

    monkeypatch.setitem(sys.modules, "funasr", type("m", (), {"AutoModel": _FakeAutoModel}))
    return _FakeAutoModel


def _torch_has_cuda() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def test_explicit_cuda_on_cpu_torch_fails_before_funasr_silently_lands_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if _torch_has_cuda():
        pytest.skip("本机 torch 带 CUDA，静默回退场景不复现")
    fake = _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")

    engine = SenseVoiceEngine(models_dir=tmp_path, device="cuda")

    with pytest.raises(compute.ComputeUnavailableError, match="CUDA"):
        engine._ensure_model()
    assert fake.instances == [], "探针已判 CUDA 不可算，不许再让 funasr 静默落 CPU"


@pytest.mark.parametrize("engine_cls", [SenseVoiceEngine, ParaformerEngine])
def test_explicit_cuda_landing_on_cpu_is_a_broken_promise(
    engine_cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")
    monkeypatch.setattr(transcriber, "_probe_cuda_op", lambda _device: "", raising=False)

    engine = engine_cls(models_dir=tmp_path, device="cuda")

    with pytest.raises(compute.ComputeUnavailableError, match="cpu"):
        engine._ensure_model()


@pytest.mark.parametrize("engine_cls", [SenseVoiceEngine, ParaformerEngine])
def test_auto_silent_fallback_records_cpu_with_reason(
    engine_cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")
    monkeypatch.setattr(transcriber, "_probe_cuda_op", lambda _device: "", raising=False)
    monkeypatch.setattr(transcriber, "_resolve_torch_device", lambda _device: "cuda:0")

    engine = engine_cls(models_dir=tmp_path, device="auto")
    engine._ensure_model()

    report = engine.compute()
    assert report is not None
    assert (report.requested, report.resolved, report.actual) == ("auto", "cuda", "cpu")
    assert report.fallback is True
    assert "cpu" in report.reason


def test_cuda_placement_evidence_is_reported_as_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_funasr(monkeypatch, placement="cuda", resolved="cuda:0")
    monkeypatch.setattr(transcriber, "_probe_cuda_op", lambda _device: "", raising=False)
    monkeypatch.setattr(transcriber, "_resolve_torch_device", lambda _device: "cuda:0")

    engine = SenseVoiceEngine(models_dir=tmp_path, device="cuda")
    engine._ensure_model()

    report = engine.compute()
    assert report is not None
    assert (report.requested, report.resolved, report.actual) == ("cuda", "cuda", "cuda")
    assert report.fallback is False


def test_model_device_prefers_physical_placement_over_funasr_resolution() -> None:
    lying = SimpleNamespace(model=_Inner("cpu"), kwargs={"device": "cuda:0"})
    assert transcriber._model_device(lying) == "cpu", "参数设备是物理证据，优先于解析值"
    assert transcriber._model_device(SimpleNamespace(kwargs={"device": "cuda:0"})) == "cuda"
    assert transcriber._model_device(SimpleNamespace()) is None
