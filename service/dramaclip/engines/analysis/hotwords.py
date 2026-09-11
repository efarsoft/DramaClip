"""热词挖掘：全剧 OCR 字幕条 → ASR hotwords 表（事前注入，专名错误率的主降手段）。

短剧人物/设定/地名高度固定，字幕（人工校对）里反复出现的词就是 ASR 最容易
写错的词。取词法：jieba 分词 → 长度≥2 的普通词/人名 → 频次排序取 TopN。
纯词表输出，逗号分隔（faster-whisper hotwords 参数格式）。
"""

from __future__ import annotations

import logging
from collections import Counter

from dramaclip.engines.analysis.models import OcrSegment

logger = logging.getLogger(__name__)

_HOTWORD_TOP_N = 20
_MIN_WORD_LEN = 2
_MIN_COUNT = 3


def mine(bars: list[OcrSegment], *, top_n: int = _HOTWORD_TOP_N) -> str:
    """从字幕条挖掘热词表；不足 _MIN_COUNT 次的词不收。返回逗号分隔串。"""
    if not bars:
        return ""
    try:
        import jieba
    except ImportError:
        logger.warning("jieba 未安装，热词挖掘跳过")
        return ""
    counts: Counter[str] = Counter()
    for bar in bars:
        for word in jieba.cut(bar.text):
            word = word.strip()
            if len(word) < _MIN_WORD_LEN or word.isdigit():
                continue
            counts[word] += 1
    qualified = [
        (word, count)
        for word, count in counts.most_common()
        if count >= _MIN_COUNT
    ]
    hotwords = [word for word, _count in qualified[:top_n]]
    if hotwords:
        logger.info("热词表 %d 个：%s", len(hotwords), "、".join(hotwords))
    return "，".join(hotwords)
