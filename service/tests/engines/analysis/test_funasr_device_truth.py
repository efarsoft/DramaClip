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


def _reader(engine_cls: type) -> Any:
    """设备助手名字的读者 = 引擎类所在模块。

    拆分后引擎在 asr 包内 from-import 绑死了 common 的助手名；给门面
    transcriber 打桩只改门面那份绑定，引擎读不到——桩静默失效，开发机
    （真探针恰好放行）假绿，CPU torch 的 CI 上才红。桩必须打在读者上。
    """
    return sys.modules[engine_cls.__module__]


def _stub_probe(
    monkeypatch: pytest.MonkeyPatch, engine_cls: type, *, problem: str = ""
) -> list[str]:
    """真算探针换成记账桩：返回调用记录，由用例断言桩确实被走到。"""

    calls: list[str] = []

    def _probe(device: str) -> str:
        calls.append(device)
        return problem

    monkeypatch.setattr(_reader(engine_cls), "_probe_cuda_op", _probe)
    return calls


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
    probed = _stub_probe(monkeypatch, engine_cls)

    engine = engine_cls(models_dir=tmp_path, device="cuda")

    with pytest.raises(compute.ComputeUnavailableError, match="cpu"):
        engine._ensure_model()
    assert probed, "探针桩必须被走到：没走到说明桩没打在读者模块上"


@pytest.mark.parametrize("engine_cls", [SenseVoiceEngine, ParaformerEngine])
def test_probe_problem_refuses_explicit_cuda_before_funasr_loads(
    engine_cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真算探针判不可算时，显式 cuda 在 funasr 加载前就拒绝（不许静默落 CPU）。"""
    fake = _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")
    problem = "模拟：Torch not compiled with CUDA enabled"
    probed = _stub_probe(monkeypatch, engine_cls, problem=problem)

    engine = engine_cls(models_dir=tmp_path, device="cuda")

    with pytest.raises(compute.ComputeUnavailableError, match="CUDA"):
        engine._ensure_model()
    assert probed == ["cuda:0"]
    assert fake.instances == [], "探针已判不可算，不许再让 funasr 静默落 CPU"


@pytest.mark.parametrize("engine_cls", [SenseVoiceEngine, ParaformerEngine])
def test_probe_problem_falls_auto_back_to_cpu_with_reason(
    engine_cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """auto 解析到 cuda 但真算失败（坏驱动一类）：回退 CPU，回执记 fallback 与原因。"""
    _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")
    problem = "模拟：RuntimeError: Found no NVIDIA driver"
    probed = _stub_probe(monkeypatch, engine_cls, problem=problem)
    monkeypatch.setattr(
        _reader(engine_cls), "_resolve_torch_device", lambda _device: "cuda:0"
    )

    engine = engine_cls(models_dir=tmp_path, device="auto")
    engine._ensure_model()

    report = engine.compute()
    assert report is not None
    assert (report.requested, report.resolved, report.actual) == ("auto", "cuda", "cpu")
    assert report.fallback is True and problem in report.reason
    assert probed == ["cuda:0"]


@pytest.mark.parametrize("engine_cls", [SenseVoiceEngine, ParaformerEngine])
def test_auto_silent_fallback_records_cpu_with_reason(
    engine_cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_funasr(monkeypatch, placement="cpu", resolved="cpu")
    _stub_probe(monkeypatch, engine_cls)
    monkeypatch.setattr(
        _reader(engine_cls), "_resolve_torch_device", lambda _device: "cuda:0"
    )

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
    probed = _stub_probe(monkeypatch, SenseVoiceEngine)
    monkeypatch.setattr(
        _reader(SenseVoiceEngine), "_resolve_torch_device", lambda _device: "cuda:0"
    )

    engine = SenseVoiceEngine(models_dir=tmp_path, device="cuda")
    engine._ensure_model()
    assert probed == ["cuda:0"]

    report = engine.compute()
    assert report is not None
    assert (report.requested, report.resolved, report.actual) == ("cuda", "cuda", "cuda")
    assert report.fallback is False


def test_model_device_prefers_physical_placement_over_funasr_resolution() -> None:
    lying = SimpleNamespace(model=_Inner("cpu"), kwargs={"device": "cuda:0"})
    assert transcriber._model_device(lying) == "cpu", "参数设备是物理证据，优先于解析值"
    assert transcriber._model_device(SimpleNamespace(kwargs={"device": "cuda:0"})) == "cuda"
    assert transcriber._model_device(SimpleNamespace()) is None
