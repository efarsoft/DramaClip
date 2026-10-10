"""fusion：OCR×ASR 融合（ASR 文本主干；一条字幕 = 一行；时间取字幕驻留窗）。

判据来源：ep1 207 字人工标注实测——「默认信 OCR」的文本 CER 41.5%，纯 ASR 11.1%；
两通道分歧时 ASR 独对 12.1% vs OCR 独对 5.8%（2:1），RapidOCR 的字形误读（崇桢/蛙虫/
枚势滔失）根本不是汉语词。故 OCR 一个字也不许改写 ASR 已有字，只提供分行、时间与
无语音处的补字。

分行必须由**整集一次**的内容对齐决定：ASR 字级戳是把整段均分出来的插值（真机 seg2
实测 1.0 s/字），与画面字幕窗对账中位差 1.98s、最大 7.75s 且方向会翻转——用时间去挑
条、用时间去下刀，刀口就会劈开词（真机「大明两」「权势滔天贪」「生我比」）。
"""

from __future__ import annotations

from dramaclip.engines.analysis.fusion import fuse
from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan


def _seg(text: str, start: float = 10.0, end: float = 14.0) -> AsrSegment:
    """构造带字级时间戳的 ASR 段（每字 0.4s 均布，标点不进字级流）。"""
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


def test_row_time_follows_the_subtitle_window() -> None:
    """行时间以字幕驻留窗为准：源字幕在屏幕上那一段必须被覆盖到（#117 后条窗互不重叠）。"""
    seg = _seg("顾霆琛，你到底是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].text == "顾霆琛，你到底是谁"
    assert (result[0].start, result[0].end) == (9.8, 14.2)
    assert result[0].source is None


def test_ocr_fills_asr_gaps() -> None:
    """整句只有一条字幕且 ASR 漏字（BGM/气声）：OCR 补字并标 ocr_fixed。"""
    seg = _seg("你是谁")
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你是谁", conf=0.95)]
    result = fuse([seg], ocr)
    assert result[0].text == "顾霆琛你是谁"
    assert result[0].source == "ocr_fixed"


def test_fill_never_adopts_a_neighbour_bars_chars() -> None:
    """补字只认「本行自己那条」多出的字：邻条（无人佐证的重读/别句字幕）一个字也不掺。"""
    seg = _seg("你是谁", start=10.0, end=11.0)
    bars = _bars("顾霆琛你是谁", 9.8, 11.8) + _bars("下一句的字幕", 12.0, 14.2)
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["顾霆琛你是谁"]


def test_glyph_noise_does_not_reach_the_panel() -> None:
    """单字级字形分歧不刷徽标：真机上它会命中大半面板，等于没有信号。"""
    seg = _seg("敛财无度的东厂提督")
    ocr = [OcrSegment(start=9.8, end=14.2, text="敛财无度的东昌提督", conf=0.7)]
    result = fuse([seg], ocr)
    assert result[0].text == "敛财无度的东厂提督"
    assert result[0].source is None


def test_phrase_level_divergence_marks_review() -> None:
    """两通道累计读到 ≥2 字对不上 = 整短语读不到一起 → 标 review 交人工。"""
    seg = _seg("就是杀了大明两大权贵")
    ocr = [OcrSegment(start=9.8, end=14.2, text="就是沙了大明两大蛙虫", conf=0.9)]
    result = fuse([seg], ocr)
    assert result[0].text == "就是杀了大明两大权贵", "文本仍取 ASR"
    assert result[0].source == "review"


def test_two_chars_is_the_review_floor() -> None:
    """复核线的下界钉死在 2：一字是 OCR 字形误读，两字才叫读不到一起。

    真机旧实现按连续长度刷出 54% 待复核行（等于没有信号）；把线抬到 3 就会漏掉
    「权贵/蛙虫」这类整词被读歪的行——那种恰恰是人名地名，最需要人看。
    """
    seg = _seg("杀了大明两大权贵")
    ocr = [OcrSegment(start=9.8, end=14.2, text="杀了大明两大蛙虫", conf=0.9)]
    assert fuse([seg], ocr)[0].source == "review"


def test_unmatched_ocr_chars_count_toward_review() -> None:
    """条里多出的字（语音侧无佐证）与错字同秤：一行的分歧数是两侧合计。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = _bars("我穿成崇啊啊", 10.0, 14.0) + _bars("祯皇帝如何再造大明", 14.0, 23.0)
    result = fuse([seg], bars)
    assert result[0].text == "我穿成崇", "多余字不进面板（补字闸关着）"
    assert result[0].source == "review", "两处无佐证的多余字 = 2 处对不上"


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


def test_unmatched_word_stream_returns_untouched() -> None:
    """字级流与段文本对不上：整集回落纯 ASR，不拿半截流去对齐（半截流会静默吞字）。"""
    seg = AsrSegment(
        start=0.0,
        end=4.0,
        text="顾霆琛你到底是谁",
        words=[WordSpan(start=0.0, end=1.0, word="你是谁")],
    )
    ocr = [OcrSegment(start=9.8, end=14.2, text="顾霆琛你到底是谁", conf=0.9)]
    assert fuse([seg], ocr) == [seg]


def test_multi_char_asr_words_no_duplication() -> None:
    """whisper 词是多字 token：与 OCR 单字对齐不得产出叠字（真机实证缺陷）。"""
    words = [
        WordSpan(start=10.0, end=10.7, word="你是", probability=0.95),
        WordSpan(start=10.7, end=11.0, word="谁", probability=0.12),
    ]
    seg = AsrSegment(start=10.0, end=11.0, text="你是谁", words=words)
    ocr = [OcrSegment(start=9.8, end=11.2, text="你是谁", conf=0.66)]
    result = fuse([seg], ocr)
    assert [r.text for r in result] == ["你是谁"]
    assert result[0].words == words, "一个词不得被复制进两行"


def _long_seg(start: float, end: float, text: str) -> AsrSegment:
    """构造长巨段（每字均布时间戳，模拟 paraformer 的 VAD 连续输出）。"""
    step = (end - start) / len(text)
    words = [
        WordSpan(start=start + i * step, end=start + (i + 1) * step, word=c)
        for i, c in enumerate(text)
    ]
    return AsrSegment(start=start, end=end, text=text, words=words)


def _bars(text: str, t0: float, t1: float) -> list[OcrSegment]:
    """一个驻留窗内的多条同文本帧读数。"""
    return [OcrSegment(start=t0, end=t1, text=text, conf=0.9) for _ in range(2)]


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
    """巨段按「字落在哪一条」分行，文本仍是条内的 ASR 字——刀口不再劈开词。

    旧实现按条的时间窗下刀（1fps 采样 ±1s），把精确到字的 ASR 流切成
    「我穿成崇 / 祯皇帝如」；「崇祯」这种词中间。真机 ep1 同类病灶：「大明两」
    「权势滔天贪」「生我比」。
    """
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇桢", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇祯", "皇帝如", "何再造大明"]


def test_mega_segment_does_not_adopt_window_edge_ocr_chars() -> None:
    """巨段行边界的 OCR 多余字不采信：ASR 字流是连续的，多出的是误读或邻条字。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇桢帝", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert result[0].text == "我穿成崇祯", "条边界的桢/帝都不许进行"
    assert "ocr_fixed" not in {r.source for r in result}


def test_mega_segment_pieces_carry_only_their_own_words() -> None:
    """拆段后各行只带自己那些字的级时间戳：全段 words 复制到会污染下游台词保护窗。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("祯皇帝如", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert [len(r.words) for r in result] == [4, 4, 5]


def test_mega_segment_drops_bars_without_speech_evidence() -> None:
    """没人逐字佐证的字幕条不产出行（2026-10-10 业主裁定「无佐证条删除」）。

    真机 27 条里有 4 条是同一句字幕的第二、三种误读（「推他的皇爷早就已经换了一个人」
    「他的皇节早就包经换了一个人」）——语音侧的字早已落在别条上，这几条一字未获佐证。
    留着等于把 CER 41.5% 那个「逐字抄字幕条」的老病重新灌回面板。
    """
    words = [
        WordSpan(start=10.0 + i, end=11.0 + i, word=c) for i, c in enumerate("我穿成崇")
    ]
    seg = AsrSegment(start=10.0, end=23.0, text="我穿成崇", words=words)
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("皇帝如可", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    assert [r.text for r in fuse([seg], bars)] == ["我穿成崇"]


def test_cut_segment_never_inherits_an_unclaimed_bar() -> None:
    """拆行时也不许把没人佐证条的文本掺进行里：一个字不丢、一个字不掺。"""
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("枚势滔失蛙虫", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert "".join(r.text for r in result) == "我穿成崇祯皇帝如何再造大明"
    assert "ocr_fixed" not in {r.source for r in result}


def test_row_swallowing_a_misread_bar_is_reviewed() -> None:
    """吞下无佐证条的字要计入**这一行**的分歧距离：徽标是给人看行的，只记在条上等于没刷。

    真机 ep1 实测形状（2026-10-10 审查）：「我穿成崇」有佐证成行，「枚势滔失蛙虫」无佐证
    被删，但它咬住的「祯皇帝如何再」整串回挂进前一行——那一行自有分歧只 1 字，按条记账
    不带徽标，于是面板上一行掺着整条误读的字却告诉人工「不用看」。
    """
    seg = _long_seg(10.0, 23.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("枚势滔失蛙虫", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert result[0].source == "review", "吞了整条误读的行必须交人工"


def test_textless_segment_with_word_stamps_falls_back_whole_episode() -> None:
    """文本侧一个字没有、词戳侧却有字：坏数据，整集回落——字流只认文本，凭空造字比少分行更坏。

    `if not paced and marks` 的旧守卫只看「文本有没有内容字」，文本空时直接放行：
    词戳里的字照样进对齐流，面板于是多出文本侧从未存在过的字。
    """
    good = _seg("你好")
    bad = AsrSegment(
        start=12.0,
        end=16.0,
        text="",
        words=[
            WordSpan(start=12.0, end=13.0, word="凭"),
            WordSpan(start=13.0, end=14.0, word="空"),
        ],
    )
    result = fuse([good, bad], _bars("你好", 9.8, 12.0))
    assert result == [good, bad], "整集回落到未融合的 ASR 段：词戳侧的字不许上面板"


def test_head_orphans_attach_forward_to_the_first_claimed_row() -> None:
    """第一条字幕出现之前就在说的话（片头旁白）：前挂第一条，一个字不丢。"""
    seg = _long_seg(0.0, 12.0, "开场白没有字幕我说的是你")
    bars = _bars("我说的是你", 8.0, 12.0)
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["开场白没有字幕我说的是你"]


def test_mega_segment_tail_after_last_subtitle_survives() -> None:
    """末条之后还在说的话（旁白没有字幕）：回挂最后一条，不许丢字。"""
    seg = _long_seg(10.0, 24.0, "我穿成崇祯皇帝如何再造大明啊")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("祯皇帝如", 14.0, 18.0)
        + _bars("何再造大", 18.0, 22.0)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇", "祯皇帝如", "何再造大明啊"]
    assert (result[-1].start, result[-1].end) == (18.0, 22.0)


def test_mega_segment_overlapping_windows_do_not_duplicate_chars() -> None:
    """两条时间交叠时字仍须划分，不得两窗各取一遍。

    #117 之后上游不再产交叠驻留窗；本行按内容归属划分，留着防回归。
    """
    seg = _long_seg(10.0, 19.0, "我穿成崇祯皇帝如")
    bars = _bars("我穿成崇桢", 10.0, 15.0) + _bars("皇帝如", 14.0, 19.0)
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["我穿成崇祯", "皇帝如"]
    assert "".join(r.text for r in result) == "我穿成崇祯皇帝如"


def test_row_times_never_overlap_even_when_speech_runs_long() -> None:
    """语音跑到下一条字幕之后，行时间仍互不重叠：时间取自互不重叠的条窗，不是事后钳制。"""
    seg = _long_seg(10.0, 40.0, "我穿成崇祯皇帝如何再造大明")
    bars = (
        _bars("我穿成崇", 10.0, 14.0)
        + _bars("祯皇帝如", 14.0, 18.0)
        + _bars("何再造大明", 18.0, 23.0)
    )
    result = fuse([seg], bars)
    assert all(cur.end <= nxt.start for cur, nxt in zip(result, result[1:], strict=False))


def test_sentence_asr_still_splits_at_subtitle_boundaries() -> None:
    """句级 ASR 段跨两条字幕：照样按条拆行，标点跟着它后面那个字走（不丢不串）。"""
    seg = _seg("古庭臣，你到底是谁")
    bars = (
        _bars("古庭臣你", 9.8, 11.8)
        + _bars("到底是谁", 12.0, 14.2)
    )
    result = fuse([seg], bars)
    assert [r.text for r in result] == ["古庭臣，你", "到底是谁"]
    assert [(r.start, r.end) for r in result] == [(9.8, 11.8), (12.0, 14.2)]


def test_two_segments_on_one_subtitle_make_one_row() -> None:
    """一条 = 一行：两个 ASR 段的话落在同一条字幕上时合成一行，而不是两行同窗重叠。"""
    segs = [_long_seg(10.0, 20.0, "我穿成崇祯"), _long_seg(20.0, 30.0, "皇帝如何再造大明")]
    bars = _bars("我穿成崇祯皇帝如", 14.0, 18.0) + _bars("何再造大明", 18.0, 23.0)
    result = fuse(segs, bars)
    assert [r.text for r in result] == ["我穿成崇祯皇帝如", "何再造大明"]
    assert [(r.start, r.end) for r in result] == [(14.0, 18.0), (18.0, 23.0)]


def test_clock_disagreement_does_not_steal_a_row_from_the_wrong_segment() -> None:
    """ASR 字戳与画面差 7s（真机实测中位 1.98s、最大 7.75s）：归属只由内容决定。

    旧实现用 `seg.start±0.3` 的时间窗挑条，两套时钟一错开就把邻段的条塞过来，
    行时间与文本一起串到错误的语音上。
    """
    segs = [
        _long_seg(0.0, 8.0, "一个是富可敌国"),  # 画面在 17.5s 才出这句字幕
        _long_seg(8.0, 16.0, "敛财无度的东厂提督"),
    ]
    bars = (
        _bars("一个是富可敌国", 17.5, 19.5)
        + _bars("敛财无度的东昌提督", 19.5, 21.0)
    )
    result = fuse(segs, bars)
    assert [r.text for r in result] == ["一个是富可敌国", "敛财无度的东厂提督"]
    assert [(r.start, r.end) for r in result] == [(17.5, 19.5), (19.5, 21.0)]
    assert [r.source for r in result] == [None, None], "单字之差不刷徽标，也不改文本"
