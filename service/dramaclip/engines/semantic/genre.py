"""题材分类（原案 4.4）：LLM 主路 + 关键词降级。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

GENRES: tuple[str, ...] = ("复仇", "甜宠", "悬疑", "逆袭", "家庭伦理", "都市", "古装", "其他")

_SYSTEM_PROMPT = (
    "你是短剧发行顾问。判断这部短剧的主导题材——多题材混合时按**主线冲突**归类，只能从以下选择一个："
    + " / ".join(GENRES[:-1])
    + '。只返回 JSON：{"genre":"复仇"}，不要其他内容。'
)

_GENRE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "复仇": ("报仇", "复仇", "还债", "讨回", "血债", "仇人"),
    "甜宠": ("喜欢", "亲爱", "抱抱", "心动", "恋爱", "宠"),
    "悬疑": ("真相", "秘密", "线索", "调查", "谜", "失踪"),
    "逆袭": ("翻身", "逆袭", "崛起", "废物", "看不起", "震惊"),
    "家庭伦理": ("婆婆", "儿媳", "家产", "遗产", "兄弟", "娘家"),
    "都市": ("公司", "总裁", "合同", "项目", "职场", "老板"),
    "古装": ("皇上", "娘娘", "本宫", "陛下", "殿下", "圣旨"),
}


def classify(
    asr_text: str,
    client: LlmClient | None,
    *,
    system_prompt: str | None = None,
    trace_path: Path | None = None,
) -> str:
    """题材判定。降级（关键词兜底）不是异常，但必须留下一份能对上账的痕。"""
    text = asr_text[:3000]
    if client is None or not text.strip():
        return _classify_by_keywords(text)
    system = system_prompt or _SYSTEM_PROMPT
    raw: Any = None
    error = ""
    try:
        raw = client.chat_json(system, text)
    except LlmUnavailable as exc:
        error = f"{type(exc).__name__}: {exc}"
    answer = str(raw.get("genre", "")).strip() if isinstance(raw, dict) else ""
    matched = answer in GENRES
    keyword = _classify_by_keywords(text)
    dump_trace(
        trace_path,
        {
            "engine": "genre",
            "system": system,
            "user": text,
            "raw": raw,
            "error": error,
            "model_genre": answer,
            "matched": matched,
            "degraded": not matched,
            "keyword_genre": keyword,
        },
    )
    return answer if matched else keyword


def _classify_by_keywords(text: str) -> str:
    best_genre, best_hits = "其他", 0
    for genre, words in _GENRE_KEYWORDS.items():
        hits = sum(text.count(word) for word in words)
        if hits > best_hits:
            best_genre, best_hits = genre, hits
    return best_genre if best_hits > 0 else "其他"
