"""包外集号引用告警（W14-A·条件①后半句验证侧补强）：文案提到素材外的集号
→ soft+人审（生成侧 no_fabrication 已有强约束，这里是验证侧兜底）。"""

from __future__ import annotations

from dramaclip.engines.narration.audit import review_script


def _script(segments: list[dict]) -> dict:
    return {
        "hook": "开场钩子",
        "segments": segments,
        "cta": "点击左下角看全集",
    }


def _seg(episode: int, text: str, start: float = 0.0, end: float = 2.0) -> dict:
    return {"episode": episode, "start": start, "end": end, "text": text}


def test_out_of_pack_reference_flags() -> None:
    """素材 1-2 集、文案提「第15集」：soft 告警引用了包外集号。"""
    report = review_script(
        _script([_seg(1, "第一集铺垫。"), _seg(2, "她说：去看第15集的结局。")]),
        episode_durations={1: 100.0, 2: 90.0},
    )
    hits = [f for f in report.findings if f.rule_id == "FUND_EPISODE_OUT_OF_PACK"]
    assert hits and hits[0].passed is False
    assert "素材只到第2集" in hits[0].message


def test_in_pack_references_stay_silent() -> None:
    """集内引用（含「第1集/第2集」字样）不触发包外告警。"""
    report = review_script(
        _script([_seg(1, "第1集的伏笔在这里。"), _seg(2, "第2集的反转收束全剧。")]),
        episode_durations={1: 100.0, 2: 90.0},
    )
    hits = [f for f in report.findings if f.rule_id == "FUND_EPISODE_OUT_OF_PACK"]
    assert all(f.passed for f in hits), "集内引用不该判包外"


def test_full_width_digits_are_normalized() -> None:
    """全角数字引用同样识别（「第１５集」）。"""
    report = review_script(
        _script([_seg(1, "故事讲到第１５集才反转。")]),
        episode_durations={1: 100.0},
    )
    hits = [f for f in report.findings if f.rule_id == "FUND_EPISODE_OUT_OF_PACK"]
    assert hits and hits[0].passed is False
    assert "第15集" in hits[0].message
