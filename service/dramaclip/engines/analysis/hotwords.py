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

_HOTWORD_TOP_N = 10
_MIN_WORD_LEN = 2
_MAX_WORD_LEN = 4
_MIN_COUNT = 3
# 虚词/代词/疑问词做热词有害无益（占 prompt 预算、诱导填充词风格）
_STOPWORDS = frozenset({
    "我们", "你们", "他们", "她们", "自己", "这个", "那个", "这些", "那些",
    "怎么", "什么", "这样", "那样", "就是", "不是", "没有", "已经", "因为",
    "所以", "但是", "如果", "一个", "真是", "今天", "知道", "觉得", "东西",
    "地方", "时间", "出来", "起来", "过来", "这里", "那里",
})


def _is_cjk(word: str) -> bool:
    return all("一" <= ch <= "鿿" for ch in word)


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
            if (
                len(word) < _MIN_WORD_LEN
                or len(word) > _MAX_WORD_LEN
                or word in _STOPWORDS
                or not _is_cjk(word)
            ):
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
    # 空格分隔：全角逗号分隔会作为 prompt 条件诱导模型高频输出逗号（真机实证 135 个）
    return " ".join(hotwords)
