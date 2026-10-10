"""转写精炼层：LLM 断句 + 语境校对，合并单次调用（P1 转写质量跃升）。

本地 ASR（paraformer）在 BGM 素材上有三类病：跨停顿并句、句尾串音、同音错字。
声学断句（VAD）被 BGM 骗（停顿里音乐还在响），字幕窗分行被两套时钟骗（字戳是
插值）——**语义断句不受两者影响**：「大明两大蛀虫」是一个短语、「干的第一件事」
是新句开头，这是语言判断。

单次 LLM 调用输出「切好句、修同音错字」的句子数组；**对齐审计护栏（纯代码）**
验证输出不得丢失内容、替换必须拼音同/近音、凭空插入必须有字幕读数佐证——
LLM 的自由度被数学约束在「移动边界 + 同音替换 + 有据补字」内。
护栏拒绝 → 回退 paraformer 原生分段（完整句兜底）+ WARN，不挡分析（分档语义）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pypinyin import lazy_pinyin

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.semantic.llm_client import (
    LlmConfig,
)
from dramaclip.engines.semantic.llm_client import (
    from_settings as llm_from_settings,
)

_LOGGER = logging.getLogger(__name__)

# 标点豁免：LLM 添加的标点不进对齐（可读性，无内容风险）
_PUNCT = set("，。！？、：；“”‘’…—，!.?:;\"'()[]{}<>-_/\\ \n\t\r")
_MAX_RETRIES = 1


@dataclass
class RefineOutcome:
    """精炼结果：applied=False 时 segments 为回退的原生分段。"""

    segments: list[AsrSegment]
    applied: bool
    detail: str


@dataclass
class _Char:
    """字流单元：内容字符 + 时间戳（秒）。"""

    char: str
    start: float = 0.0
    end: float = 0.0


def _pinyin(char: str) -> str:
    """单字拼音（无声调）；无法注音（标点/符号）返回空。"""
    if not char or char in _PUNCT or not char.isalpha():
        return ""
    out = lazy_pinyin(char, errors=lambda x: "")
    return out[0] if out else ""


def _pinyin_compatible(raw: str, new: str) -> bool:
    """拼音护栏：同音（chuán==chuān 类，无声调相等）必过；近音（声母或韵母相同）也过。

    空拼音（标点/符号位）不参与比较，恒过——对齐审计已单独处理删除类。
    """
    py_raw = _pinyin(raw)
    py_new = _pinyin(new)
    if not py_raw or not py_new:
        return True
    if py_raw == py_new:
        return True
    return py_raw[0] == py_new[0] or py_raw[-1] == py_new[-1]


def stream_of(segments: list[AsrSegment]) -> list[_Char] | None:
    """ASR 字流：逐内容字带时间戳；任一段「词戳字数与文本字数不符」→ None（坏数据）。"""
    stream: list[_Char] = []
    for seg in segments:
        words = [(word, ch) for word in seg.words for ch in _content(word.word)]
        text_chars = [ch for ch in _marks(seg.text)]
        if len(words) != len(text_chars):
            return None
        for (word, ch), _mark in zip(words, text_chars, strict=True):
            stream.append(_Char(char=ch, start=word.start, end=word.end))
    return stream


def _content(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def _marks(text: str) -> list[tuple[str, bool]]:
    return [(ch, ch not in _PUNCT) for ch in text]


def _audit(
    raw: list[_Char],
    sentences: list[str],
    ocr_text: str,
) -> str:
    """对齐审计：输出字流 vs 原始字流。返回空串=通过；否则拒绝原因。

    规则：内容删除 → 拒；替换/插入 → 拼音同/近（插入须字幕读数有据）→ 否则拒。
    标点自由。NW 对齐按内容字，标点在两侧各自剥离后比对。
    """
    raw_chars = [c.char for c in raw if c.char not in _PUNCT]
    out_chars = [ch for sentence in sentences for ch in _content(sentence)]
    import difflib

    matcher = difflib.SequenceMatcher(a=raw_chars, b=out_chars, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            return f"内容删除：原文 {i2 - i1} 字在输出中丢失（{''.join(raw_chars[i1:i2])}）"
        if tag == "insert":
            inserted = "".join(out_chars[j1:j2])
            if inserted not in ocr_text:
                return f"无据插入：{''.join(out_chars[j1:j2])} 不在字幕读数中"
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                r = raw_chars[i1 + k] if i1 + k < i2 else ""
                o = out_chars[j1 + k] if j1 + k < j2 else ""
                if r and o and not _pinyin_compatible(r, o):
                    return f"非近音改写：{r} → {o}"
    return ""


def refine_segments(
    segments: list[AsrSegment],
    *,
    ocr_text: str,
    project_name: str,
    hotwords: str,
    settings: dict[str, str],
) -> RefineOutcome:
    """精炼主入口：断句+校对单次调用 → 护栏 → 映射。任何失败按分档回退原生分段。"""
    if not segments:
        return RefineOutcome(segments=segments, applied=False, detail="无输入段")
    stream = stream_of(segments)
    if stream is None:
        _LOGGER.warning(
            "转写精炼跳过：%d 段的字级戳与文本对不上（坏数据），产物为原生分段",
            len(segments),
        )
        return RefineOutcome(segments=segments, applied=False, detail="字流校验失败")
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        return RefineOutcome(segments=segments, applied=False, detail="LLM 未配置")
    client = llm_from_settings(settings)

    raw_text = "".join(c.char for c in stream)
    prompt_user = _user_prompt(raw_text, ocr_text, project_name, hotwords)
    system = _SYSTEM_PROMPT

    sentences: list[str] | None = None
    detail = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            data = client.chat_json(system, prompt_user, temperature=0.3)
            parsed = data.get("sentences") if isinstance(data, dict) else None
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed) and parsed:
                sentences = parsed
                break
            detail = f"输出形状不符（attempt {attempt + 1}）"
        except Exception as exc:  # noqa: BLE001 - LLM 失败分档回退，原样记原因
            detail = f"{type(exc).__name__}: {exc}（attempt {attempt + 1}）"
        prompt_user += "\n\n上一次输出不符合 JSON 格式要求，请严格只输出 {\"sentences\": [...]}。"
    if sentences is None:
        _LOGGER.warning("转写精炼跳过：%s；产物为原生分段", detail)
        return RefineOutcome(segments=segments, applied=False, detail=detail)

    ocr_reference = ocr_text.replace(" ", "")
    reject = _audit(raw=stream, sentences=sentences, ocr_text=ocr_reference)
    if reject:
        _LOGGER.warning("转写精炼护栏拒绝（%s）；产物为原生分段", reject)
        return RefineOutcome(segments=segments, applied=False, detail=f"护栏拒绝: {reject}")

    refined = _to_segments(stream, sentences)
    _LOGGER.info(
        "转写精炼完成：%d 段 → %d 句（原文 %d 字 → %d 字）",
        len(segments), len(refined), len(raw_text), sum(len(s.text) for s in refined),
    )
    return RefineOutcome(segments=refined, applied=True, detail="ok")


def _to_segments(stream: list[_Char], sentences: list[str]) -> list[AsrSegment]:
    """句子 → AsrSegment：时间取句内首末字戳（标点不占字位）。"""
    content_stream = [c for c in stream if c.char not in _PUNCT]
    result: list[AsrSegment] = []
    cursor = 0
    for sentence in sentences:
        size = len(_content(sentence))
        chunk = content_stream[cursor:cursor + size]
        cursor += size
        if not chunk:
            continue
        result.append(
            AsrSegment(
                start=round(chunk[0].start, 3),
                end=round(chunk[-1].end, 3),
                text=sentence.strip(),
            )
        )
    return result


def _user_prompt(raw_text: str, ocr_text: str, project_name: str, hotwords: str) -> str:
    parts = [f"剧名：《{project_name}》"]
    if hotwords.strip():
        parts.append(f"热词（可能涉及的专有名）：{hotwords.strip()}")
    if ocr_text.strip():
        parts.append(f"字幕参考（画面叠加字幕，仅供纠错参考）：{ocr_text}")
    parts.append(f"语音识别字流：\n{raw_text}")
    return "\n".join(parts)


_SYSTEM_PROMPT = (
    "你是短剧转写精炼器。输入是语音识别的连续字流（无标点或标点错乱，"
    "可能含同音/近音错字，背景有 BGM）。\n"
    "任务只有两个：\n"
    "1. 按语义切成自然的句/短语（短剧解说字幕粒度：一个短语一行）\n"
    "2. 修正明显的同音/近音错字（依据语境、剧名与字幕参考；"
    "例如「传承崇祯」应为「穿成崇祯」、「东昌提督」应为「东厂提督」）\n"
    '输出 JSON：{"sentences": ["句子1", "句子2", ...]}\n'
    "硬性规则：\n"
    "- 所有句子拼接后必须与输入字流逐字一致（同音/近音字替换除外），"
    "禁止增删语句内容、禁止改写句式、禁止总结概括\n"
    "- 可以为句子添加合适的标点\n"
    "- 字幕参考是画面叠加的硬字幕，仅供纠错参考；其中转写字流里没有的内容不得搬入\n"
    "- 只输出 JSON，不要多余文字"
)

