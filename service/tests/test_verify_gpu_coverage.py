"""验真脚本的纯逻辑：状态纪律、请求判据、错误归类、路径脱敏、组件筛选。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from dramaclip.infra.compute import ComputeUnavailableError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_gpu_coverage.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_gpu_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_gpu_coverage"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_script()


def test_pass_requires_actual_evidence(mod):
    with pytest.raises(ValueError, match="actual"):
        mod.Record(
            component="asr.whisper.cpu",
            requested="cpu",
            runtime="root-venv",
            status="pass",
            actual="unknown",
        )


def test_non_pass_requires_reason(mod):
    with pytest.raises(ValueError, match="reason"):
        mod.Record(
            component="asr.whisper.cuda",
            requested="cuda",
            runtime="root-venv",
            status="unsupported",
            actual="unknown",
        )


def test_record_rejects_unknown_status(mod):
    with pytest.raises(ValueError, match="status"):
        mod.Record(
            component="x", requested="cpu", runtime="r", status="ok", actual="cpu",
            reason="",
        )


def test_parse_require(mod):
    assert mod.parse_require(["asr.whisper.cuda=pass"]) == [("asr.whisper.cuda", "pass")]
    with pytest.raises(ValueError):
        mod.parse_require(["asr.whisper.cuda"])
    with pytest.raises(ValueError):
        mod.parse_require(["asr.whisper.cuda=green"])


def test_unsupported_is_not_a_pass(mod):
    records = [
        mod.Record(
            component="asr.whisper.cuda", requested="cuda", runtime="root-venv",
            status="unsupported", actual="unknown", reason="no kernel image",
        ),
        mod.Record(
            component="asr.whisper.cpu", requested="cpu", runtime="root-venv",
            status="pass", actual="cpu",
        ),
    ]
    unmet = mod.unmet_requirements(records, [("asr.whisper.cuda", "pass")])
    assert len(unmet) == 1
    assert "unsupported" in unmet[0]
    assert mod.unmet_requirements(records, [("asr.whisper.cpu", "pass")]) == []
    assert len(mod.unmet_requirements(records, [("asr.funasr.cuda", "pass")])) == 1


def test_judge_actual(mod):
    assert mod.judge_actual("asr.whisper", "cuda", "cuda") == ""
    assert mod.judge_actual("asr.whisper", "cpu", "cpu") == ""
    assert mod.judge_actual("asr.whisper", "cpu", "cuda")
    assert mod.judge_actual("asr.whisper", "cuda", "cpu")
    assert mod.judge_actual("asr.whisper", "auto", "unknown")
    assert mod.judge_actual("video.encode", "cpu", "libx264") == ""
    assert mod.judge_actual("video.encode", "cuda", "h264_nvenc") == ""
    assert mod.judge_actual("video.encode", "cuda", "libx264")
    assert mod.judge_actual("video.ai_label", "cpu", "libx264") == ""


def test_classify_error(mod):
    assert mod.classify_error(ComputeUnavailableError("请求 cuda 失败"), "cuda") == "unsupported"
    assert mod.classify_error(
        RuntimeError("请求 CUDA 但探针失败：torch.cuda.is_available = False"), "cuda"
    ) == "unsupported"
    assert mod.classify_error(
        RuntimeError("CUDA failed with error no kernel image is available"), "cuda"
    ) == "unsupported"
    assert mod.classify_error(
        RuntimeError("Torch not compiled with CUDA enabled"), "cuda"
    ) == "unsupported"
    assert mod.classify_error(ValueError("bad model dir"), "cuda") == "fail"
    assert mod.classify_error(ValueError("no kernel image"), "cpu") == "fail"


def test_sanitize_paths(mod):
    roots = {r"D:\PersonProjects\DramaClip\data": "<data>", r"C:\Users\someone": "<home>"}
    text = r"加载 D:\PersonProjects\DramaClip\data\models\a.bin 失败；home=C:\Users\someone"
    cleaned = mod.sanitize(text, roots)
    assert "<data>" in cleaned
    assert "<home>" in cleaned
    assert "PersonProjects" not in cleaned
    assert "someone" not in cleaned
    assert len(mod.sanitize("x" * 2000, {})) <= mod.REASON_MAX_CHARS


def test_component_selection(mod):
    assert mod.selected("asr.whisper.cuda", [])
    assert mod.selected("asr.whisper.cuda", ["asr"])
    assert mod.selected("asr.whisper.cuda", ["asr.whisper"])
    assert mod.selected("asr.whisper.cuda", ["asr.whisper.cuda"])
    assert not mod.selected("asr.whisper.cuda", ["tts"])
    assert mod.selected("tts.kokoro.cpu", ["tts.kokoro.*"])
    assert not mod.selected("tts.kokoro.cpu", ["tts.indextts2.*"])


def test_hw_encoders_include_amf(mod) -> None:
    assert "h264_amf" in mod._HW_ENCODERS


def test_judge_actual_accepts_amf_for_cuda(mod) -> None:
    """video.* 的 requested=cuda 语义是「请求硬件编码」：actual 说出到底是谁。"""
    assert mod.judge_actual("video.encode", "cuda", "h264_amf") == ""
    assert mod.judge_actual("video.encode", "cuda", "h264_nvenc") == ""
    assert mod.judge_actual("video.encode", "cuda", "h264_qsv") == ""
    assert mod.judge_actual("video.encode", "cuda", "libx264")


def test_select_hw_encoder_returns_first_working_candidate(mod, monkeypatch) -> None:
    from dramaclip.engines.exporter import encoder

    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"]
    )

    def fake_run_cut(args, cancel=None, **kwargs):
        if "h264_nvenc" in args:
            raise RuntimeError("NVENC: 驱动残缺")

    monkeypatch.setattr(encoder, "_run_cut", fake_run_cut)
    codec, skipped = mod._select_hw_encoder()
    assert codec == "h264_amf"
    assert "h264_nvenc" in skipped, "被跳过的候选要留原因，不然 AMD 主机看不出 NVENC 为什么不算数"


def test_select_hw_encoder_all_fail_lists_every_candidate(mod, monkeypatch) -> None:
    from dramaclip.engines.exporter import encoder

    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"]
    )
    seen: list[str] = []

    def fake_run_cut(args, cancel=None, **kwargs):
        seen.append(args[args.index("-c:v") + 1])
        raise RuntimeError("没有硬编")

    monkeypatch.setattr(encoder, "_run_cut", fake_run_cut)
    with pytest.raises(mod.Unsupported, match="h264_qsv") as caught:
        mod._select_hw_encoder()
    assert seen == ["h264_nvenc", "h264_amf", "h264_qsv"], "unsupported 必须逐项试过"
    assert "h264_nvenc" in str(caught.value) and "没有硬编" in str(caught.value)
