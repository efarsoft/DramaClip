"""对白质量打分（0-100）：字幕金句流用它挑每段最强一句。

金句有两个物种，打分器两个都认（2026-10-08 业主以《剑来》纠偏）：
- 冲突型：情绪词/冲突词/威胁句式（爽剧狠话）；
- 豪情·哲理型：排比递进/对仗/意象/世间清醒断言（文戏金句）——
  「唯有一剑，可搬山，倒海，降妖，镇魔」零情绪词，却是千古名句。

注意边界：人味纪律②禁排比，约束的是**我们写的解说正文**；
金句流选的是**原片台词**——原片的排比是它的高光，不是我们的 AI 味。
"""

from __future__ import annotations

import re

_EMOTION_WORDS: tuple[str, ...] = (
    "哭", "笑", "怒", "恨", "爱", "怕", "求", "滚", "杀", "死", "疯了", "不敢", "竟然", "居然",
)
_CONFLICT_WORDS: tuple[str, ...] = (
    "滚", "闭嘴", "废物", "打死", "报仇", "复仇", "背叛", "离婚", "证据", "真相", "骗子", "威胁",
)
_TONE_MARKS: tuple[str, ...] = ("！", "？", "!?", "……")
# 意象词：文戏金句的血肉（清风明月/三尺剑/春风），具体名词比形容词可信
_IMAGERY_WORDS: tuple[str, ...] = (
    "风", "月", "雪", "剑", "花", "江", "山", "海", "星", "火", "酒", "夜", "刀", "灯",
)
# 世间清醒式断言的句首/句中标记
_ASSERTION_MARKERS: tuple[str, ...] = (
    "真正的", "世上", "人间", "从来", "根本", "理所应当", "所谓", "不过",
)
_MIN_LINE_S = 2.0
_MAX_LINE_S = 8.0


def _parallel_bonus(text: str) -> int:
    """排比递进：≥3 个长度相近的并列短成分（顿号/逗号分隔）。

    「可搬山，倒海，降妖，镇魔，敕神，摘星」——同构短语连发，气势递增。"""
    segments = [seg.strip() for seg in re.split(r"[，,、]", text) if seg.strip()]
    if len(segments) < 3:
        return 0
    lens = [len(seg) for seg in segments]
    if max(lens) - min(lens) <= max(4, min(lens) * 0.6):
        return 24 if len(segments) >= 4 else 16
    return 0


def _couplet_bonus(text: str) -> int:
    """对仗/顶真：两半长度相近（「但愿世间人无病，宁可架上药成灰」），
    或分句首尾同词接龙（「可问春风；春风不语」）。"""
    halves = re.split(r"[；;，,]", text, maxsplit=1)
    if len(halves) != 2:
        return 0
    left, right = halves[0].strip(), halves[1].strip()
    if min(len(left), len(right)) >= 4 and 0.7 <= len(left) / max(len(right), 1) <= 1.4:
        return 12
    return 0


def _anadiplosis_bonus(text: str) -> int:
    """顶真接龙：前句尾词 = 后句首词（「可问春风；春风不语」）——文戏金句的接骨法。"""
    halves = [h.strip(" ；;，,。") for h in re.split(r"[；;]", text)]
    for a, b in zip(halves, halves[1:], strict=False):
        if len(a) >= 2 and len(b) >= 2 and (a.endswith(b[:2]) or b.startswith(a[-2:])):
            return 14
    return 0


def _progression_bonus(text: str) -> int:
    """递进修辞：数字抬升（十分力气→十二分力气）。"""
    if re.search(r"[一两三四五六七八九十几]分[^，。；]*[一二三四五六七八九十几]分", text):
        return 10
    return 0


def score_line(text: str, duration_s: float, *, independent: bool = False) -> int:
    """单句对白质量分（0-100）：修辞结构为主、情绪词表为辅。"""
    emotion = sum(text.count(word) for word in _EMOTION_WORDS)
    conflict = sum(text.count(word) for word in _CONFLICT_WORDS)
    tone = sum(text.count(mark) for mark in _TONE_MARKS)
    imagery = sum(1 for word in _IMAGERY_WORDS if word in text)
    assertions = sum(1 for word in _ASSERTION_MARKERS if word in text)
    length_bonus = 8 if _MIN_LINE_S <= duration_s <= _MAX_LINE_S else 0
    raw = (
        min(emotion * 8, 16)
        + min(conflict * 10, 20)
        + min(tone * 4, 8)
        + min(imagery * 4, 12)
        + min(assertions * 8, 16)
        + _parallel_bonus(text)
        + _couplet_bonus(text)
        + _anadiplosis_bonus(text)
        + _progression_bonus(text)
        + length_bonus
        + (10 if independent else 0)
    )
    return max(0, min(100, 30 + raw))
