"""TTS 回填不许破坏时间轴的单调性（业主立案③「卡顿后跳场景」真根因）。

编排期写下的段长只是 `estimate_duration` 的估计值，配音回填把 end 改成
`start + 实测音频时长`。实测一旦超过估计，后一段的源素材区间就被前一段盖住：
成片演到源第 6 秒又倒回第 1 秒，把同一段画面重播一遍——观感正是「卡一下然后跳场景」。
编排层（`build_from_script_episodes`）本来就按集用 `start = max(candidate, cursor)`
保证互不重叠，回填这一步必须守住同一条不变量。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import pipeline, scriptwriter
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.narration.pipeline import build_from_script_episodes


class _StubTts:
    """只落一个空文件；实测时长由 audio_duration_s 的桩给出，不碰网络也不碰真音频。"""

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


_LONG_SOURCE_S = 3600.0


def _voice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan: PlanData,
    durations: dict[str, float],
    source_durations: dict[str, float] | None = None,
) -> PlanData:
    """按槽位给出实测时长并跑真回填：槽位 id 藏在音频文件名主干里（内容寻址前缀）。

    源时长默认给到 3600s——远大于本文件任何一条时间轴，这样「回填守住单调性」的
    用例不会顺带把 #70 的越界守卫也测了一遍：那条守卫有自己专门的判红用例。
    """
    def probe(path: Path) -> float:
        return durations[str(Path(path).stem.split("-")[0])]

    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)
    if source_durations is None:
        source_durations = {
            str(segment.episode_id): _LONG_SOURCE_S for segment in plan.timeline
        }
    return pipeline.synthesize_narration_texts(
        plan, {"tts.engine": "edge"}, tmp_path, source_durations=source_durations
    )


def _plan(*segments: tuple[str, float, float, str]) -> PlanData:
    """(集, 起, 止, 角色) 序列 → 方案；旁白/压底段的槽位按出现顺序编号 n0/n1…。"""
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    order = 0
    for episode_id, start, end, audio in segments:
        slot: str | None = None
        if audio != "original":
            slot = f"n{order}"
            texts.append(NarrationText(id=slot, text=f"旁白{order}"))
            order += 1
        timeline.append(
            TimelineSegment(
                episode_id=episode_id, start=start, end=end, audio=audio,  # type: ignore[arg-type]
                narration_id=slot,
            )
        )
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)


def _windows(plan: PlanData) -> list[tuple[str, float, float]]:
    return [(segment.episode_id, segment.start, segment.end) for segment in plan.timeline]


def _assert_source_never_runs_backwards(plan: PlanData) -> None:
    """同集的源时间只许往前走：倒退就意味着成片里会出现重播/倒带。"""
    cursor: dict[str, float] = {}
    for segment in plan.timeline:
        limit = cursor.get(segment.episode_id, 0.0)
        assert segment.start >= limit - 1e-6, (
            f"{segment.episode_id}@{segment.start} 倒回上一段结尾 {limit} 之前 → 画面重播"
        )
        cursor[segment.episode_id] = max(limit, segment.end)


def test_overrun_narration_does_not_swallow_the_next_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测 6s 的旁白装进 1s 的计划窗口：后一段必须往后挪，不能叠在前面那段上。"""
    plan = _plan(("ep1", 0.0, 1.0, "ducked"), ("ep1", 1.0, 5.5, "ducked"))
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 6.0, "n1": 6.0})
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end) for s in result.timeline] == [(0.0, 6.0), (6.0, 12.0)]
    assert all(s.end - s.start == 6.0 for s in result.timeline), "段长仍等于旁白实测时长"


def test_original_window_after_an_overrun_is_shifted_not_left_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """cross/intro 形状：旁白顶穿预算后，紧跟的原声段若留在原地就是二次倒带。"""
    plan = _plan(("ep1", 0.0, 1.0, "narration"), ("ep1", 1.0, 5.0, "original"))
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 6.0})
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end, s.audio) for s in result.timeline] == [
        (0.0, 6.0, "narration"),
        (6.0, 10.0, "original"),
    ], "原声段整体平移，自身长度不许被压掉"


def test_shorter_narration_keeps_the_planned_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测短于计划：就地收口即可，无重叠可修，不该把段尾拖到别处。"""
    plan = _plan(("ep1", 0.0, 8.0, "ducked"), ("ep1", 30.0, 38.0, "ducked"))
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 6.0, "n1": 6.0})
    assert [(s.start, s.end) for s in result.timeline] == [(0.0, 6.0), (30.0, 36.0)]


def test_a_wide_original_window_is_a_barrier_for_the_next_narration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """原声段自己也占源素材时间：只让旁白推进游标，后面那条旁白仍会叠上去。"""
    plan = _plan(
        ("ep1", 0.0, 1.0, "ducked"),
        ("ep1", 1.0, 10.0, "original"),
        ("ep1", 2.0, 3.0, "ducked"),
    )
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 1.5, "n1": 1.5})
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end) for s in result.timeline] == [(0.0, 1.5), (1.5, 10.5), (10.5, 12.0)]


def test_each_episode_advances_its_own_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """跨集编排：ep-b 的画面起点不能被 ep-a 的旁白顶长。"""
    plan = _plan(
        ("ep-a", 0.0, 1.0, "ducked"),
        ("ep-b", 0.0, 1.0, "ducked"),
        ("ep-a", 1.0, 2.0, "ducked"),
    )
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 6.0, "n1": 6.0, "n2": 6.0})
    _assert_source_never_runs_backwards(result)
    assert _windows(result) == [
        ("ep-a", 0.0, 6.0),
        ("ep-b", 0.0, 6.0),
        ("ep-a", 6.0, 12.0),
    ]


def test_script_plan_stays_renderable_after_voicing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """端到端（编排 → 配音回填）：编排层守住的单调性不能被回填还回去。

    只在编排层做「近邻贴合」是不够的：那一层的输出随后就会被实测时长覆盖。
    """
    script = scriptwriter.Script(
        hook="钩子",
        segments=[
            scriptwriter.ScriptSegment(episode=1, start=0.0, end=1.0, text="第一段"),
            scriptwriter.ScriptSegment(episode=1, start=1.0, end=2.0, text="第二段"),
        ],
        cta="点我看结局",
    )
    episode_map = {1: ("ep-a", [AsrSegment(start=0.0, end=20.0, text="台词")])}
    plan = build_from_script_episodes(episode_map, {1: 100.0}, script, StrategySpec())
    voiced = _voice(
        monkeypatch,
        tmp_path,
        plan,
        {segment.narration_id or "": 9.0 for segment in plan.timeline},
    )
    _assert_source_never_runs_backwards(voiced)
    assert voiced.timeline[-1].start >= voiced.timeline[-2].end


def test_backfill_past_the_source_end_is_rejected_not_truncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """回填把段尾推出源片末尾、且往前挪就会和上一段重叠：这条方案必须失败。

    真机实测（bundled ffmpeg 8.1.1，源 6.mp4=76.86s、9s 干音）：窗口 70.86→79.86
    退码 **0**，产物视频 6.07s / 音频 6.03s——9 秒旁白被从中间掐掉；窗口
    76.86→82.86（起点即 EOF）退码仍 0，产物 262 字节、无流。渲染层既不会报错也不
    会警告，所以唯一的拦截点在这里（业主裁决：改所见所闻的一律失败，不截断）。
    """
    plan = _plan(("ep1", 186.0, 192.0, "ducked"), ("ep1", 192.0, 197.0, "ducked"))
    with pytest.raises(
        RuntimeError,
        match=r"越过源集末尾.*197\.20.*192\.20.*超出 5\.00.*止于 192\.20s.*重播画面",
    ):
        _voice(
            monkeypatch,
            tmp_path,
            plan,
            {"n0": 6.2, "n1": 5.0},
            {"ep1": 192.2},
        )


def test_a_narration_longer_than_the_whole_episode_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没有上一段可撞时，越界只可能是文案比整集还长：原因要说清，别赖回填。"""
    plan = _plan(("ep1", 0.0, 1.0, "ducked"))
    with pytest.raises(RuntimeError, match=r"越过源集末尾.*比整集素材还长"):
        _voice(monkeypatch, tmp_path, plan, {"n0": 30.0}, {"ep1": 26.0})


def test_an_original_segment_pushed_past_the_source_is_rejected_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """旁白顶穿预算后紧跟的原声段被平移出界，同样不能出片：它没有 narration_id。"""
    plan = _plan(("ep1", 0.0, 1.0, "narration"), ("ep1", 1.0, 20.0, "original"))
    with pytest.raises(RuntimeError, match=r"越过源集末尾.*原声段"):
        _voice(
            monkeypatch,
            tmp_path,
            plan,
            {"n0": 25.0},
            {"ep1": 26.0},
        )


def test_unknown_source_duration_fails_instead_of_skipping_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """源时长缺失/为 0 不许当成「没有越界」：那正是判据静默失效的形状。"""
    plan = _plan(("ep1", 0.0, 1.0, "ducked"))
    for missing in ({}, {"ep1": 0.0}):
        with pytest.raises(RuntimeError, match="没有源集时长"):
            _voice(monkeypatch, tmp_path, plan, {"n0": 1.0}, missing)


def test_the_tail_beat_is_pulled_back_onto_the_material_instead_of_being_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """末尾那条旁白装不进剩余素材时，先往前挪（真机 896cd284 的形状），不是截音。

    库里那条方案的最后一段起点正好等于源长（192.20/192.20），它前面一段在 68.19s
    结束——中间空着 124s，往前挪既不放重画面也不动文案，是唯一不损失所见所闻的解。
    """
    plan = _plan(
        ("ep1", 59.24, 68.19, "narration"),
        ("ep1", 192.2, 197.2, "narration"),
    )
    result = _voice(
        monkeypatch, tmp_path, plan, {"n0": 8.95, "n1": 6.03}, {"ep1": 192.2}
    )
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end) for s in result.timeline] == [
        (59.24, 68.19),
        (186.17, 192.2),
    ], "末段应贴着源末尾起，长度仍等于旁白实测 6.03s"


def test_a_pulled_back_tail_leaves_later_episodes_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """收口只动这一集：别的集的游标不能被末段的平移带偏。"""
    plan = _plan(
        ("ep-a", 190.0, 192.0, "narration"),
        ("ep-b", 5.0, 9.0, "narration"),
    )
    result = _voice(
        monkeypatch,
        tmp_path,
        plan,
        {"n0": 6.0, "n1": 4.0},
        {"ep-a": 192.2, "ep-b": 30.0},
    )
    _assert_source_never_runs_backwards(result)
    assert _windows(result) == [("ep-a", 186.2, 192.2), ("ep-b", 5.0, 9.0)]

