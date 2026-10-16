"""GPU 探测解析与缓存状态机；transcriber CUDA 回退。"""

from __future__ import annotations

import sys
import types
from collections.abc import Generator
from pathlib import Path
from typing import Any

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

    def __init__(
        self, size: str, device: str = "cpu", download_root: str | None = None,
        compute_type: str = "float32",
    ) -> None:
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

    def __init__(
        self, _size: str, device: str = "cpu", download_root: str | None = None,
        compute_type: str = "float32",
    ) -> None:
        self.device = device
        _FakeLazyWhisper.created.append(device)

    def transcribe(  # type: ignore[no-untyped-def]
        self, _wav: object, language: str = "zh", vad_filter: bool = False,
        *, word_timestamps: bool = False, hotwords: str | None = None,
    ):
        if self.device == "cuda":
            def _boom() -> Generator[None, None, None]:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield  # pragma: no cover

            return _boom(), None
        seg = types.SimpleNamespace(start=0.0, end=1.0, text=" 你好 ", words=[])
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


class _ComputeRecorder:
    """只记录每次构建收到的 (device, compute_type)——验 int8 不硬塞 CUDA 的映射纪律。"""

    created: list[tuple[str, str]] = []

    def __init__(
        self, _size: str, device: str = "cpu", download_root: str | None = None,
        compute_type: str = "float32",
    ) -> None:
        _ComputeRecorder.created.append((device, compute_type))
        self.device = device


def test_default_auto_goes_to_every_device_untouched(monkeypatch) -> None:
    """默认档 auto 原样直达各设备：精度由 ctranslate2 按实际解析到的卡挑。

    写死的 CPU 档（int8）硬塞 CUDA 会被拒→注定回退 CPU，GPU 在场却永远用不上；
    auto 在 CPU 上也挑 int8——CPU 用户零回退。
    """
    fake = types.SimpleNamespace(WhisperModel=_ComputeRecorder)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _ComputeRecorder.created.clear()
    FasterWhisperEngine("base", device="cuda")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("cuda", "auto")
    FasterWhisperEngine("base", device="auto")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("auto", "auto")
    FasterWhisperEngine("base", device="cpu")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("cpu", "auto")


def test_legacy_int8_is_never_sent_to_a_gpu(monkeypatch) -> None:
    """存量兜底：老设置库落盘的 int8（或调用方显式传入）不许发往 GPU。

    设备非 cpu 时映射成 auto；CPU 路径保留 int8（本来就是它的档）。
    """
    fake = types.SimpleNamespace(WhisperModel=_ComputeRecorder)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _ComputeRecorder.created.clear()
    FasterWhisperEngine("base", device="cuda", compute_type="int8")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("cuda", "auto")
    FasterWhisperEngine("base", device="auto", compute_type="int8")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("auto", "auto")
    FasterWhisperEngine("base", device="cpu", compute_type="int8")._ensure_model()
    assert _ComputeRecorder.created[-1] == ("cpu", "int8")


def test_explicit_compute_type_is_respected_on_gpu(monkeypatch) -> None:
    """业主显式选的档位（float16/int8_float16/auto）原样透传：映射只动 int8。"""
    fake = types.SimpleNamespace(WhisperModel=_ComputeRecorder)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _ComputeRecorder.created.clear()
    FasterWhisperEngine("base", device="cuda", compute_type="float16")._ensure_model()
    assert _ComputeRecorder.created == [("cuda", "float16")]


# ── 设备分档与能力结论（device_profile 纯函数） ──

from dramaclip.infra import device_profile  # noqa: E402


def test_tier_of_vram_thresholds() -> None:
    assert device_profile.tier_of("none", 8192) == "none"
    assert device_profile.tier_of("nvidia", 4096) == "low"
    assert device_profile.tier_of("nvidia", 8192) == "entry"
    assert device_profile.tier_of("nvidia", 16384) == "mid"
    assert device_profile.tier_of("nvidia", 24576) == "high"
    assert device_profile.tier_of("nvidia", 0) == "low"


def test_profile_caps_and_runtime_layering() -> None:
    snap = {
        "vendor": "nvidia",
        "name": "Quadro M4000",
        "memory_total_mb": 8192,
        "max_cuda_version": "13.0",
    }
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["tier"] == "entry"
    assert prof["caps"]["faster_whisper_gpu"]["ok"] is True
    assert prof["caps"]["faster_whisper_gpu"]["ready"] is False  # 运行库未装
    ready = device_profile.profile(snap, cuda_runtime_installed=True)
    assert ready["caps"]["faster_whisper_gpu"]["ready"] is True
    # 8GB 显存够 4B 档、不够 8B 档
    assert prof["caps"]["local_visual_4b"]["ok"] is True
    assert prof["caps"]["local_visual_8b"]["ok"] is False
    # 运行时组合层（tts-venv 安装态）不在 profile 硬件判定里：一律 ready=False
    assert prof["caps"]["vocal_separation_gpu"]["ready"] is False
    assert "MDX-Net" in prof["caps"]["vocal_separation_gpu"]["hint"]


def test_profile_driver_guidance_when_cuda_too_old() -> None:
    snap = {
        "vendor": "nvidia",
        "name": "Quadro K2200",
        "memory_total_mb": 4096,
        "max_cuda_version": "11.0",
    }
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["driver_guidance"]["needed"] is True
    assert prof["driver_guidance"]["url"].startswith("https://")
    assert prof["caps"]["faster_whisper_gpu"]["ok"] is False
    assert prof["tier"] == "low"


def test_profile_none_vendor_recommends_cloud() -> None:
    prof = device_profile.profile(
        {"vendor": "none", "name": "", "memory_total_mb": 0, "max_cuda_version": ""},
        cuda_runtime_installed=False,
    )
    assert prof["tier"] == "none"
    assert "云端" in prof["recommendation"]
    assert prof["driver_guidance"]["needed"] is False


def test_torch_variant_marker_roundtrip(tmp_path: Path) -> None:
    from dramaclip.infra.model_manager import tts_runtime

    data = tmp_path / "data"
    # 未安装：unknown（不抛）
    assert tts_runtime.torch_variant(data) == "unknown"
    # 坏标记：unknown
    marker = tts_runtime._variant_marker(data)
    marker.parent.mkdir(parents=True)
    marker.write_text("bogus", encoding="utf-8")
    assert tts_runtime.torch_variant(data) == "unknown"
    # 安装完成写入的合法标记：原样读回
    marker.write_text("cuda", encoding="utf-8")
    assert tts_runtime.torch_variant(data) == "cuda"
    # status 的透传只在 venv 真实存在时发生（无 python.exe = 未安装分支，恒 unknown）
    py = tts_runtime.venv_dir(data) / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    assert tts_runtime.status(data)["torch_variant"] == "unknown"  # 探针跑不动假解释器 → 未装完


def test_gpu_variant_three_tiers(monkeypatch) -> None:
    """算力三档：≥7.0 cu128 / 5.0-6.9 cu126（老卡兼容）/ <5.0 或无卡 CPU。"""
    from dramaclip.infra.model_manager import tts_runtime

    monkeypatch.setattr(tts_runtime.shutil, "which", lambda _n: r"C:\fake\nvidia-smi.exe")

    class _Probe:
        def __init__(self, out: str) -> None:
            self.stdout = out
            self.returncode = 0

    cases = {
        "7.5": "cuda",
        "8.9": "cuda",
        "5.2": "cuda126",
        "6.1": "cuda126",
        "4.5": "cpu",
        "": "cuda",  # 探测失败按有卡处理（保守装 CUDA 轮，合成探针诚实回退）
    }
    for cap, expected in cases.items():
        monkeypatch.setattr(
            tts_runtime.subprocess,
            "run",
            lambda *a, _c=cap, **k: _Probe(f"{_c}\n"),
        )
        assert tts_runtime._gpu_variant() == expected, f"compute_cap={cap!r}"


def test_gpu_variant_cpu_when_no_smi(monkeypatch) -> None:
    from dramaclip.infra.model_manager import tts_runtime

    monkeypatch.setattr(tts_runtime.shutil, "which", lambda _n: None)
    assert tts_runtime._gpu_variant() == "cpu"


def test_install_torch_falls_back_to_mirror(monkeypatch, tmp_path: Path) -> None:
    """官方 cu 源失败 → 阿里 flat 镜像重试（--find-links + 清华 index）；cpu 直走清华。"""
    from dramaclip.infra.model_manager import tts_runtime

    calls: list[list[str]] = []
    state = {"fail_first": True}

    def _fake_run(uv: Path, venv: Path, *args: str) -> None:
        calls.append(list(args))
        if state["fail_first"] and "--find-links" not in args:
            raise RuntimeError("SSL 握手失败")

    monkeypatch.setattr(tts_runtime, "_run_uv", _fake_run)
    tts_runtime._install_torch(Path("uv"), venv_dir := tmp_path / "venv", "cuda126")
    assert len(calls) == 2
    joined = " ".join(calls[1])
    assert "--find-links" in joined and "cu126" in joined
    # cpu 变体只走清华单次
    calls.clear()
    state["fail_first"] = False
    tts_runtime._install_torch(Path("uv"), venv_dir, "cpu")
    assert len(calls) == 1 and "--index-url" in calls[0]
    assert tts_runtime._PYPI_MIRROR in calls[0]


# ── funasr 双引擎 device 支持 ──

def test_resolve_torch_device(monkeypatch) -> None:
    from dramaclip.engines.analysis.transcriber import _resolve_torch_device

    class _FakeTorch:
        class cuda:
            is_available = staticmethod(lambda: _avail)

    monkeypatch.setitem(__import__("sys").modules, "torch", _FakeTorch)
    _avail = True
    assert _resolve_torch_device("auto") == "cuda:0"
    _avail = False
    assert _resolve_torch_device("auto") == "cpu"
    # 显式 cuda 是用户明确要求 GPU：探针只管 auto，加载失败由引擎回退兜底
    assert _resolve_torch_device("cuda") == "cuda:0"
    assert _resolve_torch_device("cuda:1") == "cuda:1"  # 显式卡号原样透传
    assert _resolve_torch_device("cpu") == "cpu"


def test_sensevoice_passes_device_to_automodel(monkeypatch, tmp_path: Path) -> None:
    import dramaclip.engines.analysis.transcriber as mod

    captured: dict[str, Any] = {}

    class _FakeAuto:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(mod, "_resolve_torch_device", lambda _d: "cuda:0")
    import types

    fake_mod = types.ModuleType("funasr")
    fake_mod.AutoModel = _FakeAuto  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "funasr", fake_mod)
    engine = mod.SenseVoiceEngine(models_dir=tmp_path, device="cuda")
    engine._ensure_model()
    assert captured["device"] == "cuda:0"


def test_sensevoice_falls_back_to_cpu_on_cuda_failure(monkeypatch, tmp_path: Path) -> None:
    import dramaclip.engines.analysis.transcriber as mod

    devices: list[str] = []

    class _FakeAuto:
        def __init__(self, **kwargs: Any) -> None:
            devices.append(kwargs["device"])
            if kwargs["device"] != "cpu":
                raise RuntimeError("CUDA error: cublas64_12.dll missing")

    monkeypatch.setattr(mod, "_resolve_torch_device", lambda _d: "cuda:0")
    import types

    fake_mod = types.ModuleType("funasr")
    fake_mod.AutoModel = _FakeAuto  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "funasr", fake_mod)
    engine = mod.SenseVoiceEngine(models_dir=tmp_path, device="cuda")
    engine._ensure_model()
    assert devices == ["cuda:0", "cpu"]
