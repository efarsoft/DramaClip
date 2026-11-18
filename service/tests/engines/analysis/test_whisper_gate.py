"""faster_whisper 本地模型预检：缺失给行动性引导，不放行到 huggingface 撞网络。

客户「分析失败」的又一种无细节形态：模型没下载 → WhisperModel 触发
huggingface_hub 联网 → 国内网络下英文连接超时。预检把这一步拦在加载前。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis.transcriber import FasterWhisperEngine


def test_missing_model_raises_with_engine_center_guidance(tmp_path: Path) -> None:
    engine = FasterWhisperEngine("base", device="cpu", models_dir=tmp_path)
    with pytest.raises(ValueError, match="引擎中心"):
        engine._ensure_model()


def test_present_hf_layout_passes_the_gate(tmp_path: Path) -> None:
    snapshot = tmp_path / "models--Systran--faster-whisper-base" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"weights")
    engine = FasterWhisperEngine("base", device="cpu", models_dir=tmp_path)
    engine._require_local_model()  # 不抛即通过


def test_no_models_dir_keeps_legacy_behavior() -> None:
    """models_dir=None（旧调用方/dev 直构）不做预检——沿用历史放行语义。"""
    engine = FasterWhisperEngine("base", device="cpu", models_dir=None)
    engine._require_local_model()  # 不抛即通过



def test_missing_asset_error_bypasses_cuda_wrapper(tmp_path: Path) -> None:
    """装测实锤（2026-11-17）：请求 CUDA 时文件缺失（VAD onnx 没进包）曾被套上
    「请求 CUDA，推理失败」的算力壳——资产缺失必须原样上抛（RuntimeError），
    不是 ComputeUnavailableError：换 CPU 也修不了，错误归因要把用户引向资产修复。"""
    import pytest

    engine = FasterWhisperEngine("base", device="cuda", models_dir=tmp_path)

    def _boom() -> object:
        raise RuntimeError(
            "[ONNXRuntimeError] : 3 : NO_SUCHFILE : Load model from "
            r"C:\...\faster_whisper\assets\silero_vad_v6.onnx failed. File doesn't exist"
        )

    engine._ensure_model = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="NO_SUCHFILE"):
        engine.transcribe(tmp_path / "x.wav")
