"""编码器混音分支：只要段上带了旁白音频就必须混进成片。

回归动机（两轴审查 B2）：`full_narration` 每段都是 `ducked`，而取音侧只认
`narration`，导致这个分支对 ducked 从未触发过。本文件锁死编码器的两条腿：
带音即混（不分 narration/ducked）、无音则回退单路原声。
"""

from __future__ import annotations

import random

from dramaclip.engines.exporter import encoder


def _args(audio: str, tts: str | None) -> list[str]:
    return encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0.0, end=3.0, audio=audio, mask=False,
        tts_audio=tts, rng=random.Random(0),
    )


def test_ducked_segment_mixes_tts() -> None:
    args = _args("ducked", "tts.mp3")
    assert "-filter_complex" in args, "ducked 段未走混音分支，旁白会整条丢失"
    assert "tts.mp3" in args
    assert "volume=0.12" in " ".join(args), "全片解说底噪压到 12%"


def test_narration_segment_mixes_tts() -> None:
    args = _args("narration", "tts.mp3")
    assert "-filter_complex" in args
    assert "volume=0.2" in " ".join(args), "旁白段原声压低 20%"


def test_original_segment_keeps_source_audio() -> None:
    args = _args("original", None)
    assert "-filter_complex" not in args
    assert "-vf" in args


def test_narration_without_audio_falls_back_to_plain() -> None:
    assert "-filter_complex" not in _args("narration", None), "无音频时不应声明第二路输入"
