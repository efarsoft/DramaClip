"""B7：长文本 TTS 切分（纯函数，无 IO）。

切分优先级：句末标点（。！？；.!?;）→ 子句（，、,:）→ 空白 → 硬切。
逐层只在「上一层的原子块仍超上限」时启用，任何一层都不丢字：
``"".join(chunks) == text`` 恒成立（调用方按序拼接即还原原文）。

字符上限（依据）：
  · latin 500 —— 云端 TTS（edge-tts 单请求）与本地引擎单段的舒适区；
    超过后 edge 服务端会自行再切，质量与超时都不可控。
  · CJK 200 = 500 / 2.5 —— 中文信息密度约为拉丁字母的 2.5 倍
    （同秒数语音承载的字符数），等时长口径下上限同比例缩。
  · CJK 占比 ≥ 30% 即按 CJK 上限：混排文本里中文句读决定韵律，
    按 latin 上限切会把中文段切得过粗。

**不做中文数字归一化**：IndexTTS worker 上游 ``infer(text_normalization=True)``
（隔离 venv 实测签名）自己做归一化，split 层再做一遍会双重转换；参考文本
（克隆场景）与合成文本走同一条 worker 路径，天然同步。

空 chunk 必须丢弃并计数（``SplitResult.dropped_empty``）：调用方拿计数做诚实
报告，而不是对着空串调引擎（空文案在真引擎上是异常，见 tts.preview 的守卫）。
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: 拉丁文本单块字符上限（依据见模块 docstring）
LATIN_MAX_CHARS = 500
#: CJK 文本单块字符上限 = LATIN_MAX_CHARS / 2.5
CJK_MAX_CHARS = 200
#: CJK 占比达到该值即按 CJK 上限切
_CJK_RATIO = 0.30

_SENTENCE_END = "。！？；.!?;"
_CLAUSE_END = "，、,:"

# 句末切分：标点后断开，标点归属前块（lookbehind 不消费字符，join 可还原）
_SENTENCE_RE = re.compile(f"(?<=[{re.escape(_SENTENCE_END)}])")
_CLAUSE_RE = re.compile(f"(?<=[{re.escape(_CLAUSE_END)}])")
_WORD_RE = re.compile(r"\S+\s*")


class SplitResult(NamedTuple):
    """切分结果：非空块序列 + 被丢弃的空块数（诚实报告的凭据）。"""

    chunks: list[str]
    dropped_empty: int


def split_long_text(
    text: str, *, cjk_aware: bool = True, max_chars: int | None = None
) -> SplitResult:
    """把长文本切成逐块可合成的片段；短文本原样单块返回。

    ``max_chars`` 显式给定则覆盖语言推断的上限（克隆引擎按参考音频预算收紧时用）。
    """
    if not text.strip():
        # 全空白文本就是一个「被丢弃的空块」：不返回 [""]，调用方不该拿空串去合成
        return SplitResult([], 1)
    limit = max_chars if max_chars is not None else _limit_for(text, cjk_aware)
    units = _atomic_units(text, limit)
    units = _fold_punct_only(units)
    chunks = _pack(units, limit)
    kept = [chunk for chunk in chunks if chunk.strip() != ""]
    return SplitResult(kept, len(chunks) - len(kept))


def _limit_for(text: str, cjk_aware: bool) -> int:
    if not cjk_aware:
        return LATIN_MAX_CHARS
    letters = [char for char in text if not char.isspace()]
    if not letters:
        return LATIN_MAX_CHARS
    cjk = sum(1 for char in letters if _is_cjk(char))
    return CJK_MAX_CHARS if cjk / len(letters) >= _CJK_RATIO else LATIN_MAX_CHARS


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF  # CJK 统一表意文字
        or 0x3400 <= code <= 0x4DBF  # 扩展 A
        or 0x3000 <= code <= 0x303F  # CJK 句读（。、「」）
        or 0xFF00 <= code <= 0xFFEF  # 全角字符（！？：，）
    )


def _atomic_units(text: str, limit: int) -> list[str]:
    """级联切到每块 ≤ limit：句末 → 子句 → 空白 → 硬切。join 后与原文逐字相等。"""
    units: list[str] = []
    for sentence in _SENTENCE_RE.split(text):
        if sentence == "":
            continue
        if len(sentence) <= limit:
            units.append(sentence)
            continue
        for clause in _CLAUSE_RE.split(sentence):
            if clause == "":
                continue
            if len(clause) <= limit:
                units.append(clause)
                continue
            units.extend(_split_by_space_or_hard(clause, limit))
    return units


def _split_by_space_or_hard(piece: str, limit: int) -> list[str]:
    words = _WORD_RE.findall(piece)
    units: list[str] = []
    for word in words:
        if len(word) <= limit:
            units.append(word)
        else:
            units.extend(_hard_cut(word, limit))
    return units


def _hard_cut(piece: str, limit: int) -> list[str]:
    return [piece[i : i + limit] for i in range(0, len(piece), limit)]


def _is_punct_only(unit: str) -> bool:
    """纯标点/空白碎块：没有任何字母、数字或表意文字（str.isalnum 对 CJK 汉字为真，
    对「。！？」等标点为假——不用 _is_cjk，那个的区间含全角标点会误判）。"""
    return not any(char.isalnum() for char in unit)


def _fold_punct_only(units: list[str]) -> list[str]:
    """纯标点碎块折回邻块（优先前块，首块折向后块）：独立成块的「！！！」合成出来
    是突兀的空白+爆音，折回才是人耳听到的那句话。折回后允许超 limit——碎块本身
    不可再分，宁可超限也不丢内容。"""
    folded: list[str] = []
    for unit in units:
        if folded and (_is_punct_only(unit) or _is_punct_only(folded[-1])):
            folded[-1] += unit
        else:
            folded.append(unit)
    return folded


def _pack(units: list[str], limit: int) -> list[str]:
    """贪心装箱：相邻原子块并到不超上限为止（减少块数=减少拼接点与引擎调用）。"""
    chunks: list[str] = []
    buffer = ""
    for unit in units:
        if buffer and len(buffer) + len(unit) > limit:
            chunks.append(buffer)
            buffer = unit
        else:
            buffer += unit
    if buffer:
        chunks.append(buffer)
    return chunks
