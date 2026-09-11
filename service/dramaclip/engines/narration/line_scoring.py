"""对白质量打分（0-100）：字幕金句流用它挑每段最强一句。"""

from __future__ import annotations

_EMOTION_WORDS: tuple[str, ...] = (
    "哭", "笑", "怒", "恨", "爱", "怕", "求", "滚", "杀", "死", "疯了", "不敢", "竟然", "居然",
)
_CONFLICT_WORDS: tuple[str, ...] = (
    "滚", "闭嘴", "废物", "打死", "报仇", "复仇", "背叛", "离婚", "证据", "真相", "骗子", "威胁",
)
_TONE_MARKS: tuple[str, ...] = ("！", "？", "!?", "……")
_MIN_LINE_S = 2.0
_MAX_LINE_S = 8.0


def score_line(text: str, duration_s: float, *, independent: bool = False) -> int:
    """单句对白质量分（0-100）。"""
    emotion = sum(text.count(word) for word in _EMOTION_WORDS)
    conflict = sum(text.count(word) for word in _CONFLICT_WORDS)
    tone = sum(text.count(mark) for mark in _TONE_MARKS)
    length_bonus = 8 if _MIN_LINE_S <= duration_s <= _MAX_LINE_S else 0
    raw = emotion * 10 + conflict * 12 + tone * 6 + length_bonus + (10 if independent else 0)
    return max(0, min(100, 30 + raw))
