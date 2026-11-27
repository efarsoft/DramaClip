"""probe_torch 探针契约：全链顺序、回退记账、逐份忠实参数。假 torch 注入做确定性断言。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from dramaclip.engines.tts.workers.probe_torch import probe_device


class _FakeLine:
    """一根设备线的假象：availability 可调，最小运算可炸可过，记 empty_cache 次数。"""

    def __init__(self, available: bool, raises: bool = False) -> None:
        self.available = available
        self.raises = raises
        self.empty_cache_calls = 0

    def is_available(self) -> bool:
        return self.available

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1

    def _math(self) -> float:
        if self.raises:
            raise RuntimeError("no kernel for sm 52")
        return 4.0


def _make_torch(cuda: _FakeLine, xpu: _FakeLine) -> object:
    """假 torch：ones(4, device=线名) 走到对应线的最小运算，可炸可过。

    乘法必须定义在类上——SimpleNamespace 实例挂 __mul__ 不生效（特殊方法查类型）。"""

    class _Tensor:
        def __init__(self, line: _FakeLine) -> None:
            self._line = line

        def __mul__(self, _other: object) -> _Tensor:
            return self

        def sum(self) -> SimpleNamespace:
            return SimpleNamespace(item=self._line._math)

    class _Torch:
        def __init__(self) -> None:
            self.cuda = cuda
            self.xpu = xpu

        def ones(self, *_: int, device: str = "cpu") -> _Tensor:
            return _Tensor(cuda if device.startswith("cuda") else xpu)

    return _Torch()


def test_cpu_request_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    cuda = _FakeLine(available=True)
    monkeypatch.setitem(sys.modules, "torch", _make_torch(cuda, _FakeLine(True)))
    assert probe_device("cpu") == ("cpu", "")
    assert cuda.empty_cache_calls == 0


def test_gpu_tries_cuda_then_xpu_and_returns_first_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(_FakeLine(True), _FakeLine(False))
    )
    assert probe_device("gpu") == ("cuda", "")
    assert probe_device("auto") == ("cuda", "")


def test_cuda_unavailable_falls_to_xpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(_FakeLine(False), _FakeLine(True))
    )
    assert probe_device("auto") == ("xpu", "")


def test_both_lines_dead_join_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "torch",
        _make_torch(_FakeLine(False), _FakeLine(False)),
    )
    device, reason = probe_device("gpu")
    assert device == "cpu"
    assert reason == (
        "torch.cuda.is_available() = False；torch.xpu.is_available() = False"
    )


def test_cuda_kernel_boom_records_cache_clear_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cuda = _FakeLine(available=True, raises=True)
    # xpu 也死：cuda 线的炸因必须留进汇总 reason（xpu 活着时回退成功、reason 为空）
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(cuda, _FakeLine(False))
    )
    device, reason = probe_device("gpu")
    assert device == "cpu"
    assert reason == (
        "RuntimeError: no kernel for sm 52；torch.xpu.is_available() = False"
    )
    assert cuda.empty_cache_calls == 1


def test_cuda_boom_with_live_xpu_falls_back_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cuda = _FakeLine(available=True, raises=True)
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(cuda, _FakeLine(True))
    )
    assert probe_device("gpu") == ("xpu", "")
    assert cuda.empty_cache_calls == 1


def test_single_backend_request_only_tries_that_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 显式 cuda 只试 cuda 线：xpu 即便活着也不该被踩（显式承诺探针失败直接判失败）
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(_FakeLine(False), _FakeLine(True))
    )
    device, reason = probe_device("cuda")
    assert device == "cpu"
    assert reason == "torch.cuda.is_available() = False"


def test_funasr_params_keep_legacy_behavior(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # cuda_label="cuda:0" + stderr 提示 = funasr 原行为；默认无 stderr = 其余三份原行为
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(_FakeLine(True), _FakeLine(False))
    )
    assert probe_device("gpu", cuda_label="cuda:0", stderr_note=True) == ("cuda:0", "")
    monkeypatch.setitem(
        sys.modules,
        "torch",
        _make_torch(_FakeLine(True, raises=True), _FakeLine(False)),
    )
    probe_device("gpu", cuda_label="cuda:0", stderr_note=True)
    assert ">> CUDA 探针失败，回退 CPU" in capsys.readouterr().err


def test_default_has_no_stderr_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(
        sys.modules, "torch", _make_torch(_FakeLine(True, raises=True), _FakeLine(False))
    )
    device, reason = probe_device("gpu")
    assert device == "cpu"
    assert "RuntimeError" in reason
    assert capsys.readouterr().err == ""
