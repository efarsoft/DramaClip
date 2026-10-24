"""配乐生成请求构建（generator）的纯函数契约。"""

from __future__ import annotations

from dramaclip.engines.bgm.selector import target_bpm
from dramaclip.engines.music.generator import (
    DURATION_CHOICES,
    EMOTION_CAPTIONS,
    INSTRUMENTAL_LYRICS,
    build_request,
)

_EMOTIONS = ("default", "anger", "triumph", "suspense", "sadness")


def test_five_emotions_have_presets_with_instrumental_lyrics() -> None:
    assert set(EMOTION_CAPTIONS) == set(_EMOTIONS)
    for emotion in _EMOTIONS:
        request = build_request(emotion, 120)
        assert request.caption == EMOTION_CAPTIONS[emotion]
        assert request.lyrics == INSTRUMENTAL_LYRICS == "[Instrumental]"
        assert "no vocals" in request.caption
        assert request.emotion == emotion


def test_bpm_follows_selector_target() -> None:
    """生成 bpm 与选曲目标同源（selector.target_bpm）：生成曲天然落在选曲档位。"""
    for emotion in _EMOTIONS:
        assert build_request(emotion, 120).bpm == target_bpm(emotion)


def test_caption_override_wins_and_blank_falls_back() -> None:
    override = build_request("suspense", 120, caption_override="雨夜霓虹下的爵士贝斯漫步")
    assert override.caption == "雨夜霓虹下的爵士贝斯漫步"
    blank = build_request("suspense", 120, caption_override="   ")
    assert blank.caption == EMOTION_CAPTIONS["suspense"]


def test_duration_choices_are_the_library_bed_tiers() -> None:
    assert DURATION_CHOICES == (120, 180)
    assert build_request("default", 180).duration_s == 180.0
