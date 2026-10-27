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
from dramaclip.engines.narration import synthesis as synthesis
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

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _StubTts())
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


def test_backfill_past_the_source_end_drops_the_segment_with_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """回填把段尾推出源片末尾、且前伸和收口都救不动：该段弃用留痕、成片继续。

    真机实测（bundled ffmpeg 8.1.1，源 6.mp4=76.86s、9s 干音）：窗口 70.86→79.86
    退码 **0**，产物视频 6.07s / 音频 6.03s——9 秒旁白被从中间掐掉；窗口
    76.86→82.86（起点即 EOF）退码仍 0，产物 262 字节、无流。渲染层既不报错也不
    警告，所以越界窗口绝不能渲染——业主裁决 2026-10-26 升级处置：不再整条方案
    判失败，而是装不下的段弃用留痕（不裁音、不重播），其余照常出片。
    """
    import logging

    plan = _plan(("ep1", 186.0, 192.0, "ducked"), ("ep1", 192.0, 197.0, "ducked"))
    with caplog.at_level(logging.WARNING, logger="dramaclip.engines.narration.synthesis"):
        result = _voice(
            monkeypatch,
            tmp_path,
            plan,
            {"n0": 6.2, "n1": 5.0},
            {"ep1": 192.2},
        )
    assert _windows(result) == [("ep1", 185.8, 192.0)]  # n0 头部扩展保计划尾，n1 弃用
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "实测 5.00s" in joined and "弃用" in joined


def test_narration_overrun_extends_backwards_and_keeps_the_payoff_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测比计划窗口长：起点前伸保住计划尾，后段原声拍原地不动（音画同源）。

    2026-10-06 真机 ultra_short：61 字钩子实测 ~20s，旧逻辑收口把窗口推到集尾、
    把 CTA 顶出源末尾整条判死。新逻辑钩子窗口起点前伸——素材不裁、不重播、
    原声拍对口型的画面一帧不挪（业主裁决「保障素材时长，不裁」）。"""
    plan = _plan(
        ("ep1", 38.13, 68.13, "narration"),
        ("ep1", 68.13, 72.66, "original"),
        ("ep1", 72.66, 87.66, "narration"),
    )
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 40.0, "n1": 8.0}, {"ep1": 90.0})
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end) for s in result.timeline] == [
        (28.13, 68.13),  # 钩子实测 40s > 预算窗 30s：起点前伸，尾锚 68.13 不动
        (68.13, 72.66),  # 原声拍原地（音画同源，动不得）
        (72.66, 80.66),  # CTA 实测 8s < 预算 15s：从计划起点起
    ]


def test_backwards_extension_stops_at_the_previous_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """前伸撞上同集上一段就停：保持计划起点、向后超出计划尾，不叠上一段画面。"""
    plan = _plan(("ep1", 0.0, 10.0, "ducked"), ("ep1", 10.0, 14.0, "ducked"))
    result = _voice(monkeypatch, tmp_path, plan, {"n0": 8.0, "n1": 8.0})
    _assert_source_never_runs_backwards(result)
    assert [(s.start, s.end) for s in result.timeline] == [(0.0, 8.0), (10.0, 18.0)]


def test_a_narration_longer_than_the_whole_episode_is_dropped_with_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """没有空隙可放时弃段留痕、成片继续（业主裁决 2026-10-26「重新选取而非失败」）：
    原因要说清（实测 vs 空隙），别赖回填。"""
    import logging

    plan = _plan(("ep1", 0.0, 1.0, "ducked"))
    with caplog.at_level(logging.WARNING, logger="dramaclip.engines.narration.synthesis"):
        result = _voice(monkeypatch, tmp_path, plan, {"n0": 30.0}, {"ep1": 26.0})
    assert result.timeline == []  # 方案里只有这一段，弃用后时间轴为空
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "实测 30.00s" in joined and "弃用" in joined


def test_rewrite_round_shrinks_overlong_narration_into_its_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """定向重写路径：实测装不下 → 按实测语速算目标字数收短 → 重合成 → 重回排落位。"""
    plan = _plan(("ep1", 20.0, 21.0, "narration"))
    seen: dict[str, float] = {}

    def probe(path: Path) -> float:
        stem = Path(path).stem
        if stem not in seen:  # 首个内容寻址文件=原文案 30s，重写后的新文件=10s
            seen[stem] = 30.0 if not seen else 10.0
        return seen[stem]

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)

    def rewrite(text: str, target_chars: int) -> str | None:
        # 目标字数按本段实测语速推：len("旁白0")=3 / 30s → 26s 空隙 × 0.1 → 8 字下限
        assert target_chars == 8
        return "收短版"

    result = pipeline.synthesize_narration_texts(
        plan,
        {"tts.engine": "edge"},
        tmp_path,
        source_durations={"ep1": 26.0},
        rewrite_for_fit=rewrite,
    )
    # 收短后 10s：头部扩展保计划尾（21s），起点前伸到 11s
    assert _windows(result) == [("ep1", 11.0, 21.0)]
    assert result.narration_texts[0].text == "收短版"


def test_unrewriteable_overflow_drops_after_first_round(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """重写出口给不出新文案：一轮无进展即停（不做满两轮空转），弃段留痕成片继续。"""
    import logging

    plan = _plan(("ep1", 20.0, 21.0, "narration"))

    def probe(path: Path) -> float:
        return 30.0

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)
    calls: list[int] = []

    def rewrite(text: str, target_chars: int) -> str | None:
        calls.append(target_chars)
        return None

    with caplog.at_level(logging.WARNING, logger="dramaclip.engines.narration.synthesis"):
        result = pipeline.synthesize_narration_texts(
            plan,
            {"tts.engine": "edge"},
            tmp_path,
            source_durations={"ep1": 26.0},
            rewrite_for_fit=rewrite,
        )
    assert result.timeline == []
    assert len(calls) == 1
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "实测 30.00s" in joined and "弃用" in joined


def test_head_extension_start_snaps_to_nearest_scene_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """结构层音画同步：头部扩展把起点伸进空闲素材后，吸附回最近的视觉切点。"""
    plan = _plan(("ep1", 20.0, 21.0, "narration"))

    def probe(path: Path) -> float:
        return 10.0

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)
    result = pipeline.synthesize_narration_texts(
        plan,
        {"tts.engine": "edge"},
        tmp_path,
        source_durations={"ep1": 26.0},
        scene_cuts={"ep1": [10.7, 21.0]},
    )
    # 头部扩展落位 11.0-21.0，吸附到 0.3s 外的切点 10.7（10.7+10=20.7 ≤ 计划尾 21）
    assert _windows(result) == [("ep1", 10.7, 20.7)]


def test_rewrite_output_passes_numerals_and_metanarrative_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """收短产出过全链同款两道零容忍出口：数字中文化生效；元叙述命中弃用走弃段。"""
    import logging

    plan = _plan(("ep1", 20.0, 21.0, "narration"))
    seen: dict[str, float] = {}

    def probe(path: Path) -> float:
        stem = Path(path).stem
        if stem not in seen:
            seen[stem] = 30.0 if not seen else 10.0
        return seen[stem]

    monkeypatch.setattr(synthesis, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", probe)

    def rewrite(text: str, target_chars: int) -> str | None:
        return "他拿走了2000斤玄铁锅"

    result = pipeline.synthesize_narration_texts(
        plan,
        {"tts.engine": "edge"},
        tmp_path,
        source_durations={"ep1": 26.0},
        rewrite_for_fit=rewrite,
    )
    assert result.narration_texts[0].text == "他拿走了两千斤玄铁锅"

    # 元叙述命中：重写结果弃用，该段走弃段路径
    def bad_rewrite(text: str, target_chars: int) -> str | None:
        return "画面里他拿走了玄铁锅"

    plan2 = _plan(("ep1", 20.0, 21.0, "narration"))
    seen.clear()
    with caplog.at_level(logging.WARNING, logger="dramaclip.engines.narration.synthesis"):
        result2 = pipeline.synthesize_narration_texts(
            plan2,
            {"tts.engine": "edge"},
            tmp_path,
            source_durations={"ep1": 26.0},
            rewrite_for_fit=bad_rewrite,
        )
    assert result2.timeline == []
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "元叙述" in joined


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
    assert _windows(result) == [("ep-a", 186.0, 192.0), ("ep-b", 5.0, 9.0)]  # 前伸保计划尾


# ---- B 项·片头闪前预告：回填游标豁免 -----------------------------------------
# `build_intro` 把最高冲突镜前置做首帧（预告式开场），片头段对同集后续段是**有意**
# 的源时间倒回；若照常推进游标，正文会被挤到预告之后甚至冲出源集末尾（真机探针
# 实测过这个失败）。豁免判据在 pipeline.synthesize_narration_texts：intro-1 槽位
# 的计划起点晚于其后任一**同集**段 ⇒ 闪前预告 ⇒ 不推进游标。


def _intro_plan(*segments: tuple[str, float, float, str, str | None]) -> PlanData:
    """intro 形状的方案：(集, 起, 止, 角色, 槽位)。文案手动填上（编排只产 brief）。"""
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for episode_id, start, end, audio, slot in segments:
        if slot is not None:
            texts.append(NarrationText(id=slot, text=f"{slot} 的文案"))
        timeline.append(
            TimelineSegment(
                episode_id=episode_id, start=start, end=end, audio=audio,  # type: ignore[arg-type]
                narration_id=slot,
            )
        )
    return PlanData(mode="intro_narration", timeline=timeline, narration_texts=texts)


def test_intro_teaser_head_does_not_push_the_body_past_the_source_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """闪前预告（片头=片尾高潮镜 94-100，正文回 0-6，CTA 取时序末场景尾部 4-6）：
    8s 钩子 TTS 回填后片头收口到 92-100，正文从自己的计划起点 0 起算，不被游标
    顶出源集末尾。修法②之前这里整条方案 RuntimeError（探针实测：正文被顶到
    106 > 源长 100）。窗口形状与真机探针一致。"""
    plan = _intro_plan(
        ("ep1", 94.0, 100.0, "narration", "intro-1"),
        ("ep1", 0.0, 6.0, "original", None),
        ("ep1", 4.0, 6.0, "narration", "cta-1"),
    )
    # 探针键 = 槽位 id 的 "-" 前缀（_content_addressed_audio 的文件名主干形状）
    result = _voice(
        monkeypatch, tmp_path, plan, {"intro": 8.0, "cta": 2.0}, {"ep1": 100.0}
    )
    assert _windows(result) == [
        ("ep1", 92.0, 100.0),  # 钩子 8s 收口贴着源尾
        ("ep1", 0.0, 6.0),     # 正文回时间序起点，未被游标顶走
        ("ep1", 6.0, 8.0),     # CTA 被正文游标推进（豁免只给片头段）
    ]


def test_intro_chronological_head_still_advances_the_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """最高冲突镜本就是时序第一镜（未前置）：片头是普通时序段，游标照常推进——
    立案③的重播保护不受 B 项豁免影响：8s 钩子把 0-6 的窗口拉到 0-8，
    下一段必须从 8 起算，不许盖住被拉长的片头尾。"""
    plan = _intro_plan(
        ("ep1", 0.0, 6.0, "narration", "intro-1"),
        ("ep1", 6.0, 12.0, "original", None),
        ("ep1", 12.0, 14.0, "narration", "cta-1"),
    )
    result = _voice(
        monkeypatch, tmp_path, plan, {"intro": 8.0, "cta": 2.0}, {"ep1": 100.0}
    )
    _assert_source_never_runs_backwards(result)
    assert _windows(result) == [
        ("ep1", 0.0, 8.0),
        ("ep1", 8.0, 14.0),  # 原声段被平移，不被片头拉长后盖住
        ("ep1", 14.0, 16.0),
    ]


def test_intro_teaser_exempt_is_per_episode_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """豁免只看**同集**倒回：片头预告 ep2 高潮，正文与 CTA 都在 ep1——
    ep2 的预告不推进任何游标，ep1 的正文/CTA 照常按 ep1 游标推进。"""
    plan = _intro_plan(
        ("ep2", 90.0, 96.0, "narration", "intro-1"),
        ("ep1", 0.0, 6.0, "original", None),
        ("ep1", 4.0, 6.0, "narration", "cta-1"),
    )
    result = _voice(
        monkeypatch, tmp_path, plan, {"intro": 6.0, "cta": 2.0},
        {"ep1": 100.0, "ep2": 96.0},
    )
    assert _windows(result) == [
        ("ep2", 90.0, 96.0),  # 预告原样（实测=计划长），ep2 游标未被推进
        ("ep1", 0.0, 6.0),    # ep1 正文从计划起点起算
        ("ep1", 6.0, 8.0),    # ep1 CTA 被 ep1 正文游标推进
    ]

