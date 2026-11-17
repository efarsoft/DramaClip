"""W8·TTS 忠实度防线：口播 flatten 与舞台指令影子扫描（纯函数层）。

生成式 TTS 的三类已知翻车里，冒号引语（吞说话人标签/引语变声演绎）由
flatten 在合成前压成叙述流（只动标点不换词，字幕层不受影响）；括号舞台
指令 flatten 不了，影子扫描 warn 留痕不拦片（报告不是门禁，reference_qc
同款边界）。
"""

from __future__ import annotations

from dramaclip.engines.narration.synthesis import (
    _STAGE_DIRECTION_RE,
    flatten_speech_text,
)


def test_flatten_unfolds_colon_quote() -> None:
    """冒号引语压叙述流：冒号→逗号、去引号，字词不动。"""
    assert flatten_speech_text("他说：「门没有锁」") == "他说，门没有锁"
    assert flatten_speech_text("她只留下一句：“等我回来。”") == "她只留下一句，等我回来。"


def test_flatten_keeps_plain_text_intact() -> None:
    """无引语普通句逐字不变；问号不在冒号位也不动。"""
    plain = "他推开门，屋里一片漆黑。"
    assert flatten_speech_text(plain) == plain
    assert flatten_speech_text("凭什么是我？") == "凭什么是我？"


def test_stage_direction_regex_matches_paren_notes() -> None:
    """括号舞台指令命中；正常括号数字/年份不误伤太宽（≤10 字窗口）。"""
    assert _STAGE_DIRECTION_RE.search("枪声再起（枪响）众人散开")
    assert _STAGE_DIRECTION_RE.search("（冷笑）") is not None
    assert not _STAGE_DIRECTION_RE.search("一九九七年冬天来了")
