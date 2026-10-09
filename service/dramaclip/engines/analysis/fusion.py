"""OCR×ASR 文本融合：时间窗聚合 → 整段对齐裁决 → 按字幕驻留窗切句。

分工由 ep1 207 字人工标注实测决定，不是「谁更可信」的口头偏好：
- 文本：ASR。两通道分歧时 ASR 独对 12.1%、OCR 独对 5.8%（2:1），纯 ASR CER 11.1%
  对纯 OCR 抄写 41.5%；OCR 的字形误读（崇桢/蛙虫/枚势滔失）根本不是汉语词，语音
  通道的错是同音字——后者保留词形，人工一眼可辨。
- 时间与分行：OCR。paraformer 这类 VAD 连续语音引擎整集只出几条巨段，句级边界
  只能来自字幕条驻留窗。
- 置信度不参与裁决：paraformer 无字级概率（WordSpan 默认 1.0，633/633 实测恒等），
  靠概率翻案的判据形同虚设；RapidOCR 条置信中位数 0.758，也分不出对错。
"""

from __future__ import annotations

from dataclasses import dataclass

from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan

_WINDOW_S = 0.3          # OCR 条时间窗向外扩展（采样与时间轴误差容差）
_PUNCT = set("，。！？、：；“”‘’…—，")  # 标点不进字级对齐，裁决后按原位回插
_SPLIT_MIN_BARS = 4      # OCR 条达到此数：候选「OCR 主导巨段」
_SPLIT_MIN_DUR = 8.0     # 巨段时长下限（秒）：短段维持原有整段融合
_REVIEW_RUN = 2          # 连续分歧字数：≥此值算「短语级读不到一起」，交人工复核


@dataclass(frozen=True)
class _Stream:
    """整段裁决后的 ASR 字流：字、时间戳、归属原词、与他通道是否分歧。"""

    spans: list[WordSpan]
    owner: list[int]
    words: list[WordSpan]
    chars: list[str]
    disagreed: list[bool]
    filled: bool

    def slice(self, lo: int, hi: int) -> tuple[str, list[WordSpan], list[bool]]:
        """取 [lo, hi) 区间：文本、覆盖到的原词、逐字分歧标记。"""
        if lo >= hi:
            return "", [], []
        covered = range(self.owner[lo], self.owner[hi - 1] + 1)
        return (
            "".join(self.chars[lo:hi]).strip(),
            [self.words[i] for i in covered],
            self.disagreed[lo:hi],
        )

    @property
    def text(self) -> str:
        return "".join(self.chars).strip()


def fuse(
    asr_segments: list[AsrSegment],
    ocr_segments: list[OcrSegment],
) -> list[AsrSegment]:
    """融合主入口：返回与 asr_segments 同构的新段列表（text/source 已按分工改写）。
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
        split = len(assigned) >= _SPLIT_MIN_BARS and seg.end - seg.start >= _SPLIT_MIN_DUR
        fused.extend(_fuse_segment(seg, assigned, split=split))
    return fused


def _fuse_segment(seg: AsrSegment, bars: list[OcrSegment], *, split: bool) -> list[AsrSegment]:
    """整段对齐裁决一次，再按驻留窗切句（巨段）或整段成一条（短段）。

    对齐只做一次、覆盖整段：驻留窗本身有 ±1 字的时间模糊（1fps 采样 + 头尾 pad），
    若逐窗各自对齐，窗边界的错位会被当成「两通道分歧」——真机 ep1 实测那样刷出
    54% 的待复核行，等于没有信号。
    """
    lines = _ocr_stream(bars)
    words = seg.words if split else _words_in(
        seg.words,
        min(o.start for o in bars) - _WINDOW_S,
        max(o.end for o in bars) + _WINDOW_S,
    )
    # 词炸成单字单元：whisper 词是多字的（"你是"=1 词），与 OCR 单字粒度对齐
    # 不一致时 NW 会走出"OCR 补字 + ASR 整词赢回"的叠字路径（真机实证）
    spans: list[WordSpan] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for char in word.word:
            spans.append(WordSpan(start=word.start, end=word.end, word=char))
            owner.append(index)
    if not spans:
        # 本段 ASR 一字没有（静音却有字幕）：只能留 OCR 文本，整行标无语音佐证
        return _ocr_pieces(seg, bars) if lines else [seg]
    chars, disagreed, filled = _arbitrate(
        _needleman_wunsch(list(lines), spans), allow_fill=not split
    )
    stream = _Stream(
        spans=spans,
        owner=owner,
        words=words,
        chars=chars,
        disagreed=disagreed,
        filled=filled,
    )
    if not stream.text:
        return [seg]
    return _slice_by_runs(seg, stream, bars) if split else _whole_segment(seg, stream, bars)


def _whole_segment(seg: AsrSegment, stream: _Stream, bars: list[OcrSegment]) -> list[AsrSegment]:
    """短段：整段一条，标点按原位回插；文本与源段一致且无需复核则原样保留。"""
    review = _has_phrase_disagreement(stream.disagreed)
    stripped = "".join(c for c in seg.text if c not in _PUNCT).strip()
    if stream.text == stripped and not review:
        return [seg]
    return [
        AsrSegment(
            start=round(min(min(o.start for o in bars), seg.start), 3),
            end=round(max(max(o.end for o in bars), seg.end), 3),
            text=_reinsert_punctuation(seg.text, stream.text),
            speaker=seg.speaker,
            emotion=seg.emotion,
            words=seg.words,
            source="review" if review else ("ocr_fixed" if stream.filled else None),
        )
    ]


def _slice_by_runs(seg: AsrSegment, stream: _Stream, bars: list[OcrSegment]) -> list[AsrSegment]:
    """按字幕驻留窗切句：窗只决定「在哪里下刀」与时间轴，字流仍来自整段裁决。

    allow_fill=False 时每个 ASR 字都进字流且顺序不变（OCR 多出的字不采信），所以
    字流下标与 spans 一一对应，窗边界用字的时间戳定位——旧实现逐窗各自取字，真机
    13s 巨段丢了 7 个字。
    """
    pieces: list[AsrSegment] = []
    cursor = 0
    for run in _dwell_runs(bars):
        hi = run[-1].end + _WINDOW_S
        stop = cursor
        while stop < len(stream.spans) and _mid(stream.spans[stop]) <= hi:
            stop += 1
        piece = _make_piece(seg, stream, cursor, stop, run)
        cursor = stop
        if piece is not None:
            pieces.append(piece)
    if cursor < len(stream.spans):
        # 末窗之后仍在说的字（旁白没有字幕）：单独成条，时间取语音自己的
        tail = stream.slice(cursor, len(stream.spans))
        pieces.append(
            AsrSegment(
                start=round(tail[1][0].start, 3),
                end=round(tail[1][-1].end, 3),
                text=tail[0],
                speaker=seg.speaker,
                emotion=seg.emotion,
                words=tail[1],
                source=_piece_source(tail[1], tail[2]),
            )
        )
    return pieces


def _make_piece(
    seg: AsrSegment,
    stream: _Stream,
    lo: int,
    hi: int,
    run: list[OcrSegment],
) -> AsrSegment | None:
    """一个驻留窗成一条：窗内无字则回落该窗 OCR 文本并标 ocr_fixed（没声音对得上）。"""
    text, words, disagreed = stream.slice(lo, hi)
    if not text:
        if words:
            return None
        text = _ocr_stream(run)
        if not text:
            return None
        disagreed = []
    return AsrSegment(
        start=round(min(o.start for o in run), 3),
        end=round(max(o.end for o in run), 3),
        text=text,
        speaker=seg.speaker,
        emotion=seg.emotion,
        words=words,
        source=_piece_source(words, disagreed),
    )


def _piece_source(words: list[WordSpan], disagreed: list[bool]) -> str | None:
    """条目标记：没有 ASR 字＝整行 OCR 回落（无语音佐证）；有短语级分歧＝待人工复核。"""
    if not words:
        return "ocr_fixed"
    return "review" if _has_phrase_disagreement(disagreed) else None


def _ocr_pieces(seg: AsrSegment, bars: list[OcrSegment]) -> list[AsrSegment]:
    """无 ASR 字可用时按驻留窗逐条落 OCR 文本（全部标 ocr_fixed，语音侧无佐证）。"""
    return [
        AsrSegment(
            start=round(min(o.start for o in run), 3),
            end=round(max(o.end for o in run), 3),
            text=_ocr_stream(run),
            speaker=seg.speaker,
            emotion=seg.emotion,
            source="ocr_fixed",
        )
        for run in _dwell_runs(bars)
    ]


def _dwell_runs(bars: list[OcrSegment]) -> list[list[OcrSegment]]:
    """同文本相邻条合并为一个驻留窗（字幕在一句台词上停留多帧）。"""
    runs: list[list[OcrSegment]] = []
    for bar in sorted(bars, key=lambda o: o.start):
        text = bar.text.replace(" ", "")
        if not text:
            continue
        if runs and runs[-1][-1].text.replace(" ", "") == text:
            runs[-1].append(bar)
        else:
            runs.append([bar])
    return runs


def _mid(word: WordSpan) -> float:
    return (word.start + word.end) / 2


def _words_in(words: list[WordSpan], lo: float, hi: float) -> list[WordSpan]:
    return [w for w in words if lo <= _mid(w) <= hi]


def _ocr_stream(bars: list[OcrSegment]) -> str:
    """OCR 字流：按时间序拼条文本，相邻同读法只算一次（一句字幕跨多帧不得重复计字）。"""
    out: list[str] = []
    for bar in sorted(bars, key=lambda o: o.start):
        text = bar.text.replace(" ", "")
        if text and text != (out[-1] if out else ""):
            out.append(text)
    return "".join(out)


def _arbitrate(
    cells: list[tuple[str | None, WordSpan | None]], *, allow_fill: bool
) -> tuple[list[str], list[bool], bool]:
    """逐位裁决 → (字流, 逐字是否与 OCR 分歧, OCR 是否补过字)。

    两通道都有字时恒取 ASR 字。分歧按连续长度分档（`_has_phrase_disagreement`）：
    单字是 OCR 字形误读（桢/祯、厂/昌 这类同音/形近替换，ASR 2:1 更可能对），
    连续 ≥2 字才是两通道对整短语都读不到一起（「两大权贵/两大蛙虫」），那种才值得
    刷 review 给人看。allow_fill=False（巨段）时 OCR 多出的字一律不采：ASR 字流是
    连续的，窗内多出的字要么是误读、要么属于邻窗（真机 82% 行逐字抄字幕条的病根）。
    """
    chars: list[str] = []
    disagreed: list[bool] = []
    filled = False
    for ocr, asr in cells:
        if ocr is not None and asr is not None:
            chars.append(asr.word)
            disagreed.append(ocr != asr.word)
        elif ocr is not None:
            if allow_fill:
                chars.append(ocr)
                disagreed.append(False)
                filled = True
        elif asr is not None:
            chars.append(asr.word)
            disagreed.append(False)
    return chars, disagreed, filled


def _has_phrase_disagreement(disagreed: list[bool]) -> bool:
    streak = 0
    for flag in disagreed:
        streak = streak + 1 if flag else 0
        if streak >= _REVIEW_RUN:
            return True
    return False


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
