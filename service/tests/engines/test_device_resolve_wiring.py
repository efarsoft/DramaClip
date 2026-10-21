"""设备解析接线：解析发生在构造之前，引擎收到的是解析后的设备。

本文件只验**接线**（判据本身在 `tests/infra/test_device_resolve.py`）：
- `_build_transcriber` / `factory.create` 传给引擎的 `device` 来自解析结论，不是设置原值；
- 显式 `cuda` 撞上不可用的 cap 时必须**在构造引擎之前**炸——模型加载、worker 拉起
  都不该发生（规格 §3.6：cuda 是承诺）；
- 云端引擎与没有 cap 的引擎（kokoro）不进解析表：透传，不替它们宣布可用性。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis import runtime
from dramaclip.engines.analysis import transcriber as asr_mod
from dramaclip.engines.narration import synthesis as synthesis_mod
from dramaclip.engines.tts import factory
from dramaclip.engines.tts.engines import cosyvoice as cosyvoice_mod
from dramaclip.engines.tts.engines import indextts2 as indextts2_mod
from dramaclip.engines.tts.engines import kokoro as kokoro_mod
from dramaclip.infra import compute, config, device_resolve
from dramaclip.infra.model_manager import registry

_LOCAL_ASR = ("faster_whisper", "sensevoice", "paraformer")
_LOCAL_TTS = ("indextts2", "cosyvoice", "cosyvoice3")
_CAP = {
    "asr.faster_whisper": "faster_whisper_gpu",
    "asr.sensevoice": "funasr_gpu",
    "asr.paraformer": "funasr_gpu",
    "tts.indextts2": "indextts2_gpu",
    "tts.cosyvoice": "indextts2_gpu",
    "tts.cosyvoice3": "indextts2_gpu",
}


class _Recorder:
    """假解析器：按 `blocked` 集合决定抛错，按 `device` 返回解析结论。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.blocked: set[str] = set()
        self.device = "cpu"

    def __call__(
        self, kind: str, engine: str, requested: str | None, data_dir: Path
    ) -> device_resolve.DeviceResolution | None:
        self.calls.append(
            {"kind": kind, "engine": engine, "requested": requested, "data_dir": data_dir}
        )
        table = device_resolve.ASR_ENGINES if kind == "asr" else device_resolve.TTS_ENGINES
        component = table.get(engine)
        if component is None:
            return None
        if requested == "cuda" and engine in self.blocked:
            raise compute.ComputeUnavailableError(
                f"{component} 请求 cuda，本机能力表判不可用：测试原因"
            )
        return device_resolve.DeviceResolution(
            component=component,
            cap=_CAP[component],
            requested=requested or "auto",
            resolved=self.device,
            actual=self.device,
            device=self.device,
            reason="",
        )


class _StubEngine:
    """替身引擎：只记构造参数，绝不加载模型（类属性对齐真引擎的能力声明）。"""

    supports_diarization = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    @staticmethod
    def supports_model(model: str) -> bool:
        return False


class _ExplodingEngine:
    """被构造即失败：用来证明炸点在执行构造之前。"""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("解析失败时不允许构造引擎")


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(device_resolve, "resolve_engine", rec)
    return rec


@pytest.fixture
def asr_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FasterWhisperEngine", "SenseVoiceEngine", "ParaformerEngine"):
        monkeypatch.setattr(runtime, name, _StubEngine, raising=False)
        monkeypatch.setattr(asr_mod, name, _StubEngine, raising=False)


@pytest.fixture
def tts_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indextts2_mod, "IndexTts2Engine", _StubEngine)
    monkeypatch.setattr(cosyvoice_mod, "CosyVoiceEngine", _StubEngine)
    monkeypatch.setattr(kokoro_mod, "KokoroEngine", _StubEngine)


def _settings(**overrides: str) -> config.Settings:
    return {**config.DEFAULTS, **overrides}


def _asr_spec(engine: str) -> registry.ModelSpec:
    return next(s for s in registry.builtin_specs() if s.kind == "asr" and s.engine == engine)


def test_asr_engines_receive_resolved_device_not_the_intent(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    """设置写 auto、解析给 cpu：引擎必须收到 cpu——收到 auto 等于解析没接上。"""
    resolver.device = "cpu"
    for engine in _LOCAL_ASR:
        built = runtime._build_transcriber(
            _settings(**{"asr.engine": engine, "asr.device": "auto"}),
            tmp_path,
            tmp_path / "data",
        )
        assert built.kwargs["device"] == "cpu"
    call = resolver.calls[-1]
    assert (call["kind"], call["engine"], call["requested"]) == ("asr", _LOCAL_ASR[-1], "auto")
    assert call["data_dir"] == tmp_path / "data"


def test_asr_cuda_blocked_fails_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("FasterWhisperEngine", "SenseVoiceEngine", "ParaformerEngine"):
        monkeypatch.setattr(runtime, name, _ExplodingEngine, raising=False)
    resolver.blocked = set(_LOCAL_ASR)
    for engine in _LOCAL_ASR:
        with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
            runtime._build_transcriber(
                _settings(**{"asr.engine": engine, "asr.device": "cuda"}),
                tmp_path,
                tmp_path / "data",
            )


def test_asr_without_data_dir_passes_intent_through(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    """没有解析入口 = 透传（`resolve_data_dir()` 会 mkdir，不许藏在引擎构造里）。"""
    built = runtime._build_transcriber(
        _settings(**{"asr.engine": "sensevoice", "asr.device": "cuda"}), tmp_path
    )
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls == []


def test_asr_cloud_engine_is_never_resolved(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "DashscopeCloudAsrEngine", _StubEngine, raising=False)
    runtime._build_transcriber(
        _settings(**{"asr.engine": "dashscope_cloud", "asr.device": "cuda"}),
        tmp_path,
        tmp_path / "data",
    )
    assert resolver.calls == []


def test_tts_local_engines_receive_resolved_device(
    tmp_path: Path, resolver: _Recorder, tts_stubs: None
) -> None:
    resolver.device = "cpu"
    for engine in _LOCAL_TTS:
        built = factory.create(engine, tmp_path, device="auto", data_dir=tmp_path / "data")
        assert built.kwargs["device"] == "cpu"
        assert resolver.calls[-1]["engine"] == engine


def test_tts_cuda_blocked_fails_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indextts2_mod, "IndexTts2Engine", _ExplodingEngine)
    resolver.blocked = {"indextts2"}
    with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
        factory.create("indextts2", tmp_path, device="cuda", data_dir=tmp_path / "data")


def test_kokoro_has_no_cap_so_device_passes_through(
    tmp_path: Path, resolver: _Recorder, tts_stubs: None
) -> None:
    """kokoro 不在解析表：猜一个 cap 等于替它宣布可用性，透传才是诚实的。"""
    built = factory.create("kokoro", tmp_path, device="cuda", data_dir=tmp_path / "data")
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls[-1]["engine"] == "kokoro"


def test_edge_is_never_resolved(tmp_path: Path, resolver: _Recorder) -> None:
    factory.create("edge", tmp_path, device="cuda", data_dir=tmp_path / "data")
    assert resolver.calls == []


def test_engine_pool_forwards_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """narration 池的显式引擎在构造时就得带上解析入口——解析本身在工厂里发生。"""
    monkeypatch.setattr(synthesis_mod, "create_tts", _StubEngine)
    pool = synthesis_mod._EnginePool(
        "indextts2", tmp_path, None, device="auto", data_dir=tmp_path / "data"
    )
    built = pool._instances["indextts2"]
    assert built is not None
    assert built.kwargs["data_dir"] == tmp_path / "data"


def test_selftest_build_asr_resolves_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.infra.model_manager import selftest

    monkeypatch.setattr(asr_mod, "SenseVoiceEngine", _ExplodingEngine)
    resolver.blocked = {"sensevoice"}
    with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
        selftest._build_asr(
            tmp_path, _asr_spec("sensevoice"), "cuda", "auto", data_dir=tmp_path / "data"
        )


def test_selftest_build_asr_without_data_dir_passes_through(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    from dramaclip.infra.model_manager import selftest

    built = selftest._build_asr(tmp_path, _asr_spec("sensevoice"), "cuda", "auto")
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls == []
