"""解说字幕的行时间：词界对齐、比例回退、最短可读停留（纯函数）。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.subtitle import narration_lines as nl
from dramaclip.engines.subtitle.ass_generator import split_subtitle_text

# 真配音实测的词界（edge-tts 7.3.1）：文本不带标点，还会在词中间断开
_TEXT = "六千六百六十六都掏了，新娘却连车门都不肯上——这场婚礼还能不能成？"
_CUES: list[dict[str, Any]] = [
    {"text": "六千六百六", "start": 0.1, "end": 1.125},
    {"text": "十六都", "start": 1.225, "end": 1.725},
    {"text": "掏", "start": 1.725, "end": 1.988},
    {"text": "了", "start": 1.988, "end": 2.163},
    {"text": "新娘", "start": 2.538, "end": 2.987},
    {"text": "却", "start": 3.0, "end": 3.125},
    {"text": "连", "start": 3.125, "end": 3.288},
    {"text": "车门", "start": 3.3, "end": 3.763},
    {"text": "都", "start": 3.85, "end": 3.962},
    {"text": "不肯", "start": 3.975, "end": 4.263},
    {"text": "上", "start": 4.263, "end": 4.513},
    {"text": "这", "start": 4.9, "end": 5.062},
    {"text": "场", "start": 5.062, "end": 5.225},
    {"text": "婚礼", "start": 5.237, "end": 5.725},
    {"text": "还", "start": 5.825, "end": 5.975},
    {"text": "能", "start": 5.975, "end": 6.088},
    {"text": "不能", "start": 6.1, "end": 6.375},
    {"text": "成", "start": 6.375, "end": 6.688},
]
_LINES = ["六千六百六十六都掏了", "新娘却连车门都不肯上", "这场婚礼还能不能成？"]
_TIMES = [(0.1, 2.163), (2.538, 4.513), (4.9, 6.688)]


def test_align_cues_maps_punctuation_less_tokens_back_onto_the_text() -> None:
    words = nl.align_cues(_TEXT, _CUES)

    assert words is not None
    # 「十六都」是「六千六百六十六」的后三个字；「新娘」前面隔着逗号
    assert words[1][:2] == (5, 8) and words[4][:2] == (11, 13)
    assert words[-1][:2] == (31, 32), "行尾字的位置要落在原文最后一个字上"


def test_align_cues_skips_spaces_between_tokens() -> None:
    words = nl.align_cues(
        "她走了。 他没追",
        [{"text": "她走了", "start": 0, "end": 1}, {"text": "他没追", "start": 1.4, "end": 2.5}],
    )

    assert words is not None and [w[:2] for w in words] == [(0, 3), (5, 8)]


@pytest.mark.parametrize(
    ("text", "cues"),
    [
        # 数字被念成别的写法：token 与原文对不上
        ("6666都掏了，新娘却连车门都不肯上", _CUES),
        # 原文里还有字没被念到
        (_TEXT, _CUES[:-1]),
        (_TEXT, [{"text": "六千六百六", "start": "abc", "end": 1.125}]),
        (_TEXT, ["六千六百六"]),
        (_TEXT, []),
    ],
    ids=["digits", "unspoken-tail", "bad-time", "not-a-dict", "empty"],
)
def test_align_cues_refuses_anything_it_cannot_map(text: str, cues: list[Any]) -> None:
    assert nl.align_cues(text, cues) is None


def test_lines_from_cues_share_the_text_split_and_take_real_word_times() -> None:
    lines = nl.lines_from_cues(_TEXT, _CUES, 16)

    assert lines is not None
    assert [line.text for line in lines] == split_subtitle_text(_TEXT, 16) == _LINES
    assert [(line.start, line.end) for line in lines] == _TIMES


def test_lines_from_cues_fall_back_when_tokens_do_not_match() -> None:
    assert nl.lines_from_cues("6666都掏了", _CUES, 16) is None


def test_lines_by_share_splits_the_segment_by_character_count() -> None:
    lines = nl.lines_by_share(_TEXT, 16, 7.46)

    assert [line.text for line in lines] == _LINES
    assert lines[-1].end == 7.46, "末行收在段尾"
    assert [round(line.end, 3) for line in lines[:-1]] == [2.487, 4.973], "三行各十字：均分"
    assert all(a.end == b.start for a, b in zip(lines, lines[1:], strict=False))


def test_lines_by_share_survives_blank_text() -> None:
    """空白文案只有一条 0 字行：按字数比例分时长是除零的来源。"""
    lines = nl.lines_by_share("   ", 16, 3.0)

    assert [(line.start, line.end, line.text) for line in lines] == [(0.0, 3.0, "")]


def test_hold_readable_extends_only_the_end() -> None:
    lines = [nl.TimedLine(0.0, 0.4, "她走了"), nl.TimedLine(2.0, 5.0, "下一行")]

    held = nl.hold_readable(lines, limit=5.0)

    assert (held[0].start, held[0].end) == (0.0, 0.8)
    assert held[1] == lines[1], "后面的行一个字都不许动"


def test_hold_readable_never_crosses_the_next_line() -> None:
    lines = [nl.TimedLine(0.0, 0.4, "她走了"), nl.TimedLine(0.6, 5.0, "下一行")]

    held = nl.hold_readable(lines, limit=5.0)

    assert held[0].end == round(0.6 - nl.LINE_GAP_S, 3), "延末点不许压到下一行上"
    assert held[0].start == 0.0, "首行前面没有可借的，起点不动"


def test_hold_readable_borrows_from_the_previous_line_when_the_end_has_no_room() -> None:
    """按字数比例分配的行首尾相接，末点没有空间：只能向前一行借，前一行自己也得留够。"""
    lines = [
        nl.TimedLine(0.0, 2.0, "长行"),
        nl.TimedLine(2.0, 2.4, "她走了"),
        nl.TimedLine(2.4, 6.0, "下一行"),
    ]

    held = nl.hold_readable(lines, limit=6.0)

    assert (held[1].start, held[1].end) == (1.6, 2.4)
    assert held[0].end == round(1.6 - nl.LINE_GAP_S, 3)
    assert held[2] == lines[2]


def test_hold_readable_uses_the_natural_pause_before_touching_the_previous_line() -> None:
    """词界路径的行间本来就有念白停顿：先用停顿，前一行不被削。"""
    lines = [
        nl.TimedLine(0.0, 2.0, "长行"),
        nl.TimedLine(2.5, 2.9, "她走了"),
        nl.TimedLine(3.0, 6.0, "下一行"),
    ]

    held = nl.hold_readable(lines, limit=6.0)

    assert (held[1].start, held[1].end) == (2.12, round(3.0 - nl.LINE_GAP_S, 3))
    assert held[0] == lines[0]


def test_hold_readable_cuts_into_the_previous_line_only_past_the_pause() -> None:
    """停顿不够才动前一行：削掉的只是缺口，前一行留下毫秒取整的整终点。"""
    lines = [
        nl.TimedLine(0.0, 2.0, "长行"),
        nl.TimedLine(2.45, 2.85, "她走了"),
        nl.TimedLine(2.95, 6.0, "下一行"),
    ]

    held = nl.hold_readable(lines, limit=6.0)

    assert held[1].end - held[1].start >= nl.MIN_DISPLAY_S - 1e-9
    assert held[0].end == 1.99 and held[0].start == 0.0


def test_hold_readable_never_starves_the_previous_line() -> None:
    """前一行自己刚够最短停留：不许再借给它，宁可持续不足也不制造新的过短行。"""
    lines = [
        nl.TimedLine(0.0, 0.9, "刚刚够"),
        nl.TimedLine(0.9, 1.2, "她走了"),
        nl.TimedLine(1.2, 6.0, "下一行"),
    ]

    held = nl.hold_readable(lines, limit=6.0)

    assert held[0].end - held[0].start >= nl.MIN_DISPLAY_S - 1e-9
    assert held[1].start >= held[0].end


def test_hold_readable_leaves_long_lines_alone() -> None:
    lines = [nl.TimedLine(0.1, 2.163, "第一行"), nl.TimedLine(2.538, 4.513, "第二行")]

    assert nl.hold_readable(lines, limit=7.46) == lines


def test_hold_readable_keeps_lines_ordered_and_overlap_free() -> None:
    lines = [
        nl.TimedLine(0.0, 0.3, "她"),
        nl.TimedLine(0.35, 0.5, "走了"),
        nl.TimedLine(0.55, 0.7, "他"),
        nl.TimedLine(0.75, 6.0, "没追"),
    ]

    held = nl.hold_readable(lines, limit=6.0)

    assert all(line.end > line.start for line in held)
    assert all(
        a.start <= b.start and a.end <= b.start + 1e-9 for a, b in zip(held, held[1:], strict=False)
    )


@pytest.mark.parametrize(
    "cues", [None, [], [{"text": "六千", "start": 0, "end": 1}]], ids=["none", "marker", "mismatch"]
)
def test_narration_lines_falls_back_to_share_without_usable_cues(cues: list[Any] | None) -> None:
    lines = nl.narration_lines(_TEXT, cues, 16, 7.46)

    assert lines == nl.hold_readable(nl.lines_by_share(_TEXT, 16, 7.46), limit=7.46)


def test_narration_lines_follows_real_word_times_when_cues_are_usable() -> None:
    lines = nl.narration_lines(_TEXT, _CUES, 16, 7.46)

    assert [(line.start, line.end) for line in lines] == _TIMES
