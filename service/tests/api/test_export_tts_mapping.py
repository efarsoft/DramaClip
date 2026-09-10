"""段→旁白映射必须按 `segment.narration_id`，不按位置序号。

回归动机（两轴审查 B3）：`api/export` 原先「数 narration 段」重建映射 ——
`ducked` 段一个也拿不到音（full_narration 出厂零解说），而 TTS 失败被
`kept_texts` 过滤掉后，剩余旁白与位置序号整体错位一格。
"""

from __future__ import annotations

from dramaclip.api.export import tts_audio_by_segment
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment


def _plan(segments: list[TimelineSegment], texts: list[NarrationText]) -> PlanData:
    return PlanData(mode="cross_narration", timeline=segments, narration_texts=texts)


def _texts(ids: list[str]) -> list[NarrationText]:
    return [NarrationText(id=nid, text=f"文案-{nid}", audio_path=f"/a/{nid}.mp3") for nid in ids]


def test_alternating_timeline_maps_to_owning_text() -> None:
    """cross_narration 的原声/旁白交替：旁白归第 1、3 段，绝不是第 0、1 段。"""
    plan = _plan(
        [
            TimelineSegment(episode_id="e", start=0, end=1, audio="original"),
            TimelineSegment(episode_id="e", start=1, end=2, audio="narration", narration_id="n0"),
            TimelineSegment(episode_id="e", start=2, end=3, audio="original"),
            TimelineSegment(episode_id="e", start=3, end=4, audio="narration", narration_id="n1"),
        ],
        _texts(["n0", "n1"]),
    )
    assert tts_audio_by_segment(plan) == {1: "/a/n0.mp3", 3: "/a/n1.mp3"}


def test_ducked_timeline_maps_every_segment() -> None:
    """full_narration 形态：每段都是 ducked，四段必须四条音，一段都不能少。"""
    plan = _plan(
        [
            TimelineSegment(episode_id="e", start=float(i), end=float(i) + 1, audio="ducked",
                            narration_id=f"full-{i + 1}")
            for i in range(4)
        ],
        _texts(["full-1", "full-2", "full-3", "full-4"]),
    )
    mapping = tts_audio_by_segment(plan)
    assert mapping == {
        0: "/a/full-1.mp3", 1: "/a/full-2.mp3", 2: "/a/full-3.mp3", 3: "/a/full-4.mp3"
    }


def test_cta_at_third_index_keeps_its_own_audio() -> None:
    """ultra_short_hook：钩子在 0、CTA 在 2，中间夹原声段——CTA 音不得被丢。"""
    plan = _plan(
        [
            TimelineSegment(
                episode_id="e", start=0, end=4, audio="narration", narration_id="hook-1"
            ),
            TimelineSegment(episode_id="e", start=4, end=12, audio="original"),
            TimelineSegment(
                episode_id="e", start=12, end=16, audio="narration", narration_id="cta-1"
            ),
        ],
        _texts(["hook-1", "cta-1"]),
    )
    assert tts_audio_by_segment(plan) == {0: "/a/hook-1.mp3", 2: "/a/cta-1.mp3"}


def test_missing_id_is_not_silently_mapped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration")],
        _texts(["n0"]),
    )
    assert tts_audio_by_segment(plan) == {}  # 无 id 即无映射，绝不按位置猜


def test_dangling_id_is_dropped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration", narration_id="ghost")],
        _texts(["n0"]),
    )
    assert tts_audio_by_segment(plan) == {}


def test_unsynthesized_text_is_dropped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration", narration_id="n0")],
        [NarrationText(id="n0", text="甲", audio_path=None)],
    )
    assert tts_audio_by_segment(plan) == {}


def test_original_segment_with_stale_id_is_mapped_by_id_only() -> None:
    """映射只认 id：音频角色不参与推断（回退段由回填层负责清 id，见 test_ducked_narration）。"""
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="original", narration_id="n0")],
        _texts(["n0"]),
    )
    assert tts_audio_by_segment(plan) == {0: "/a/n0.mp3"}
