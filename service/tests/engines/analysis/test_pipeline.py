"""engines.analysis.pipeline：fake 引擎 + 真实音频提取的编排测试。"""

from __future__ import annotations

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


def test_extract_audio_wav_is_16k_mono(sample_video: Path, tmp_path: Path) -> None:
    import wave

    wav = tmp_path / "audio.wav"
    pipeline.extract_audio(sample_video, wav)
    with wave.open(str(wav), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1
