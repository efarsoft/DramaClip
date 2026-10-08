"""转化门禁：无 CTA / 空喊关注的方案进不了作品库。"""

from __future__ import annotations

from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment


def _plan(*, mode: str = "full_narration", last: str, first_end: float = 3.0) -> PlanData:
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=first_end, audio="ducked", narration_id="a"
            ),
            TimelineSegment(
                episode_id="ep1",
                start=first_end,
                end=first_end + 2.0,
                audio="ducked",
                narration_id="b",
            ),
        ],
        narration_texts=[
            NarrationText(id="a", text="开场钩子"),
            NarrationText(id="b", text=last),
        ],
    )


def test_cta_pointing_at_full_series_passes() -> None:
    assert defects(_plan(last="后面更狠——点进去看全集")) == []


def test_missing_cta_is_a_defect() -> None:
    assert "收尾没有指向看全集" in defects(_plan(last="今天就讲到这里"))


def test_banned_follow_cta_is_a_defect() -> None:
    issues = defects(_plan(last="关注我看全集"))
    assert "收尾禁止关注/点赞/二维码" in issues


def test_raw_clip_skips_cta_copy() -> None:
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    assert defects(plan) == []


def test_empty_timeline_fails() -> None:
    assert defects(PlanData(mode="full_narration")) == ["空时间轴"]


def test_grade_is_ready_only_when_defects_empty() -> None:
    from dramaclip.engines.narration.conversion import grade

    assert grade(_plan(last="后面更狠——点进去看全集")) == "ready"
    assert grade(_plan(last="今天就讲到这里")) == "draft"
    assert grade(PlanData(mode="raw_clip", timeline=[
        TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")
    ])) == "ready"


def test_intro_hook_cta_does_not_pass_for_the_ending() -> None:
    """片头写了看全集，不等于片尾有 CTA。"""
    plan = PlanData(
        mode="intro_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="narration", narration_id="intro"
            ),
            TimelineSegment(episode_id="ep1", start=3.0, end=20.0, audio="original"),
        ],
        narration_texts=[
            NarrationText(id="intro", text="开场钩子，后面更狠——点进去看全集"),
        ],
    )
    assert "收尾没有文案" in defects(plan)


def test_last_segment_subtitle_cta_passes() -> None:
    plan = PlanData(
        mode="subtitle_flow",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="original", subtitle_text="金句"
            ),
            TimelineSegment(
                episode_id="ep1",
                start=3.0,
                end=6.0,
                audio="original",
                subtitle_text="后面更狠——点进去看全集",
            ),
        ],
    )
    assert defects(plan) == []


# ------------------------------------------------------------- 时间轴合法性缺陷（批次一 A2）
# 纯 plan 数据可判的幻觉时间戳：负起点、end<=start、同集段区间重叠。
# 此前只有 CTA/禁用词缺陷——LLM 剧本链坏时间轴一路放行到渲染期才暴雷。


def _good_tail() -> tuple[list[TimelineSegment], list[NarrationText]]:
    """结尾两段带合法 CTA，让新缺陷是断言里唯一新增项。"""
    return (
        [
            TimelineSegment(
                episode_id="ep1", start=0.0, end=3.0, audio="ducked", narration_id="a"
            ),
            TimelineSegment(
                episode_id="ep1", start=3.0, end=6.0, audio="ducked", narration_id="b"
            ),
        ],
        [
            NarrationText(id="a", text="开场钩子"),
            NarrationText(id="b", text="后面更狠——点进去看全集"),
        ],
    )


def test_negative_start_is_a_defect() -> None:
    timeline, texts = _good_tail()
    timeline[0] = timeline[0].model_copy(update={"start": -1.0})
    plan = PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)
    assert any("起点为负" in issue for issue in defects(plan))


def test_end_before_start_is_a_defect() -> None:
    timeline, texts = _good_tail()
    timeline[1] = timeline[1].model_copy(update={"end": 1.0})  # start=3.0 > end
    plan = PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)
    assert any("结束不晚于开始" in issue for issue in defects(plan))


def test_overlap_within_episode_is_a_defect_for_llm_timelines() -> None:
    """dialogue_narration（唯一 LLM 产时间轴的模式）同集两段画面区间重叠＝
    成片重播同一段素材（业主立案③），门禁必须拦。"""
    timeline, texts = _good_tail()
    timeline[1] = timeline[1].model_copy(update={"start": 2.0, "end": 6.0})  # 与 [0,3) 重叠
    plan = PlanData(mode="dialogue_narration", timeline=timeline, narration_texts=texts)
    assert any("重叠" in issue for issue in defects(plan))


def test_rule_arranged_designed_overlaps_are_not_defects() -> None:
    """规则模式的 CTA 卡/旁白桥重叠是**设计**（尾卡叠在既有画面上），不是幻觉：
    批次一把重叠检查扩到全部模式，四个规则模式恒 draft、生产线全断（真回归）。
    形状取自 build_intro/build_ultra_short 的真实构造：尾段是前段的真子区间。"""
    timeline, texts = _good_tail()
    # intro 形状：CTA 卡复用最后场景尾部画面（_CTA_FALLBACK_S=2s）
    timeline[1] = timeline[1].model_copy(update={"start": 1.0, "end": 3.0})  # ⊂ [0,3) 同集
    plan = PlanData(mode="intro_narration", timeline=timeline, narration_texts=texts)
    assert not any("重叠" in issue for issue in defects(plan))
    # raw_clip 同样豁免重叠（规则编排），但时间轴合法性照查
    raw = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=0.0, end=8.0, audio="original"),
            TimelineSegment(episode_id="ep1", start=6.0, end=8.0, audio="original"),
        ],
    )
    assert not any("重叠" in issue for issue in defects(raw))


def test_rule_modes_still_reject_corrupt_spans() -> None:
    """重叠豁免不豁免合法性：规则模式出现负起点/结束不晚于开始照样拦
    （生产上写不出这种段，出现即存储损坏或代码 bug）。"""
    timeline, texts = _good_tail()
    timeline[0] = timeline[0].model_copy(update={"start": -1.0})
    plan = PlanData(mode="intro_narration", timeline=timeline, narration_texts=texts)
    assert any("起点为负" in issue for issue in defects(plan))


def test_same_span_in_different_episodes_is_not_overlap() -> None:
    """跨集本来就会重复用相似时间码：只有同集内两两比才算重叠。"""
    timeline, texts = _good_tail()
    timeline[1] = timeline[1].model_copy(update={"episode_id": "ep2", "start": 2.0})
    plan = PlanData(mode="dialogue_narration", timeline=timeline, narration_texts=texts)
    assert not any("重叠" in issue for issue in defects(plan))


def test_touching_ends_are_not_overlap() -> None:
    """首尾相接（前段 end == 后段 start）是连续推进，不是重叠。"""
    timeline, texts = _good_tail()
    plan = PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)
    assert defects(plan) == []


def test_raw_clip_still_checks_timeline_legality() -> None:
    """raw_clip 豁免的是 CTA 文案检查（无旁白），时间轴合法性照查——
    现有口径就是「raw_clip 无旁白，只查时间轴」。"""
    plan = PlanData(
        mode="raw_clip",
        timeline=[
            TimelineSegment(episode_id="ep1", start=5.0, end=3.0, audio="original"),
        ],
    )
    assert any("结束不晚于开始" in issue for issue in defects(plan))


def test_ultra_short_thin_copy_is_a_defect() -> None:
    """超短全稿 <60 字 = 钩子没展开就收尾（首版实测 24 字/6 秒残件）→ draft 重掷。"""
    plan = PlanData(
        mode="ultra_short_hook",
        timeline=[
            TimelineSegment(episode_id="ep-1", start=0.0, end=3.0, audio="narration"),
            TimelineSegment(episode_id="ep-1", start=3.0, end=9.0, audio="original"),
            TimelineSegment(episode_id="ep-1", start=9.0, end=12.0, audio="narration"),
        ],
        narration_texts=[
            NarrationText(id="hook-1", text="他杀妻夺产，殊不知她是龙王"),
            NarrationText(id="cta-1", text="点击左下角看全集"),
        ],
    )
    issues = defects(plan)
    assert any("钩子没展开" in item for item in issues), issues


def test_ultra_short_dense_copy_passes() -> None:
    plan = PlanData(
        mode="ultra_short_hook",
        timeline=[
            TimelineSegment(
                episode_id="ep-1", start=0.0, end=12.0, audio="narration", narration_id="hook-1"
            ),
            TimelineSegment(episode_id="ep-1", start=12.0, end=20.0, audio="original"),
            TimelineSegment(
                episode_id="ep-1", start=20.0, end=26.0, audio="narration", narration_id="cta-1"
            ),
        ],
        narration_texts=[
            NarrationText(
                id="hook-1",
                text="花几百万两买凶杀妻，八年后她以龙王之尊踏浪归来——当年沉海的弃妇，如今执掌四海生杀。",
            ),
            NarrationText(
                id="cta-1",
                text="寿宴上他还在等她跪下，却不知龙魂已醒。点击左下角，免费观看全集。",
            ),
        ],
    )
    # _cta_text 认最后一段旁白：时间轴尾段的 narration_id 必须接上 cta-1（与真实编排同形）
    assert defects(plan) == []


def test_highlight_cut_pure_cut_skips_cta_gate() -> None:
    """高光混剪与 raw_clip 同族：零旁白零 CTA，不判「收尾没有文案」。

    2026-10-08 真机：新模式漏了豁免名单，恒为 draft 不能出片。"""
    from dramaclip.engines.narration.models import PlanData, TimelineSegment

    plan = PlanData(
        mode="highlight_cut",
        timeline=[
            TimelineSegment(episode_id="ep1", start=24.5, end=29.5, audio="original"),  # type: ignore[arg-type]
            TimelineSegment(episode_id="ep1", start=105.0, end=110.0, audio="original"),  # type: ignore[arg-type]
        ],
    )
    assert defects(plan) == [], "纯剪辑形态不判收尾文案"