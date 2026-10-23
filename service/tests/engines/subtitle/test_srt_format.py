"""SRT 时间码与块格式的唯一实现处。

工具箱的 `copy.srt` 与成片的逐句时间轴共用同一份写法：`HH:MM:SS,mmm` 是前端
`parseSrt` 的入参契约，两处手写就会有两个真相（档1 G2 判据唯一性同一族）。
本文件锁的是**改造前的既有行为**，含「空文本跳行但序号留空位」这条——它是现状，
不是设计目标，但重构不许顺手改语义。
"""

from __future__ import annotations

from dramaclip.engines.subtitle.srt import SrtCue, format_srt


def test_two_cues_render_blocks_joined_by_blank_line() -> None:
    text = format_srt(
        [
            SrtCue(start=0.0, end=2.5, text="第一句"),
            SrtCue(start=2.5, end=5.0, text="第二句"),
        ]
    )
    assert text == (
        "1\n00:00:00,000 --> 00:00:02,500\n第一句\n\n"
        "2\n00:00:02,500 --> 00:00:05,000\n第二句\n"
    )


def test_stamp_rounds_to_milliseconds_and_carries_into_minutes() -> None:
    assert format_srt([SrtCue(2.9999, 3661.5, "跨分钟与小时")]).startswith(
        "1\n00:00:03,000 --> 01:01:01,500\n"
    )


def test_empty_text_is_skipped_but_its_number_stays_spent() -> None:
    """现状锁定：序号按输入位置走，跳过的空行不回收编号（前端解析器不校验连号）。"""
    text = format_srt([SrtCue(0.0, 1.0, "有"), SrtCue(1.0, 2.0, "   "), SrtCue(2.0, 3.0, "又")])
    assert text == (
        "1\n00:00:00,000 --> 00:00:01,000\n有\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\n又\n"
    )


def test_no_cue_yields_empty_file_not_a_trailing_newline() -> None:
    assert format_srt([]) == ""
    assert format_srt([SrtCue(0.0, 1.0, "")]) == ""
