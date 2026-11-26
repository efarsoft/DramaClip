"""解说字幕的行时间：词界对齐取真实词时，外加最短可读停留。

切行只有一套（`split_subtitle_spans`：标点断句那一套），有词界 cue 与没有的两条
路径共用——行文逐字相同，区别只在时间从哪来：

· 有词界 cue（配音旁的 .cues.json）：行起于行首字所在词的起点，止于行尾字所在词
  的终点，字幕跟着实际念出来的字走；
· 没有 cue（indextts2 / kokoro 等引擎、旧缓存）：按字数比例分配。

最短可读停留两条路径都做：先只延末点，末点没有空间再向前一行借。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from dramaclip.engines.subtitle.ass_generator import split_subtitle_spans

#: 一行字幕至少亮多久才算读得过来。中文口播一秒四五字，两三字的行自然时长只有
#: 零点几秒，一闪而过。
MIN_DISPLAY_S = 0.8
#: 延末点不许压到下一行上：相邻两行之间留的空隙。
LINE_GAP_S = 0.08


@dataclass(frozen=True)
class TimedLine:
    start: float
    end: float
    text: str


def align_cues(text: str, cues: list[Any]) -> list[tuple[int, int, float, float]] | None:
    """把词界 token 逐个对回解说原文，返回每个词的 (原文起, 原文止, 起秒, 止秒)。

    配音服务的词界文本不带标点、还可能在词中间断开（实测「六千六百六｜十六都」），
    所以 token 自己当不了字幕；对回原文才知道每一行从哪个字开始、到哪个字结束。
    token 之间只许隔着标点和空白：原文里还有没被念到的字、或 token 与原文对不上
    （数字被念成别的写法），整体作废，调用方回退按字数比例。
    """
    pos = 0
    aligned: list[tuple[int, int, float, float]] = []
    for cue in cues:
        if not isinstance(cue, dict):
            return None
        token = str(cue.get("text") or "")
        if not token:
            continue
        while pos < len(text) and not text.startswith(token, pos):
            if text[pos].isalnum():
                return None
            pos += 1
        if pos >= len(text):
            return None
        try:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or 0.0)
        except (TypeError, ValueError):
            return None
        aligned.append((pos, pos + len(token), start, max(start, end)))
        pos += len(token)
    if any(ch.isalnum() for ch in text[pos:]):
        return None
    return aligned or None


def lines_from_cues(text: str, cues: list[Any], cap: int) -> list[TimedLine] | None:
    """词界路径：切行走原文同一套，每行的时间取自它盖住的那些词。"""
    words = align_cues(text, cues)
    if words is None:
        return None
    lines: list[TimedLine] = []
    index = 0
    for start, stop in split_subtitle_spans(text, cap):
        while index < len(words) and words[index][1] <= start:
            index += 1
        first = index
        while index < len(words) and words[index][0] < stop:
            index += 1
        if index > first:
            lines.append(TimedLine(words[first][2], words[index - 1][3], text[start:stop]))
    return lines or None


def lines_by_share(text: str, cap: int, duration_s: float) -> list[TimedLine]:
    """回退路径：没有词界 cue，行时间按字数比例分配。"""
    spans = split_subtitle_spans(text, cap)
    total = sum(stop - start for start, stop in spans)
    lines: list[TimedLine] = []
    cursor = 0.0
    for index, (start, stop) in enumerate(spans):
        # 末行收在段尾：逐行累加会攒出浮点毛刺
        end = (
            duration_s if index == len(spans) - 1 else cursor + duration_s * (stop - start) / total
        )
        lines.append(TimedLine(round(cursor, 3), round(end, 3), text[start:stop]))
        cursor = end
    return lines


def hold_readable(lines: list[TimedLine], *, limit: float) -> list[TimedLine]:
    """最短可读停留：亮不够的行先只延末点，末点没有空间再向前一行借。

    只延末点、不重叠、不动后面行的起点。向前借只在按字数比例分配的行上才会真的
    动到前一行（词界路径的行间本来就有念白停顿可用），且前一行自己必须还留得够
    MIN_DISPLAY_S。段尾的行最多延到 `limit`。
    """
    out = list(lines)
    for index, line in enumerate(out):
        need = MIN_DISPLAY_S - (line.end - line.start)
        if need <= 0:
            continue
        ceiling = out[index + 1].start - LINE_GAP_S if index + 1 < len(out) else limit
        extend = min(need, max(0.0, ceiling - line.end))
        out[index] = line = replace(line, end=round(line.end + extend, 3))
        need -= extend
        if need > 0 and index > 0:
            prev = out[index - 1]
            slack = max(0.0, prev.end - prev.start - MIN_DISPLAY_S)
            floor = max(0.0, prev.end + LINE_GAP_S - slack)
            borrow = min(need, max(0.0, line.start - floor))
            if borrow > 0:
                out[index] = replace(line, start=round(line.start - borrow, 3))
                out[index - 1] = replace(
                    prev,
                    end=round(min(prev.end, out[index].start - LINE_GAP_S), 3),
                )
    return out


def narration_lines(
    text: str, cues: list[Any] | None, cap: int, duration_s: float
) -> list[TimedLine]:
    """解说字幕行：有词界 cue 走真实词时，没有就按字数比例；都过最短可读停留。"""
    timed = lines_from_cues(text, cues, cap) if cues else None
    return hold_readable(timed or lines_by_share(text, cap, duration_s), limit=duration_s)
