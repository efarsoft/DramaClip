"""engines.bgm.selector：选曲纯函数（众数/severity/bpm 档位/模式门禁/回退链）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.bgm.library import BgmTrack
from dramaclip.engines.bgm.selector import (
    dominant_emotion,
    pick_track,
    select_bgm,
    should_add_bgm,
)
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _plan(mode: str, labels: list[str | None], texts: list[str | None] | None = None) -> PlanData:
    segments = [
        TimelineSegment(
            episode_id="ep1",
            start=float(i * 6),
            end=float((i + 1) * 6),
            emotion_label=label,
            subtitle_text=None if texts is None else texts[i],
        )
        for i, label in enumerate(labels)
    ]
    return PlanData(mode=mode, timeline=segments)


def _track(name: str, emotion: str, bpm: float | None = None) -> BgmTrack:
    return BgmTrack(
        file=Path(f"/bgm/{emotion}/{name}"),
        emotion=emotion,
        duration_s=60.0,
        bpm=bpm,
        license="",
        attribution="",
        source_url="",
    )


# ---------- dominant_emotion ----------


def test_dominant_is_majority() -> None:
    plan = _plan(
        "intro_narration", ["suspense", "suspense", "anger", "default", "default", "suspense"]
    )
    assert dominant_emotion(plan) == "suspense"


def test_dominant_tie_breaks_by_severity() -> None:
    """平局按 severity 序（suspense>anger>triumph>sadness>default）：钩子优先是转化线口径。"""
    assert dominant_emotion(_plan("full_narration", ["anger", "suspense"])) == "suspense"
    assert dominant_emotion(_plan("full_narration", ["triumph", "anger"])) == "anger"
    assert dominant_emotion(_plan("full_narration", ["default", "sadness"])) == "sadness"


def test_dominant_empty_timeline_is_default() -> None:
    assert dominant_emotion(_plan("full_narration", [])) == "default"


def test_dominant_missing_label_falls_back_to_subtitle_text() -> None:
    """标签缺失的段按字幕文本归一（match_emotion 同一函数，两条路径同一个键）。"""
    plan = _plan(
        "intro_narration",
        [None, None, "default"],
        texts=["他到底藏了什么秘密", "没想到幕后是他", "普通的过渡句"],  # 前两段命中悬念词表
    )
    assert dominant_emotion(plan) == "suspense"  # 两段悬念词 > 一段 default


# ---------- should_add_bgm（九模式全表钉死） ----------


def test_should_add_bgm_mode_table() -> None:
    off = {"raw_clip", "dialogue_narration"}
    on = {
        "intro_narration", "cross_narration", "ultra_short_hook", "full_narration",
        "subtitle_flow", "dual_host_chat", "inner_monologue",
    }
    for mode in off:
        assert should_add_bgm(mode) is False, f"{mode} 源声为主，不叠床"
    for mode in on:
        assert should_add_bgm(mode) is True
    assert off | on == {
        "raw_clip", "intro_narration", "cross_narration", "ultra_short_hook",
        "dialogue_narration", "full_narration", "subtitle_flow",
        "dual_host_chat", "inner_monologue",
    }, "九个模式一个不能漏"


# ---------- pick_track ----------


def test_pick_nearest_bpm_to_emotion_target() -> None:
    tracks = [
        _track("slow.wav", "suspense", bpm=70.0),
        _track("near.wav", "suspense", bpm=112.0),  # 目标 110
        _track("fast.wav", "suspense", bpm=150.0),
    ]
    assert pick_track(tracks, "suspense") is tracks[1]


def test_pick_ignores_other_emotions() -> None:
    tracks = [_track("a.wav", "anger", bpm=120.0), _track("b.wav", "suspense", bpm=111.0)]
    assert pick_track(tracks, "suspense") is tracks[1]


def test_pick_falls_back_to_default_emotion_pool() -> None:
    tracks = [_track("a.wav", "default", bpm=90.0), _track("b.wav", "anger", bpm=120.0)]
    assert pick_track(tracks, "suspense") is tracks[0]  # suspense 无曲 → default 池


def test_pick_empty_library_is_none() -> None:
    assert pick_track([], "suspense") is None  # 无曲可用是合法态，不是错


def test_pick_no_bpm_anywhere_takes_first_by_name() -> None:
    """librosa 缺失的机器：全 None 也要确定性出一首（按文件名），不炸不空。"""
    tracks = [_track("b.wav", "anger"), _track("a.wav", "anger")]
    assert pick_track(tracks, "anger") is tracks[1]


def test_pick_measured_beats_unmeasured() -> None:
    """bpm 平局按文件名（确定性）；无 bpm 的沉底（能测就优先用能测的）。"""
    tracks = [_track("a.wav", "triumph", bpm=None), _track("b.wav", "triumph", bpm=99.0)]
    assert pick_track(tracks, "triumph") is tracks[1]
    tied = [_track("z.wav", "triumph", bpm=100.0), _track("a.wav", "triumph", bpm=100.0)]
    assert pick_track(tied, "triumph") is tied[1]  # 距离同 → 文件名序


# ---------- select_bgm（接线层唯一入口） ----------


def test_select_end_to_end() -> None:
    plan = _plan("intro_narration", ["suspense", "suspense", "anger"])
    tracks = [_track("s.wav", "suspense", bpm=110.0), _track("a.wav", "anger", bpm=120.0)]
    assert select_bgm(plan, tracks) is tracks[0]


def test_select_returns_none_for_source_music_modes() -> None:
    for mode in ("raw_clip", "dialogue_narration"):
        plan = _plan(mode, ["suspense", "suspense"])
        assert select_bgm(plan, [_track("s.wav", "suspense", bpm=110.0)]) is None


def test_select_empty_library_is_none_not_error() -> None:
    plan = _plan("full_narration", ["anger", "anger"])
    assert select_bgm(plan, []) is None  # 渲染层收到 None 走现状路径（硬验收）
