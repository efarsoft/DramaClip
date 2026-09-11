"""fusion：OCR×ASR 对齐与冲突消解决策表。"""

from __future__ import annotations

from dramaclip.engines.analysis.fusion import fuse
from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan


def _seg(text: str, start: float = 10.0, end: float = 14.0) -> AsrSegment:
    """构造带字级时间戳的 ASR 段（每字 0.4s 均布，概率可按字覆盖）。"""
    probs = {"庭": 0.95, "昏": 0.95, "意": 0.95}
    words = [
        WordSpan(
            start=start + i * 0.4, end=start + (i + 1) * 0.4, word=c,
            probability=probs.get(c, 0.6),
        )
        for i, c in enumerate(text.replace("，", "").replace("。", ""))
    ]
    return AsrSegment(start=start, end=end, text=text, words=words)


def test_identical_text_keeps_original() -> None:
    seg = _seg("顾霆琛，你到底是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0] is seg, "双通道一致：段原样保留"


def test_mismatch_defaults_to_ocr() -> None:
    seg = _seg("古庭臣，你到底是谁")  # ASR 同音错字
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].text == "顾霆琛，你到底是谁"
    assert result[0].source == "ocr_fixed"


def test_high_prob_asr_wins_over_risky_ocr() -> None:
    words = [
        WordSpan(start=10 + i * 0.4, end=10 + (i + 1) * 0.4, word=c, probability=0.95)
        for i, c in enumerate("离婚协议")
    ]
    seg = AsrSegment(start=10.0, end=12.0, text="离昏协意", words=words)
    ocr = [OcrSegment(start=9.8, end=12.2, text="离昏协意", conf=0.5)]  # 字幕组自己打错
    result = fuse([seg], ocr)
    assert result[0].text == "离婚协议", "ASR 高置信 + OCR 低置信 → ASR 翻案（字幕组错字被纠正）"
    assert result[0].source == "ocr_fixed"


def test_asr_only_covers_untouched() -> None:
    seg = _seg("旁白内容没有字幕", start=20.0, end=24.0)
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0] is seg


def test_ocr_fills_asr_gaps() -> None:
    seg = _seg("你是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert "顾霆琛" in result[0].text, "BGM 段 ASR 漏字 → OCR 补齐"


def test_low_confidence_marks_review() -> None:
    seg = _seg("古庭臣你是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你是谁", conf=0.6)]
    result = fuse([seg], ocr)
    assert result[0].source == "review", "分歧双方都低置信 → 人工复核"


def test_high_conf_ocr_fix_is_not_review() -> None:
    seg = _seg("古庭臣你是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].source == "ocr_fixed", "OCR 高置信纠正同音错字 = 正常修正"


def test_no_words_returns_untouched() -> None:
    seg = AsrSegment(start=10.0, end=14.0, text="无字级时间戳的旧数据")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛", conf=0.95)]
    assert fuse([seg], ocr) == [seg]


def test_empty_ocr_returns_untouched() -> None:
    seg = _seg("顾霆琛你是谁")
    assert fuse([seg], []) == [seg]
