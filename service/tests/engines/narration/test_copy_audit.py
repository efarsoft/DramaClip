"""copy_audit（逐槽文案审查）单测。

自 test_audit.py 拆出（拆分专项）：review_copy 已移出 audit 模块，
copy 审查的测试随之独立——脚本审查测试留在 test_audit.py。
"""

from __future__ import annotations

from dramaclip.engines.narration.copy_audit import review_copy


def test_review_copy_catches_missing_slot_and_meta() -> None:
    slots = [
        {"id": "s1", "task": "开场", "start": 0.0, "end": 12.5, "lines": "x"},
        {"id": "s2", "task": "点银两", "start": 24.0, "end": 38.0, "lines": "y"},
    ]
    bad_lines = [
        {"id": "s1", "text": "苏明月被当众羞辱，这镜头看得人牙痒。"},  # s2 漏 + 镜头
    ]
    rep = review_copy(bad_lines, slots)
    failed = {f.rule_id for f in rep.hard_fails}
    assert "COPY_COVER_ALL_IDS" in failed
    assert "COPY_NO_METANARRATIVE" in failed


def test_review_copy_good_passes() -> None:
    slots = [{"id": f"s{i}", "task": "t", "start": 0.0, "end": 5.0, "lines": "x"} for i in range(3)]
    lines = [{"id": f"s{i}", "text": "短句文案，无元叙述，声纹已换名。"} for i in range(3)]
    rep = review_copy(lines, slots)
    assert rep.passed


def test_copy_line_cap_accepts_production_tolerance() -> None:
    """review 与生产同容差（cap×1.2）：61–72 字的生产放行稿不得在审查里恒 REJECT。"""
    report = review_copy(
        [{"id": "a", "text": "字" * 65}], [{"id": "a"}], mode="full_narration"
    )
    line = [f for f in report.findings if f.rule_id == "COPY_LINE_CAP"]
    assert line and line[0].passed is True, "65 字 ≤ 72（60×1.2）生产容差，审查不得翻脸"
