"""funasr worker 的就绪设备必须读模型真实落点，不与探针结果混为一谈。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dramaclip.engines.tts.workers import funasr_worker


class _Parameter:
    def __init__(self, kind: str) -> None:
        self.device = SimpleNamespace(type=kind)


class _Inner:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def parameters(self) -> Any:
        yield _Parameter(self.kind)


def test_model_device_prefers_parameter_placement() -> None:
    lying = SimpleNamespace(model=_Inner("cpu"), kwargs={"device": "cuda:0"})
    assert funasr_worker._model_device(lying) == "cpu"
    assert funasr_worker._model_device(SimpleNamespace(kwargs={"device": "cuda:0"})) == "cuda"
    assert funasr_worker._model_device(SimpleNamespace()) is None
