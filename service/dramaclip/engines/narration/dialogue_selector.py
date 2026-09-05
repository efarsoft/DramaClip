"""剧情解说模式（原案 6.6）：对白筛选 + 起承转合编排。

不用 AI 旁白——从原片提取最精彩对白，让角色自己讲故事（预告片式）。
切割粒度为 ASR 对白句（非场景），全部原声。
打分维度：情绪词密度 + 冲突关键词 + 语气符号 + 句长适中（2-8s）。
LLM 起承转合精排留接口（接入前降级为"高分开场 + 时间线推进"）。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, SpeechZone
from dramaclip.engines.narration.models import PlanData, StrategySpec, TimelineSegment

_EMOTION_WORDS: tuple[str, ...] = (
    "哭", "笑", "怒", "恨", "爱", "怕", "求", "滚", "杀", "死", "疯了", "不敢", "竟然", "居然",
)
_CONFLICT_WORDS: tuple[str, ...] = (
    "滚", "闭嘴", "废物", "打死", "报仇", "复仇", "背叛", "离婚", "证据", "真相", "骗子", "威胁",
)
_TONE_MARKS: tuple[str, ...] = ("！", "？", "!?", "……")
_MIN_LINE_S = 2.0
_MAX_LINE_S = 8.0
_GAP_TOLERANCE_S = 0.6  # 与语音区间隙 < 此值视为"独立句"（前后停顿清晰）
_SCORE_FLOOR = 30       # 低于此分的句子不入选


def score_line(text: str, duration_s: float, *, independent: bool = False) -> int:
    """单句对白质量分（0-100）。"""
    emotion = sum(text.count(word) for word in _EMOTION_WORDS)
    conflict = sum(text.count(word) for word in _CONFLICT_WORDS)
    tone = sum(text.count(mark) for mark in _TONE_MARKS)
    length_bonus = 8 if _MIN_LINE_S <= duration_s <= _MAX_LINE_S else 0
    raw = emotion * 10 + conflict * 12 + tone * 6 + length_bonus + (10 if independent else 0)
    return max(0, min(100, 30 + raw))


def select_dialogue_lines(
    segments: list[AsrSegment],
    audio: AudioFeatures,
) -> list[tuple[AsrSegment, int]]:
    """筛选高质量对白句：打分 + 阈值 + 独立性判定，按时间排序。"""
    zones = audio.speech_zones
    picked: list[tuple[AsrSegment, int]] = []
    for segment in segments:
        duration = segment.end - segment.start
        if duration < _MIN_LINE_S:
            continue
        independent = _has_clear_gap(segment, zones)
        score = score_line(segment.text, duration, independent=independent)
        if score >= _SCORE_FLOOR:
            picked.append((segment, score))
    return picked


def build_dialogue(
    episode_id: str,
    dialogue_lines: list[tuple[AsrSegment, int]],
    strategy: StrategySpec,
) -> PlanData:
    """起承转合编排（降级版）：最高分开场 → 其余按时间线 → 收尾取最靠后的悬念句。

    转场：段头 0.25s 快速淡入（encoder 侧 fade），提升预告片节奏感。
    """
    if not dialogue_lines:
        return PlanData(mode="dialogue_narration", strategy=strategy)

    ordered = sorted(dialogue_lines, key=lambda pair: pair[0].start)
    best = max(ordered, key=lambda pair: pair[1])
    # 开场换为最高分句（预告片钩子），其余保持时间线
    rest = [pair for pair in ordered if pair is not best]
    body = [best, *rest]

    segments: list[TimelineSegment] = []
    used = 0.0
    budget = strategy.max_duration_s
    for index, (segment, _score) in enumerate(body):
        duration = segment.end - segment.start
        is_edge = index == 0 or index == len(body) - 1
        if not is_edge and used + duration > budget:
            continue
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(segment.start, 3),
                end=round(segment.end, 3),
                audio="original",
                transition="fade" if index > 0 else "cut",
            )
        )
        used += duration
    return PlanData(mode="dialogue_narration", timeline=segments, strategy=strategy)


def _has_clear_gap(segment: AsrSegment, zones: list[SpeechZone]) -> bool:
    """句前/句后存在 ≥0.6s 的非语音间隙（停顿清晰、可独立成句）。"""

    def covered(t: float) -> bool:
        margin = _GAP_TOLERANCE_S
        return any(zone.start - margin <= t <= zone.end + margin for zone in zones)

    if not zones:
        return True  # 无语音区数据时不惩罚
    head_clear = not covered(segment.start)
    tail_clear = not covered(segment.end)
    return head_clear or tail_clear
