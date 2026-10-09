"""fusion：OCR×ASR 对齐与冲突消解（ASR 文本主干，OCR 供驻留窗与补字）。

判据来源：ep1 207 字人工标注实测——现行「默认信 OCR」产出 CER 41.5%，纯 ASR 11.1%；
两通道分歧时 ASR 独对 12.1% vs OCR 独对 5.8%（2:1），且 RapidOCR 无可用字级置信
（paraformer 字概率恒 1.0，翻案线形同虚设）。故 OCR 不得改写 ASR 已有字。
"""

from __future__ import annotations

from dramaclip.engines.analysis.fusion import fuse
from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan


def _seg(text: str, start: float = 10.0, end: float = 14.0) -> AsrSegment:
    """构造带字级时间戳的 ASR 段（每字 0.4s 均布）。"""
    words = [
        WordSpan(start=start + i * 0.4, end=start + (i + 1) * 0.4, word=c)
        for i, c in enumerate(text.replace("，", "").replace("。", ""))
    ]
    return AsrSegment(start=start, end=end, text=text, words=words)


def test_homophone_mismatch_keeps_asr_text() -> None:
    """整名分歧：文本仍是 ASR 读法（OCR 不得改写），但刷 review 交人工定夺。"""
    seg = _seg("古庭臣，你到底是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].text == "古庭臣，你到底是谁"
    assert result[0].source == "review"


def test_identical_text_keeps_original() -> None:
    seg = _seg("顾霆琛，你到底是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    assert fuse([seg], ocr)[0] is seg


def test_ocr_fills_asr_gaps() -> None:
    """短段 ASR 漏字（BGM/气声）：OCR 补字并标 ocr_fixed——补的是无音频佐证的字。"""
    seg = _seg("你是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].text == "顾霆琛你是谁"
    assert result[0].source == "ocr_fixed"


def test_glyph_noise_does_not_reach_the_panel() -> None:
    """单字级字形分歧不刷徽标：真机上它会命中大半面板，等于没有信号。"""
    seg = _seg("敛财无度的东厂提督")
    ocr = [OcrSegment(start=9.8, end=14.2, text="敛财无度的东昌提督", conf=0.7)]
    assert fuse([seg], ocr)[0] is seg


def test_phrase_level_divergence_marks_review() -> None:
    """连续 ≥2 字分歧 = 两通道对「短语」都读不到一起 → 标 review 交人工。"""
    seg = _seg("就是杀了大明两大权贵")
    ocr = [OcrSegment(start=9.8, end=14.2, text="就是沙了大明两大蛙虫", conf=0.9)]
    result = fuse([seg], ocr)
    assert result[0].text == "就是杀了大明两大权贵", "文本仍取 ASR"
    assert result[0].source == "review"


def test_asr_only_covers_untouched() -> None:
    seg = _seg("旁白内容没有字幕", start=20.0, end=24.0)
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    assert fuse([seg], ocr)[0] is seg


def test_no_words_returns_untouched() -> None:
    seg = AsrSegment(start=10.0, end=14.0, text="无字级时间戳的旧数据")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛", conf=0.95)]
    assert fuse([seg], ocr) == [seg]


def test_empty_ocr_returns_untouched() -> None:
    seg = _seg("顾霆琛你是谁")
    assert fuse([seg], []) == [seg]


def test_multi_char_asr_words_no_duplication() -> None:
    """whisper 词是多字 token：与 OCR 单字对齐不得产出叠字（真机实证缺陷）。"""
    words = [
        WordSpan(start=10.0, end=10.7, word="你是", probability=0.95),
        WordSpan(start=10.7, end=11.0, word="谁", probability=0.12),
    ]
    seg = AsrSegment(start=10.0, end=11.0, text="你是谁", words=words)
    ocr = [OcrSegment(start=9.8, end=11.2, text="你是谁", conf=0.66)]
    assert fuse([seg], ocr)[0] is seg, "对齐结果与原文一致 → 段保留，不得叠字"


def _long_seg(start: float, end: float, text: str) -> AsrSegment:
    """构造长巨段（每字 1s 均布时间戳，模拟 paraformer 的 VAD 连续输出）。"""
    step = (end - start) / len(text)
    words = [
        WordSpan(start=start + i * step, end=start + (i + 1) * step, word=c)
        for i, c in enumerate(text)
    ]
    return AsrSegment(start=start, end=end, text=text, words=words)


def _bars(text: str, t0: float, t1: float) -> list[OcrSegment]:
    """一个驻留窗内的多条同文本帧读数。"""
    return [
        OcrSegment(start=t0, end=t1, text=text, conf=0.9) for _ in range(2)
    ]


def test_mega_segment_splits_at_text_changes() -> None:
    """OCR 主导巨段按字幕驻留窗拆回句级粒度（业主实测：92s 巨段吞掉 74 条）。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇桢", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [r.start for r in result] == [10.0, 14.0, 18.0]
    assert len(result) == 3


def test_mega_segment_text_comes_from_asr() -> None:
    """巨段拆分只借 OCR 的时间窗，文本取窗内 ASR 字——真机 82% 行是逐字抄字幕条。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇桢", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇", "祯皇帝如", "何再造大明"]


def test_mega_segment_does_not_adopt_window_edge_ocr_chars() -> None:
    """巨段窗边界的 OCR 多余字不采信：ASR 字流是连续的，多出的是误读或邻窗字。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇桢帝", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert "桢" not in "".join(r.text for r in result)


def test_mega_segment_pieces_carry_only_their_own_words() -> None:
    """拆段后各片只带窗内字级时间戳：全段 words 复制到会污染下游台词保护窗。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("祯皇帝如", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [len(r.words) for r in result] == [4, 4, 5]


def test_mega_segment_run_without_asr_evidence_falls_back_to_ocr() -> None:
    """巨段里某窗 ASR 一字没有（静音却有字幕）：整行无语音佐证，只能留 OCR 并标 ocr_fixed。"""
    words = [
        WordSpan(start=10.0 + i, end=11.0 + i, word=c) for i, c in enumerate("我穿成崇")
    ]
    seg = AsrSegment(start=10.0, end=23.0, text="我穿成崇", words=words)
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇", "皇帝如可", "何再造大明"]
    assert [r.source for r in result] == [None, "ocr_fixed", "ocr_fixed"]


def test_mega_segment_tail_after_last_subtitle_survives() -> None:
    """末窗之后还在说的话（旁白没有字幕）：单独成条，不许随逐窗取字一起丢掉。"""
    seg = _long_seg(10.0, 24.0, "我穿成崇祯皇帝如何再造大明啊")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("祯皇帝如", 14.0, 18.0)
        + _bars("何再造大", 18.0, 22.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇", "祯皇帝如", "何再造大", "明啊"]
    assert result[-1].start == 22.0 and result[-1].end == 24.0


def test_mega_segment_overlapping_windows_do_not_duplicate_chars() -> None:
    """驻留窗时间重叠（真机 5.5-7.0 与 6.5-8.0 就是）：字必须划分，不得两窗各取一遍。"""
    seg = _long_seg(10.0, 19.0, "我穿成崇祯皇帝如")
    bars = (
        _bars("我穿成崇桢", 10.0, 15.0)
        + _bars("皇帝如", 14.0, 19.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇祯", "皇帝如"]
    assert "".join(r.text for r in result) == "我穿成崇祯皇帝如"


def test_short_segment_keeps_legacy_alignment() -> None:
    """短段（时长 < 巨段线）维持整段逐字对齐 + 标点回插——拆分只针对巨段。"""
    seg = _seg("古庭臣，你到底是谁")
    ocr = [
        OcrSegment(start=9.8, end=11.8, text="古庭臣你", conf=0.95),
        OcrSegment(start=12.0, end=14.2, text="到底是谁", conf=0.95),
    ]
    assert fuse([seg], ocr)[0] is seg
