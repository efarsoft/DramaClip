"""花字 span 级精细化：build_ass 行元素可选 span_emotions → 按字符区间插内联 override。

不给 span_emotions 时输出必须与旧行为**逐字节一致**（既有全部用例零改动通过的另一面）。
"""

from __future__ import annotations

import re

from dramaclip.engines.subtitle import presets
from dramaclip.engines.subtitle.ass_generator import build_ass


def _dialogue_body(ass: str, index: int = 0) -> str:
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    return lines[index].split(",", 9)[9]


def test_absent_span_emotions_is_byte_identical() -> None:
    """span_emotions 缺省 / None / 空列表：三种形状的输出与旧输出逐字节相同。"""
    preset = presets.get_preset("conflict-impact")
    line = {"start": 0.0, "end": 2.0, "text": "今天天气不错", "emotion_label": None}
    baseline = build_ass([dict(line)], preset)
    assert baseline == build_ass([{**line, "span_emotions": None}], preset)
    assert baseline == build_ass([{**line, "span_emotions": []}], preset)
    # 兜底：基线形状没被本批实现顺手改掉（行首整段 override + 裸文本）
    body = _dialogue_body(baseline)
    assert body.startswith("{") and body.endswith("今天天气不错")
    assert body.count("{") == 1


def test_span_inserts_inline_color_override_at_boundary() -> None:
    """区间 [4,6) 标 angry：该区间前插 \\c+\\3c（与整行情绪同形的内联 override）。"""
    preset = presets.get_preset("conflict-impact")
    ass = build_ass(
        [{"start": 0, "end": 2, "text": "今天天气不错", "span_emotions": [(4, 6, "angry")]}],
        preset,
    )
    body = _dialogue_body(ass)
    assert "{\\c&H000000FF\\3c&H00FFFFFF}不错" in body, f"span 区间没插冲突红 override：{body}"
    assert body.index("今天天气") < body.index("{\\c&H000000FF"), "override 必须插在区间起点前"


def test_span_reverts_to_base_color_after_the_span() -> None:
    """区间结束后必须回插整行底色：否则后面所有字都染着 span 的颜色。"""
    preset = presets.get_preset("conflict-impact")
    ass = build_ass(
        [{"start": 0, "end": 2, "text": "今天天气不错", "span_emotions": [(0, 2, "angry")]}],
        preset,
    )
    body = _dialogue_body(ass)
    assert "{\\c&H000000FF\\3c&H00FFFFFF}今天" in body
    assert "{\\c&H00FFFFFF\\3c&H00000000}天气不错" in body, f"span 之后没回底色：{body}"


def test_span_labels_go_through_emotion_normalization() -> None:
    """span 的情绪走与整行同一套 match_emotion 归一化（Angry/angry 同键）。"""
    preset = presets.get_preset("conflict-impact")
    upper = build_ass(
        [{"start": 0, "end": 2, "text": "今天天气不错", "span_emotions": [(4, 6, "Angry")]}],
        preset,
    )
    lower = build_ass(
        [{"start": 0, "end": 2, "text": "今天天气不错", "span_emotions": [(4, 6, "anger")]}],
        preset,
    )
    assert upper == lower


def test_malformed_spans_are_dropped_not_raised() -> None:
    """坏区间（空/倒序/越界/非三元组）逐个丢弃：花字是增益，不许把出片炸掉。"""
    preset = presets.get_preset("conflict-impact")
    ass = build_ass(
        [
            {
                "start": 0,
                "end": 2,
                "text": "今天天气不错",
                "span_emotions": [
                    (5, 3, "angry"),      # 倒序
                    (9, 99, "angry"),     # 越界起点
                    ("x", 2, "angry"),    # 坏类型
                    (0, 2),               # 非三元组
                ],
            }
        ],
        preset,
    )
    body = _dialogue_body(ass)
    assert re.sub(r"\{[^{}]*\}", "", body) == "今天天气不错"


def test_karaoke_rhythm_ignores_spans() -> None:
    """karaoke 的逐字 \\k 与区间 override 互斥：span 在该路径下忽略，输出与不给一致。"""
    preset = presets.get_preset("karaoke-pop")
    line = {"start": 0, "end": 2, "text": "今天天气不错"}
    assert build_ass([dict(line)], preset) == build_ass(
        [{**line, "span_emotions": [(4, 6, "angry")]}], preset
    )
