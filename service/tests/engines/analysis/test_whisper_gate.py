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
