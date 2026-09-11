"""OCR×ASR 文本融合：时间窗聚合 → 序列对齐 → 冲突消解决策表。

硬字幕是人工校对文本（视觉金标准），ASR 覆盖旁白/画外音/无字幕段。
融合规则（docs/06-经验参数表 §7）：
- 双通道一致 → 直接采用；
- 不一致 → 默认信 OCR；仅当 ASR 字概率 ≥0.92 且 OCR 置信 <0.75 时翻案；
- 仅 OCR 有（BGM 段/气声）→ OCR；仅 ASR 有（旁白/无字幕）→ ASR；
- 双低置信 → 标记 review，进工作台人工复核。
"""

from __future__ import annotations

from dataclasses import dataclass

from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan

_WINDOW_S = 0.3          # OCR 条时间窗向外扩展（采样与时间轴误差容差）
_ASR_WIN_PROB = 0.92     # ASR 字概率翻案线
_OCR_RISK_CONF = 0.75    # OCR 置信风险线（低于才允许 ASR 翻案）
_PUNCT = set("，。！？、：；“”‘’…—，")  # 标点不进字级对齐，裁决后按原位回插


@dataclass(frozen=True)
class _AlignedCell:
    """对齐单元：ocr 字（可空）与 asr 字（可空）配对。"""

    ocr: str | None
    asr: WordSpan | None
    ocr_conf: float = 1.0


def fuse(
    asr_segments: list[AsrSegment],
    ocr_segments: list[OcrSegment],
) -> list[AsrSegment]:
    """融合主入口：返回与 asr_segments 同构的新段列表（text/source 已按决策表改写）。

    OCR 条按「条中点落在段区间内」归属到唯一 ASR 段（防止相邻条跨段串文本）；
    与 OCR 无交集的 ASR 段原样保留（source=None）。
    """
    if not ocr_segments:
        return asr_segments
    if not any(seg.words for seg in asr_segments):
        return asr_segments
    fused: list[AsrSegment] = []
    for seg in asr_segments:
        assigned = [
            ocr
            for ocr in ocr_segments
            if seg.start - _WINDOW_S <= (ocr.start + ocr.end) / 2 <= seg.end + _WINDOW_S
        ]
        if not assigned:
            fused.append(seg)
            continue
        fused.extend(_fuse_segment(seg, assigned))
    return fused


def _fuse_segment(
    seg: AsrSegment, ocr_hits: list[OcrSegment]
) -> list[AsrSegment]:
    """单段融合：OCR 条按时间序与该段字序列做 Needleman-Wunsch 对齐后逐字裁决。"""
    span = (
        min(o.start for o in ocr_hits) - _WINDOW_S,
        max(o.end for o in ocr_hits) + _WINDOW_S,
    )
    hit_words = [w for w in seg.words if span[0] <= (w.start + w.end) / 2 <= span[1]]
    if not hit_words:
        return [seg]
    # 词炸成单字单元：whisper 词是多字的（"你是"=1 词），与 OCR 单字粒度对齐
    # 不一致时 NW 会走出"OCR 补字 + ASR 整词赢回"的叠字路径（真机实证）
    chars = [
        WordSpan(start=w.start, end=w.end, word=ch, probability=w.probability)
        for w in hit_words
        for ch in w.word
    ]
    lines = "".join(o.text for o in sorted(ocr_hits, key=lambda o: o.start)).replace(" ", "")
    ocr_conf = sum(o.conf for o in ocr_hits) / len(ocr_hits)  # 条置信均值为该段 OCR 置信
    ocr_chars = [c for c in lines]
    aligned = _needleman_wunsch(ocr_chars, chars)
    out = [
        _AlignedCell(ocr=ocr_char, asr=asr_word, ocr_conf=ocr_conf)
        for ocr_char, asr_word in aligned
    ]
    return _resolve(seg, out)


def _resolve(seg: AsrSegment, cells: list[_AlignedCell]) -> list[AsrSegment]:
    """逐字裁决：决策表见模块 docstring。输出 1~2 段（对齐区间 + 区间外原文）。"""
    chars: list[str] = []
    review = False
    for cell in cells:
        if cell.ocr is not None and cell.asr is not None:
            if cell.ocr == cell.asr.word:
                chars.append(cell.ocr)
            elif cell.asr.probability >= _ASR_WIN_PROB and cell.ocr_conf < _OCR_RISK_CONF:
                chars.append(cell.asr.word)  # OCR 存疑（艺术字/遮挡），高置信 ASR 翻案
            else:
                chars.append(cell.ocr)  # 默认信 OCR（人工校对文本）
                if cell.ocr_conf < _OCR_RISK_CONF:
                    review = True  # OCR 低置信且 ASR 不足以翻案：分歧无法裁决
        elif cell.ocr is not None:
            chars.append(cell.ocr)  # ASR 漏字（BGM/气声）→ OCR 补
        elif cell.asr is not None:
            chars.append(cell.asr.word)  # OCR 无对应（旁白）→ ASR
    text_chars = "".join(chars).strip()
    if not text_chars:
        return [seg]
    stripped = "".join(c for c in seg.text if c not in _PUNCT).strip()
    if text_chars == stripped:
        return [seg]
    text = _reinsert_punctuation(seg.text, text_chars)
    start = min((c.asr.start for c in cells if c.asr), default=seg.start)
    end = max((c.asr.end for c in cells if c.asr), default=seg.end)
    return [
        AsrSegment(
            start=round(min(start, seg.start), 3),
            end=round(max(end, seg.end), 3),
            text=text,
            speaker=seg.speaker,
            emotion=seg.emotion,
            words=seg.words,
            source="review" if review else "ocr_fixed",
        )
    ]


def _reinsert_punctuation(original: str, fused: str) -> str:
    """裁决字流按原文本的标点位置重建（字数一致时标点完全复原）。"""
    out: list[str] = []
    index = 0
    for char in original:
        if char in _PUNCT:
            out.append(char)
        elif index < len(fused):
            out.append(fused[index])
            index += 1
    out.extend(fused[index:])  # OCR 补漏字多出的部分接在尾部
    return "".join(out)


def _needleman_wunsch(
    ocr_chars: list[str], asr_words: list[WordSpan]
) -> list[tuple[str | None, WordSpan | None]]:
    """字级序列对齐（编辑距离打分：匹配 +1，错配/缺口 -1），回溯出配对序列。"""
    n, m = len(ocr_chars), len(asr_words)
    gap = -1
    score = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = score[i - 1][j - 1] + (1 if ocr_chars[i - 1] == asr_words[j - 1].word else gap)
            score[i][j] = max(match, score[i - 1][j] + gap, score[i][j - 1] + gap)
    pairs: list[tuple[str | None, WordSpan | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            match = score[i - 1][j - 1] + (1 if ocr_chars[i - 1] == asr_words[j - 1].word else gap)
            if score[i][j] == match:
                pairs.append((ocr_chars[i - 1], asr_words[j - 1]))
                i, j = i - 1, j - 1
                continue
        if i > 0 and score[i][j] == score[i - 1][j] + gap:
            pairs.append((ocr_chars[i - 1], None))
            i -= 1
        else:
            pairs.append((None, asr_words[j - 1]))
            j -= 1
    pairs.reverse()
    return pairs
