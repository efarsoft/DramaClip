"""解说模式测试共享断言。

槽位↔画面段的配对是 `copywriter` 的输入契约（它按 `narration_id` 去配对段取画面区间），
六个模式各自复述这条不变量只会写出五种版本：这里收成一个函数，各模式测试都调它。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData


def assert_slots_paired(plan: PlanData, label: str) -> None:
    """槽位↔画面段按 narration_id 一一配对；编排器不得自带成稿句子。"""
    claimed = [segment.narration_id for segment in plan.timeline if segment.narration_id]
    assert claimed == [text.id for text in plan.narration_texts], f"{label}：段与文案配对断裂"
    assert all(text.brief for text in plan.narration_texts), f"{label}：槽位缺职责 → 编剧无从下笔"
    assert all(not text.text for text in plan.narration_texts), f"{label}：编排器不得自带句子"
