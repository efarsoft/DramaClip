"""情绪智能匹配（原案 6A.7）：文本/标签 → 情绪键（预设 emotion_style 的键）。

LLM/SenseVoice 情绪标签优先（AsrSegment.emotion）；缺失时关键词降级。
"""

from __future__ import annotations

# 标签归一化：各类来源的情绪标签 → 预设情绪键
_LABEL_MAP: dict[str, str] = {
    "angry": "anger",
    "anger": "anger",
    "threatening": "anger",
    "contempt": "anger",
    "triumph": "triumph",
    "happy": "triumph",
    "excited": "triumph",
    "suspense": "suspense",
    "fear": "suspense",
    "sad": "sadness",
    "sadness": "sadness",
}

_KNOWLEDGE_WORDS: tuple[str, ...] = ("滚", "杀", "打", "恨", "废物", "闭嘴", "耻")
_TRIUMPH_WORDS: tuple[str, ...] = ("赢了", "翻身", "崛起", "报仇", "成功了")
_SUSPENSE_WORDS: tuple[str, ...] = ("真相", "秘密", "到底", "竟然", "居然", "没想到")


def match_emotion(text: str, emotion_label: str | None = None) -> str:
    """返回情绪键（default/anger/triumph/suspense/sadness）。"""
    if emotion_label:
        normalized = _LABEL_MAP.get(emotion_label.strip().lower())
        if normalized is not None:
            return normalized
    lowered = text.lower()
    if any(word in text for word in _KNOWLEDGE_WORDS):
        return "anger"
    if any(word in lowered or word in text for word in _TRIUMPH_WORDS):
        return "triumph"
    if any(word in text for word in _SUSPENSE_WORDS):
        return "suspense"
    return "default"

