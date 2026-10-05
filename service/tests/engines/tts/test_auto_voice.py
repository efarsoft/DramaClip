"""auto_voice：从剧集自动提取主角参考音色的选段与抽取。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.tts import auto_voice


def _seg(start: float, end: float, speaker: str) -> dict[str, Any]:
    text = "台词" * max(1, int(end - start))
    return {"start": start, "end": end, "text": text, "speaker": speaker}


def test_lead_speaker_is_the_one_with_most_lines() -> None:
    segs = [_seg(0, 2.0, "A"), _seg(2, 4.0, "B"), _seg(4, 9.0, "A")]
    assert auto_voice._lead_speaker(segs) == "A"


def test_lead_speaker_none_without_labels() -> None:
    segs = [{"start": 0, "end": 2, "text": "旧数据无标签"}]
    assert auto_voice._lead_speaker(segs) is None


def test_pick_span_prefers_closest_to_target() -> None:
    segs = [_seg(0, 5.0, "A"), _seg(10, 17.5, "A"), _seg(20, 25.0, "A")]
    span = auto_voice._pick_span(segs, "A")
    assert span == pytest.approx((10.0, 17.5))


def test_pick_span_trims_long_segment() -> None:
    segs = [_seg(0, 20.0, "A")]
    span = auto_voice._pick_span(segs, "A")
    assert span is not None
    start, end = span
    assert end - start == pytest.approx(auto_voice._TARGET_S)


def test_pick_span_none_when_all_too_short() -> None:
    segs = [_seg(0, 2.0, "A"), _seg(3, 5.0, "A")]
    assert auto_voice._pick_span(segs, "A") is None


def test_segments_of_tolerates_garbage() -> None:
    assert auto_voice._segments_of({"asr_segments": "not-json"}) == []
    assert auto_voice._segments_of({}) == []
