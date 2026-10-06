"""A3：段长跟随实际台词时长——金句流/交叉解说/超短三模式共用一个口径。

业主质量线：「听感与画面，需要考虑加一些过渡方案，不要硬切，看着很蛋疼」
「时长服从故事」。固定 8s 段长的病：台词 2s 说完、画面还要空挂 6s 无信息。

每条用例对应一个真实坏法：

- 无台词不收（收了没依据），且计划与固定 8s 时代**逐字节一致**（硬验收）；
- 台词 span + 0.5s 呼吸尾垫收进 [2, 8]，且不超场景边界；
- B9 节拍吸附必须排在收缩**之后**（先吸附再收缩 = 卡点失效）；
- 三处模式同一台词 span 得同一窗长（口径只有一处真相）；
- CTA 卡片段 / 旁白占位段不随台词收缩（它们的长度不归台词管）；
- 收缩不给转化门禁新增缺陷。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.narration.modes_w9 import build_subtitle_flow
from dramaclip.engines.semantic.models import ConflictScore

_STRATEGY = StrategySpec()


def _one_scene(length: float = 12.0) -> list[casting.EpisodeScene]:
    return stamp(
        [(1, "ep1", [ConflictScore(scene_index=0, start=0.0, end=length, score=90)])]
    )


def _material(
    asr: list[AsrSegment], beats: tuple[float, ...] = ()
) -> casting.MaterialByEpisode:
    return {"ep1": casting.EpisodeMaterial(number=1, asr=asr, beats=beats)}


def _line(start: float, end: float, text: str = "你给我滚出去！骗子！") -> AsrSegment:
    return AsrSegment(start=start, end=end, text=text)


# ---- 纯函数：casting.fit_scene_window --------------------------------------

def test_fit_no_dialogue_keeps_the_fixed_window() -> None:
    """无台词不收：保持 min(场景长, 8.0)，与固定 8s 时代同值（收了没依据）。"""
    assert casting.fit_scene_window(12.0, None) == 8.0
    assert casting.fit_scene_window(3.0, None) == 3.0


def test_fit_three_second_line_gets_line_plus_breath() -> None:
    """台词 3s → 段长 3s + 0.5s 呼吸尾垫（尾垫吃掉导出层 jitter 的 ±0.3s 挪动后仍有富余）。"""
    assert casting.fit_scene_window(12.0, (0.5, 3.5)) == 3.5
    assert casting.DIALOGUE_TAIL_PAD_S == 0.5


def test_fit_caps_at_eight() -> None:
    """台词 10s → 仍取 8.0：上限不动（尾垫不得把窗顶穿上限）。"""
    assert casting.fit_scene_window(20.0, (0.0, 10.0)) == 8.0
    assert casting.fit_scene_window(20.0, (0.0, 7.6)) == 8.0  # 7.6+0.5=8.1 → 8.0


def test_fit_floors_at_two() -> None:
    """台词 1s → 取 2.0：下限不动，与 snap_window_end 的 min_len 同口径。"""
    assert casting.fit_scene_window(12.0, (0.0, 1.0)) == 2.0
    assert casting.fit_scene_window(12.0, (0.0, 0.0)) == casting.SCENE_WINDOW_MIN_S


def test_fit_never_exceeds_the_scene() -> None:
    """场景本身短于台词 span → 取 min：窗口不得超出场景边界。"""
    assert casting.fit_scene_window(2.5, (0.0, 3.0)) == 2.5
    assert casting.fit_scene_window(1.5, (0.0, 1.0)) == 1.5  # 场景比下限还短也照实收


# ---- 字幕金句流（modes_w9） -------------------------------------------------

def test_subtitle_flow_window_follows_the_line() -> None:
    plan = build_subtitle_flow(_one_scene(), _material([_line(0.5, 3.5)]), _STRATEGY)
    body = plan.timeline[0]
    assert (body.start, body.end) == (0.0, 3.5), "台词 3s → 段长 3.5s（3s + 尾垫）"
    assert body.subtitle_text == "你给我滚出去！骗子！", "字幕仍是那句最强金句"


def test_subtitle_flow_caps_and_floors() -> None:
    capped = build_subtitle_flow(_one_scene(20.0), _material([_line(0.0, 10.0)]), _STRATEGY)
    assert capped.timeline[0].end == 8.0, "台词 10s → 仍取 8.0 上限"
    floored = build_subtitle_flow(_one_scene(), _material([_line(0.2, 1.2)]), _STRATEGY)
    assert floored.timeline[0].end == 2.0, "台词 1s → 取 2.0 下限"
    short_scene = build_subtitle_flow(_one_scene(2.5), _material([_line(0.0, 2.4)]), _STRATEGY)
    assert short_scene.timeline[0].end == 2.5, "场景边界 > 台词收缩"


def test_subtitle_flow_scene_without_dialogue_keeps_full_window() -> None:
    """有台词的场景收、没台词的场景保持 8s：同一条时间轴上两种形态并存。"""
    scenes = stamp(
        [
            (
                1,
                "ep1",
                [
                    ConflictScore(scene_index=0, start=0.0, end=12.0, score=90),
                    ConflictScore(scene_index=1, start=20.0, end=32.0, score=80),
                ],
            )
        ]
    )
    plan = build_subtitle_flow(scenes, _material([_line(0.5, 3.5)]), _STRATEGY)
    body = plan.timeline[:-1]
    assert [(s.start, s.end) for s in body] == [(0.0, 3.5), (20.0, 28.0)]


def test_subtitle_flow_no_dialogue_is_byte_identical_to_the_fixed_window() -> None:
    """硬验收：dialogue 为空时计划与现状逐字节一致（含 B9 吸附结果）。

    固定 8s 时代的输出：end=8.0；beat 7.9 在容差内 → 吸附为 7.9。两者都必须原样。
    """
    with_beat = build_subtitle_flow(_one_scene(), _material([], (7.9,)), _STRATEGY)
    without_beat = build_subtitle_flow(_one_scene(), _material([]), _STRATEGY)
    assert (with_beat.timeline[0].start, with_beat.timeline[0].end) == (0.0, 7.9)
    assert (without_beat.timeline[0].start, without_beat.timeline[0].end) == (0.0, 8.0)
    assert (with_beat.timeline[-1].start, with_beat.timeline[-1].end) == (9.0, 12.0)


def test_subtitle_flow_snap_happens_after_shrink() -> None:
    """吸附在收缩之后的可执行证据：拍点 3.4 距收缩后的 end 3.5 只有 0.1s（容差内），
    距收缩前的 end 8.0 却有 4.6s（容差外）。先吸附再收缩 → 3.5（卡点失效）；
    先收缩再吸附 → 3.4（落在拍上）。"""
    plan = build_subtitle_flow(
        _one_scene(), _material([_line(0.0, 3.0)], (3.4,)), _STRATEGY
    )
    assert plan.timeline[0].end == 3.4, "end 必须落在拍点上——吸附排在收缩之后"


def test_subtitle_flow_cta_card_is_untouched() -> None:
    """CTA 定长卡不随台词收缩：仍是最后场景尾部 3s。"""
    plan = build_subtitle_flow(_one_scene(), _material([_line(0.5, 3.5)]), _STRATEGY)
    cta = plan.timeline[-1]
    assert (cta.start, cta.end) == (9.0, 12.0)
    assert cta.subtitle_text is not None and "全集" in cta.subtitle_text


# ---- 交叉解说（modes_w5.build_cross） ---------------------------------------

def test_cross_original_window_follows_the_line() -> None:
    plan = build_cross(_one_scene(), _STRATEGY, _material([_line(0.5, 3.5)]))
    originals = [s for s in plan.timeline if s.audio == "original"]
    assert (originals[0].start, originals[0].end) == (0.0, 3.5)
    narrations = [s for s in plan.timeline if s.audio == "narration"]
    assert (narrations[0].start, narrations[0].end) == (0.0, 4.0), (
        "旁白占位段不随台词收缩——它的长度归 TTS 实测回填"
    )


def test_cross_no_dialogue_is_byte_identical() -> None:
    """material 不传 / 缺集键 / asr 为空：三种降级都与现状逐字节一致（8s 满窗）。"""
    baseline = build_cross(_one_scene(), _STRATEGY)
    assert baseline.timeline[0].end == 8.0
    for degraded in (
        build_cross(_one_scene(), _STRATEGY, None),
        build_cross(_one_scene(), _STRATEGY, _material([])),
        build_cross(_one_scene(), _STRATEGY, {"ep9": casting.EpisodeMaterial(number=9, asr=[])}),
    ):
        assert degraded.model_dump_json() == baseline.model_dump_json()


def test_cross_snap_happens_after_shrink() -> None:
    plan = build_cross(_one_scene(), _STRATEGY, _material([_line(0.0, 3.0)], (3.4,)))
    originals = [s for s in plan.timeline if s.audio == "original"]
    assert originals[0].end == 3.4


# ---- 超短悬念版（modes_w5.build_ultra_short） --------------------------------

def test_ultra_short_conflict_window_follows_the_line() -> None:
    plan = build_ultra_short(_one_scene(), _STRATEGY, _material([_line(0.5, 3.5)]))
    hook, conflict, cta = plan.timeline
    assert (conflict.start, conflict.end) == (0.0, 3.5)
    assert (hook.start, hook.end) == (0.0, 4.0), "hook 旁白占位段不收缩"
    assert (cta.start, cta.end) == (3.5, 18.5), "CTA 接在冲突窗后按预算留画面，不受收缩影响"


def test_ultra_short_no_dialogue_is_byte_identical() -> None:
    baseline = build_ultra_short(_one_scene(), _STRATEGY)
    assert baseline.timeline[1].end == 8.0
    assert build_ultra_short(
        _one_scene(), _STRATEGY, _material([])
    ).model_dump_json() == baseline.model_dump_json()


def test_ultra_short_snap_happens_after_shrink() -> None:
    plan = build_ultra_short(_one_scene(), _STRATEGY, _material([_line(0.0, 3.0)], (3.4,)))
    hook, conflict, cta = plan.timeline
    assert conflict.end == 3.4
    assert (hook.start, hook.end) == (0.0, 4.0)
    assert (cta.start, cta.end) == (3.4, 18.4)


# ---- 三模式口径一致 ----------------------------------------------------------

def test_three_modes_share_one_duration_rule() -> None:
    """同一场景 + 同一句台词：三个模式的原声窗长必须逐一相等（口径只有一处真相）。"""
    asr = [_line(0.5, 3.5)]
    flow = build_subtitle_flow(_one_scene(), _material(asr), _STRATEGY)
    cross = build_cross(_one_scene(), _STRATEGY, _material(asr))
    ultra = build_ultra_short(_one_scene(), _STRATEGY, _material(asr))
    flow_len = flow.timeline[0].end - flow.timeline[0].start
    cross_len = cross.timeline[0].end - cross.timeline[0].start
    ultra_len = ultra.timeline[1].end - ultra.timeline[1].start
    assert flow_len == cross_len == ultra_len == 3.5


# ---- 转化门禁：收缩不得新增缺陷 ----------------------------------------------

def _defect_kinds(plan: object) -> list[str]:
    from dramaclip.engines.narration.models import PlanData

    assert isinstance(plan, PlanData)
    # 缺陷文案里带具体秒数（收缩后必然变化），比「类别前缀」而不是全串
    return sorted(issue.split("（")[0] for issue in defects(plan))


def test_shrink_adds_no_new_conversion_defects() -> None:
    """金句流收缩后必须干净过门禁；w5 两模式规划期本就有占位缺陷
    （旁白文案未成稿 / hook 段与冲突窗同起点重叠），收缩只许改秒数、不许加类别。"""
    asr = [_line(0.5, 3.5)]
    flow = build_subtitle_flow(_one_scene(), _material(asr), _STRATEGY)
    assert defects(flow) == []

    cross_shrunk = build_cross(_one_scene(), _STRATEGY, _material(asr))
    cross_baseline = build_cross(_one_scene(), _STRATEGY)
    assert _defect_kinds(cross_shrunk) == _defect_kinds(cross_baseline)

    ultra_shrunk = build_ultra_short(_one_scene(), _STRATEGY, _material(asr))
    ultra_baseline = build_ultra_short(_one_scene(), _STRATEGY)
    assert _defect_kinds(ultra_shrunk) == _defect_kinds(ultra_baseline)
