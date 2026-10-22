"""engines.analysis.pipeline：fake 引擎 + 真实音频提取的编排测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dramaclip.engines.analysis import pipeline
from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, SceneInfo


class FakeTranscriber:
    name = "fake"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        assert wav_path.is_file(), "管线应先完成真实音频提取"
        return [AsrSegment(start=0.5, end=2.0, text="你好世界")]


@pytest.fixture(autouse=True)
def _stub_heavy_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline.scene_detector, "detect_scenes", lambda _video: [SceneInfo(start=0, end=3)]
    )
    monkeypatch.setattr(
        pipeline.audio_analyzer, "analyze_audio", lambda _wav: AudioFeatures(silence_ratio=0.4)
    )


def test_analyze_episode_runs_full_chain(sample_video: Path, tmp_path: Path) -> None:
    reports: list[tuple[float, str]] = []
    result = pipeline.analyze_episode(
        video_path=sample_video,
        work_dir=tmp_path / "work",
        transcriber=FakeTranscriber(),
        language="zh",
        report=lambda percent, message: reports.append((percent, message)),
    )
    assert [seg.text for seg in result.asr_segments] == ["你好世界"]
    assert [(s.start, s.end) for s in result.scenes] == [(0, 3)]
    assert result.audio.silence_ratio == 0.4
    percents = [percent for percent, _ in reports]
    assert percents == sorted(percents), "进度应单调递增"
    assert percents[-1] == 1.0


def test_source_signature_stable_and_sensitive(tmp_path: Path) -> None:
    """签名纯函数：同输入同输出；size/mtime/path 任一变化必变；缺文件返回 None。"""
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x" * 100)
    os.utime(video, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    base = pipeline.source_signature(video)
    assert base is not None
    assert pipeline.source_signature(video) == base, "同输入必须同输出"

    os.utime(video, ns=(1_700_000_001_000_000_000, 1_700_000_001_000_000_000))
    assert pipeline.source_signature(video) != base, "mtime 变必须换签名"

    video.write_bytes(b"x" * 101)
    os.utime(video, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert pipeline.source_signature(video) != base, "size 变必须换签名（mtime 已复原）"

    twin = tmp_path / "b.mp4"
    twin.write_bytes(b"x" * 100)
    os.utime(twin, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert pipeline.source_signature(twin) != base, "路径参与签名"

    assert pipeline.source_signature(tmp_path / "missing.mp4") is None
    assert pipeline.source_signature(video) != pipeline.source_signature(
        video, ocr_channel=False
    ), "OCR 通道可用性参与签名：降级产物在依赖就绪后强制重算"


def test_extract_audio_wav_is_16k_mono(sample_video: Path, tmp_path: Path) -> None:
    import wave

    wav = tmp_path / "audio.wav"
    pipeline.extract_audio(sample_video, wav)
    with wave.open(str(wav), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1


def test_collapse_warning_flags_squeezed_timeline() -> None:
    """46 段挤 0–11.58s（《颠勺》EP1 实锤形态）→ 坍缩警告；分布正常/段数不足不报。"""
    squeezed = [
        AsrSegment(start=k * 0.25, end=k * 0.25 + 0.2, text="词") for k in range(46)
    ]
    warning = pipeline.collapse_warning(squeezed, 2700.0)
    assert warning is not None
    assert "坍缩" in warning and "46" in warning and "2700" in warning
    spread = [
        AsrSegment(start=float(k) * 55.0, end=float(k) * 55.0 + 3.0, text="台词")
        for k in range(46)
    ]
    assert pipeline.collapse_warning(spread, 2700.0) is None, "全片铺开的段不是坍缩"
    assert pipeline.collapse_warning(squeezed[:10], 2700.0) is None, (
        "少量段挤在窄窗是台词稀疏集的正常场景"
    )
    assert pipeline.collapse_warning(squeezed, 0.0) is not None, (
        "时长拿不到时按跨度本身判（15s 窗）"
    )
