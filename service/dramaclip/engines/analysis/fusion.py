"""OCR×ASR 文本融合：整集一次内容对齐 → 一条字幕 = 一行 → 时间取字幕驻留窗。

分工由 ep1 207 字人工标注实测决定，不是「谁更可信」的口头偏好：
- 文本：ASR。两通道分歧时 ASR 独对 12.1%、OCR 独对 5.8%（2:1），纯 ASR CER 11.1%
  对纯 OCR 抄写 41.5%；OCR 的字形误读（崇桢/蛙虫/枚势滔失）根本不是汉语词，语音
  通道的错是同音字——后者保留词形，人工一眼可辨。
- 时间与分行：OCR。paraformer 这类 VAD 连续语音引擎整集只出几条巨段，句级边界
  只能来自字幕条驻留窗。
- 置信度不参与裁决：paraformer 无字级概率（WordSpan 默认 1.0，633/633 实测恒等），
  靠概率翻案的判据形同虚设；RapidOCR 条置信中位数 0.758，也分不出对错。

分行必须由**整集一次**的内容对齐决定，不能逐段各干各的：ASR 字级戳是把整段时长
均分的插值（真机 seg2 实测 1.0 s/字），与画面字幕窗对账中位差 1.98s、最大 7.75s
且方向会翻转。旧实现正是栽在两处时间判据上——①用 `seg.start±0.3` 的窗挑条，两套
时钟一错开就把邻段的条连文本一起搬过来；②用条的时间窗在字流里下刀，刀口劈开词
（真机「大明两」「权势滔天贪」「生我比」）。这里改成：条只决定「字落在哪一行」，
行时间直接取条窗——驻留窗互不重叠（#117 在 OCR 侧修好并单测守住），行重叠从此不可能
出现；本模块不再二次钳制时间，窗若回退成重叠，这里会照抄，防线守在上游那条单测上。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from dramaclip.engines.analysis.models import AsrSegment, OcrSegment, WordSpan

_LOGGER = logging.getLogger(__name__)

_PUNCT = set("，。！？、：；“”‘’…—，")
_REVIEW_DIST = 2  # 行内对不上的字数（错配+无佐证+吞下的误读字）：单字差多是字形误读


@dataclass(frozen=True)
class _Unit:
    """ASR 字流单元：一个字、它在原文里后随的标点、归属的段与原词。"""

    char: str
    post: str
    seg: int
    word: WordSpan


@dataclass
class _Line:
    """一条字幕的对账：exact>0 才有资格成为面板行（业主裁定「无佐证条删除」）。"""

    exact: int = 0
    mismatch: int = 0
    extras: int = 0
    swallowed: int = 0  # 本行吞下的「被无佐证条咬着」的语音字数
    units: list[int] = field(default_factory=list)


@dataclass
class _Align:
    """整集对齐现场：两侧字流、逐格配对、逐条对账。"""

    cells: list[tuple[int | None, int | None]]
    ocr: list[str]
    line_of: list[int]
    units: list[_Unit]
    runs: list[list[OcrSegment]]
    segments: list[AsrSegment]
    lines: list[_Line]
    sizes: dict[int, int]

    @property
    def claimable(self) -> list[int]:
        return [index for index, line in enumerate(self.lines) if line.exact]

    def row(self, index: int) -> AsrSegment:
        run = self.runs[index]
        picked = self.lines[index].units
        line = self.lines[index]
        first = self.segments[self.units[picked[0]].seg]
        filled = self._covers_one_segment(picked) and line.extras > 0
        return AsrSegment(
            start=round(min(bar.start for bar in run), 3),
            end=round(max(bar.end for bar in run), 3),
            text=self._text(index, picked, fill=filled),
            speaker=first.speaker,
            emotion=first.emotion,
            words=self._words(picked),
            source=self._source(line, filled=filled),
        )

    def _covers_one_segment(self, picked: list[int]) -> bool:
        """补字闸：只有「整段语音落在同一条字幕上」才允许把 OCR 多出的字放进面板。

        拆出来的行只覆盖巨段的一截，此时条边界的多余字必然是误读或邻条字（真机
        「我穿成崇桢帝」的桢/帝）——放进来就是把 41.5% CER 那个老病灌回面板。
        """
        owners = {self.units[index].seg for index in picked}
        return len(owners) == 1 and len(picked) == self.sizes[next(iter(owners))]

    def _text(self, index: int, picked: list[int], *, fill: bool) -> str:
        """按配对顺序拼行：有佐证的位恒取 ASR 字，补字闸开着才插无配对的 OCR 字。"""
        owned = set(picked)
        out: list[str] = []
        for oi, ai in self.cells:
            if ai is not None and ai in owned:
                out.append(self.units[ai].char + self.units[ai].post)
            elif oi is not None and ai is None and fill and self.line_of[oi] == index:
                out.append(self.ocr[oi])
        return "".join(out)

    def _words(self, picked: list[int]) -> list[WordSpan]:
        """行只带自己那些字归属的原词（相邻同词去重）：整段 words 复制到会污染台词保护窗。"""
        words: list[WordSpan] = []
        for index in picked:
            word = self.units[index].word
            if not words or words[-1] is not word:
                words.append(word)
        return words

    def _source(self, line: _Line, *, filled: bool) -> str | None:
        if filled:
            return "ocr_fixed"
        distance = line.mismatch + line.extras + line.swallowed
        return "review" if distance >= _REVIEW_DIST else None


def fuse(
    asr_segments: list[AsrSegment],
    ocr_segments: list[OcrSegment],
) -> list[AsrSegment]:
    """融合主入口：返回逐字幕条成行的段列表（文本取 ASR，时间取条窗）。"""
    runs = _dwell_runs(ocr_segments)
    units = _char_units(asr_segments)
    if units is None:
        _LOGGER.warning(
            "融合回落纯 ASR：%d 条转写段的字级戳与文本对不上，未做整集对齐（分行/时间未取字幕窗）",
            len(asr_segments),
        )
        return asr_segments
    if not runs or not units:
        return asr_segments
    ocr, line_of = _flatten(runs)
    cells = _needleman_wunsch(ocr, [unit.char for unit in units])
    align = _Align(
        cells=cells,
        ocr=ocr,
        line_of=line_of,
        units=units,
        runs=runs,
        segments=asr_segments,
        lines=[_Line() for _ in runs],
        sizes=_segment_sizes(units),
    )
    _tally(align)
    claimed = set(align.claimable)
    if not claimed:
        _LOGGER.warning(
            "融合回落纯 ASR：%d 条字幕无一获得逐字佐证（OCR %d 字 vs 转写 %d 字对不上），"
            "面板按转写段显示，请人工核对识别链路",
            len(runs),
            len(ocr),
            len(units),
        )
        return asr_segments
    _assign_units(align, claimed)
    return [align.row(index) for index in sorted(claimed)]


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


def _flatten(runs: list[list[OcrSegment]]) -> tuple[list[str], list[int]]:
    """条文本按时间序摊成字流，并记住每个字属于哪一条。"""
    chars: list[str] = []
    line_of: list[int] = []
    for index, run in enumerate(runs):
        for char in _content(run[0].text):
            chars.append(char)
            line_of.append(index)
    return chars, line_of


def _char_units(segments: list[AsrSegment]) -> list[_Unit] | None:
    """ASR 字流：逐字单元加原位标点；任一段的字数与文本对不上就不产流（整集回落）。

    字流只认文本侧：词戳与文本谁多谁少都是坏数据，硬塞进对齐就会在面板上丢字或凭空
    造字（真机守卫收口：旧条件放行了「文本空、词戳有字」的段，面板行成了「你好凭空」）。
    """
    units: list[_Unit] = []
    for index, seg in enumerate(segments):
        stream = [(word, char) for word in seg.words for char in _content(word.word)]
        marks = _marks(seg.text)
        if len(stream) != len(marks):
            return None
        for position, (word, char) in enumerate(stream):
            units.append(_Unit(char=char, post=marks[position][1], seg=index, word=word))
    return units


def _marks(text: str) -> list[tuple[str, str]]:
    """段文本拆成 (内容字, 后随标点串)：标点不进对齐流，拼行时按原位回插。"""
    out: list[list[str]] = []
    for char in text:
        if char in _PUNCT:
            if out:
                out[-1][1] += char
        elif not char.isspace():
            out.append([char, ""])
    return [(item[0], item[1]) for item in out]


def _content(text: str) -> list[str]:
    """参与对齐的字符：标点与空白两侧都不进字流（OCR 上游已去标点，此处对称兜住）。"""
    return [char for char in text if char not in _PUNCT and not char.isspace()]


def _segment_sizes(units: list[_Unit]) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for unit in units:
        sizes[unit.seg] = sizes.get(unit.seg, 0) + 1
    return sizes


def _tally(align: _Align) -> None:
    """逐格记账：每条数出逐字相同/字形分歧/语音无佐证的 OCR 字（谁有资格成行看这里）。"""
    for oi, ai in align.cells:
        if oi is None:
            continue
        line = align.lines[align.line_of[oi]]
        if ai is None:
            line.extras += 1
        elif align.ocr[oi] == align.units[ai].char:
            line.exact += 1
        else:
            line.mismatch += 1


def _assign_units(align: _Align, claimed: set[int]) -> None:
    """逐字定行：配对咬在有佐证条上的字归那条，其余一律回挂前一条；行首孤字前挂第一条。

    无佐证的条在配对里可能正咬着这些字（「枚势滔失蛙虫」咬住「祯皇帝如何再」），但它
    不产行——字属于语音侧，跟着前一条走才不会把词劈开（真机「权势滔天贪」的下刀位）。
    吞进来多少字要记在**这一行**上：面板给人看的是行，分歧只记在不成行的条上就等于没刷。
    """
    known = -1
    for oi, ai in align.cells:
        if ai is None:
            continue
        bar = align.line_of[oi] if oi is not None else None
        if bar is not None and bar in claimed:
            known = bar
        # known 停在上一条：无佐证条咬住的字、条间隙里的字都回挂它；行首孤字前挂第一条
        owner = known if known >= 0 else min(claimed)
        align.lines[owner].units.append(ai)
        if bar is not None and bar != owner:  # 这条字原本被无佐证的误读条咬着
            align.lines[owner].swallowed += 1


def _needleman_wunsch(
    ocr: list[str], asr: list[str]
) -> list[tuple[int | None, int | None]]:
    """整集字级对齐（匹配 +1、错配/缺口 -1），回溯成 (ocr 下标, asr 下标) 配对序列。"""
    n, m = len(ocr), len(asr)
    gap = -1
    score = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            score[i][j] = max(
                score[i - 1][j - 1] + (1 if ocr[i - 1] == asr[j - 1] else gap),
                score[i - 1][j] + gap,
                score[i][j - 1] + gap,
            )
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            hit = score[i - 1][j - 1] + (1 if ocr[i - 1] == asr[j - 1] else gap)
            if score[i][j] == hit:
                pairs.append((i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and score[i][j] == score[i - 1][j] + gap:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs
