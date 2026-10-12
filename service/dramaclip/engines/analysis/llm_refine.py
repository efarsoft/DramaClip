"""转写精炼层：LLM 断句 + 语境校对，合并单次调用（P1 转写质量跃升）。

本地 ASR（paraformer）在 BGM 素材上有三类病：跨停顿并句、句尾串音、同音错字。
声学断句（VAD）被 BGM 骗（停顿里音乐还在响），字幕窗分行被两套时钟骗（字戳是
插值）——**语义断句不受两者影响**：「大明两大蛀虫」是一个短语、「干的第一件事」
是新句开头，这是语言判断。

单次 LLM 调用输出「切好句、修同音错字」的句子数组；**对齐审计护栏（纯代码）**
验证输出不得丢失内容、替换必须拼音同/近音、凭空插入必须有字幕读数佐证——
LLM 的自由度被数学约束在「移动边界 + 同音替换 + 有据补字」内；非法编辑
（丢字/改写句式/凭空造字）由护栏**自动修复**（回退原字/丢弃），合法修正全保留。
护栏拒绝 → 回退 paraformer 原生分段（完整句兜底）+ WARN，不挡分析（分档语义）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pypinyin import lazy_pinyin

from dramaclip.engines.analysis.models import AsrSegment, OcrSegment
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


@dataclass
class _Entry:
    """修复后的内容字：字、句序、时间戳（None = 无原字对应，取相邻有据字）。"""

    char: str
    sent: int
    start: float | None
    end: float | None


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
        text_chars = [ch for ch in seg.text if ch not in _PUNCT]
        if len(words) != len(text_chars):
            return None
        for (word, ch), _mark in zip(words, text_chars, strict=True):
            stream.append(_Char(char=ch, start=word.start, end=word.end))
    return stream


def _content(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def _repair(
    raw: list[_Char], sentences: list[str], ocr_text: str
) -> tuple[list[list[_Entry]], int]:
    """对齐修复：非法编辑回退原字/丢弃，合法修正保留——护栏从「拒绝」升级为「自动修复」。

    - 内容删除（原文字被 LLM 丢掉）→ 还原原字（丢话最危险，一律还原）
    - 替换不同音 → 回退原字（防改写句式）
    - 替换同音/近音 → 保留修正
    - 凭空插入（字幕读数无据）→ 丢弃；有据（OCR 读到的字）→ 保留
    - 标点 → 原样保留
    返回：每句的 [(内容字, start|None, end|None)]（None=该字无原字对应，时间取邻字），
    以及回退/丢弃的字数。"""
    import difflib

    raw_content = [c for c in raw if c.char not in _PUNCT]
    tagged: list[tuple[str, int]] = []
    for index, sentence in enumerate(sentences):
        for ch in _content(sentence):
            tagged.append((ch, index))
    matcher = difflib.SequenceMatcher(
        a=[c.char for c in raw_content], b=[t[0] for t in tagged], autojunk=False
    )
    repaired: list[list[_Entry]] = [[] for _ in sentences]
    issues = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                char, sent = tagged[j1 + k]
                rc = raw_content[i1 + k]
                repaired[sent].append(_Entry(char, sent, rc.start, rc.end))
        elif tag == "delete":
            fallback_sent = (
                tagged[j1][1] if j1 < len(tagged) else len(sentences) - 1
            )
            for k in range(i1, i2):
                rc = raw_content[k]
                repaired[fallback_sent].append(_Entry(rc.char, fallback_sent, rc.start, rc.end))
            issues += i2 - i1
        elif tag == "insert":
            for k in range(j1, j2):
                char, sent = tagged[k]
                if char in ocr_text:
                    repaired[sent].append(_Entry(char, sent, None, None))
                else:
                    issues += 1
        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                r = raw_content[i1 + k] if i1 + k < i2 else None
                t = tagged[j1 + k] if j1 + k < j2 else None
                if t is None:
                    if r is not None:
                        repaired[len(sentences) - 1].append(
                            _Entry(r.char, len(sentences) - 1, r.start, r.end)
                        )
                        issues += 1
                    continue
                if r is None:
                    if t[0] in ocr_text:
                        repaired[t[1]].append(_Entry(t[0], t[1], None, None))
                    else:
                        issues += 1
                    continue
                if _pinyin_compatible(r.char, t[0]):
                    repaired[t[1]].append(_Entry(t[0], t[1], r.start, r.end))
                else:
                    repaired[t[1]].append(_Entry(r.char, t[1], r.start, r.end))
                    issues += 1
    return repaired, issues


def refine_segments(
    segments: list[AsrSegment],
    *,
    ocr_segments: list[OcrSegment] | None,
    project_name: str,
    hotwords: str,
    settings: dict[str, str],
) -> RefineOutcome:
    """精炼主入口：断句+校对单次调用 → 护栏 → 字幕窗时间映射。失败按分档回退原生分段。

    字幕窗（画面事实）作为输入信息喂给 LLM——原作者的分句节奏对模型可见，
    断句粒度与时间轴自然锚定；LLM 只做它最擅长的：语义断句微调与同音纠错。
    """
    windows = _windows(ocr_segments or [])
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
    prompt_user = _user_prompt(raw_text, windows, project_name, hotwords)
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

    ocr_reference = "".join(text for _s, _e, text in windows).replace(" ", "")
    repaired, issues = _repair(stream, sentences, ocr_reference)
    refined = _to_segments(sentences, repaired, windows)
    if issues:
        _LOGGER.warning("转写精炼护栏自动修复 %d 处（回退原字/丢弃无据字）", issues)
    return RefineOutcome(
        segments=refined,
        applied=True,
        detail="ok" if issues == 0 else f"护栏自动修复 {issues} 处",
    )


def _windows(ocr_segments: list[OcrSegment]) -> list[tuple[float, float, str]]:
    """字幕窗：相邻同文本条合并为驻留窗——窗=一条字幕的在屏时间与读数。"""
    windows: list[tuple[float, float, str]] = []
    for bar in ocr_segments:
        text = bar.text.strip()
        if not text:
            continue
        compact = text.replace(" ", "")
        if windows and windows[-1][2].replace(" ", "") == compact:
            s0, e0, _ = windows[-1]
            windows[-1] = (min(s0, bar.start), max(e0, bar.end), text)
        else:
            windows.append((bar.start, bar.end, text))
    return windows


def _to_segments(
    sentences: list[str],
    repaired: list[list[_Entry]],
    windows: list[tuple[float, float, str]],
) -> list[AsrSegment]:
    """句子 → AsrSegment：文本=修复后内容字按标点模板重排；时间=字幕窗锚定。

    数量不符（LLM 断句数与窗数不一致）时按比例分配窗时间。
    """
    result: list[AsrSegment] = []
    n, w = len(sentences), len(windows)
    for index, sentence in enumerate(sentences):
        contents = repaired[index] if index < len(repaired) else []
        template: list[tuple[str, int | None]] = []
        cursor = 0
        for ch in sentence:
            if ch in _PUNCT:
                template.append((ch, None))
            else:
                template.append((ch, cursor))
                cursor += 1
        parts: list[str] = []
        for ch, pos in template:
            if pos is None:
                parts.append(ch)
            elif pos < len(contents):
                parts.append(contents[pos].char)
        # 护栏还原/有据补字超出 LLM 模板槽位的部分尾部续齐（内容完整性优先）
        while cursor < len(contents):
            parts.append(contents[cursor].char)
            cursor += 1
        text = "".join(parts).strip()
        if not text or not _content(text):
            continue
        start_f = contents[0].start if contents and contents[0].start is not None else 0.0
        end_last = contents[-1] if contents else None
        end_f = end_last.end if end_last is not None and end_last.end is not None else start_f
        if w > 0:
            lo = index * w // n
            hi = min(max((index + 1) * w // n, lo + 1), w)
            start_f, end_f = windows[lo][0], windows[hi - 1][1]
        result.append(AsrSegment(start=round(start_f, 3), end=round(end_f, 3), text=text))
    return result


def _user_prompt(
    raw_text: str,
    windows: list[tuple[float, float, str]],
    project_name: str,
    hotwords: str,
) -> str:
    parts = [f"剧名：《{project_name}》"]
    if hotwords.strip():
        parts.append(f"热词（可能涉及的专有名）：{hotwords.strip()}")
    if windows:
        lines = [f"[{s:.1f}-{e:.1f}s] {text}" for s, e, text in windows]
        parts.append(
            "字幕窗（每条字幕的在屏时间与读数——原作者的分句节奏，"
            "你的断句应与此节奏对应；窗内读数仅供纠错参考）：\n" + "\n".join(lines)
        )
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

