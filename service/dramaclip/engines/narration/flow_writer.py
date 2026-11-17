"""整篇叙事试验线（v0.2.6 第二批 W6）：自由文本解说 → 锚定台词引用 → 确定性铺轴。

与剧本驱动链（scriptwriter.write_script_episodes，LLM 直接产时间轴 JSON）的差异：
创意调用**零机械约束**——不产时间戳、不管画面窗口、无字数帽，只交「一句解说 +
一句它所依据的原文台词」的列表；画面落点由确定性对齐铺轴完成（quote 定位转写
段）。这是 2026-11-17 成片质量诊断的落地形态：创意面只剩正向指导，机械精度
全部移交确定性工序（行业共识：约束分层）。

对齐口径：quote 从转写台词行里一字不差摘录（LLM 锚定纪律）→ 精确子串定位 →
失配走 difflib 模糊（阈值 0.55）→ 仍失配视为无锚句（沿用上一句的集与光标续写）。
铺轴产物是与剧本链同形的 Script → **原封复用** build_from_script_episodes 铺轴
（台词边界吸附/镜头切点外扩/近邻衔接/CTA 尾铺全继承），下游合成渲染零改动。

A/B：settings ``narration.flow_style=1`` 时 dialogue_narration 走本线，与槽位制
（默认）天然成对照组。
"""

from __future__ import annotations

import difflib
import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.narration import audit as narration_audit
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.narration.scriptwriter import (
    FUNDAMENTALS,
    Script,
    ScriptSegment,
    estimate_duration,
    format_mute_canvas,
    format_transcript_episodes,
    format_visual_tracks,
    genre_emphasis_block,
)
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

logger = logging.getLogger(__name__)

SCRIPT_LLM_TIMEOUT_S = 600.0
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = (15.0, 30.0)
_FUZZY_ANCHOR_RATIO = 0.55
_PAUSE_BREATH_S = 0.30  # 与 models.PAUSE_BREATH_S 同源（呼吸扣减见 W2）
_MIN_BODY_LINES = 4  # 正文句数下限（防退化，同剧本链段数下限纪律）

class FlowLine(BaseModel):
    """整篇线的一句：解说文本 + 它所依据的原文台词引用（锚）。"""

    quote: str = ""
    text: str = ""


class FlowScript(BaseModel):
    """整篇产物：开场句 + 正文句列 + 结尾引导句。数字中文化出口单一收口。"""

    hook: FlowLine
    segments: list[FlowLine] = Field(default_factory=list)
    cta: FlowLine = Field(default_factory=FlowLine)

    def all_lines(self) -> list[FlowLine]:
        return [self.hook, *self.segments, self.cta]


def _flow_system() -> str:
    return (
        "你是这部剧的专属解说编剧：全集看了三遍，角色底细如数家珍，现在在饭桌上"
        "给朋友讲它——讲完他要连夜去刷原剧。事实只来自下面给出的台词。\n"
        "本轮交付形态：**一篇连贯的解说文章**，不是时间轴——不需要你算任何时间戳、"
        "不需要管画面窗口，画面落点由后置工序按你的台词引用自动对齐。只管把故事"
        "讲得抓人。\n"
        + FUNDAMENTALS
        + "\n输出 JSON（只输出 JSON，不要多余文字）："
        '{"hook": {"quote": "开场句依据的原文台词，一字不差摘录，无则空串", '
        '"text": "开场钩子句"}, '
        '"segments": [{"quote": "该句依据的原文台词，无则空串", "text": "解说句"}…], '
        '"cta": {"quote": "…", "text": "结尾引导句"}}。\n'
        "锚定纪律：每个句子的 quote 从下方转写台词行里**一字不差**摘录（可以是该句"
        "台词的开头片段），后置工序按它把这句对齐到画面窗口；多数句子应当有锚，"
        "纯转场/情绪句可给空串。text 是写给观众听的解说，不要照抄 quote 的台词原文"
        "——被引用的台词由画面原声呈现，你写的是承接与推进。"
    )


def build_flow_request(
    episode_inputs: list[dict[str, Any]],
    *,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    genre: str = "",
    prompts: dict[str, str] | None = None,
) -> tuple[str, str]:
    """纯函数：组装整篇线的 (system, user)，不调用 LLM（审计/回放工具复用）。"""
    transcript_block = format_transcript_episodes(episode_inputs)
    if not transcript_block:
        raise ValueError("编剧无米下锅：所有集都没有台词转写")
    anchor_block = (
        "转写按集分组（每组以「【第N集】」单独一行开头），其后每行一条台词，"
        "格式为「开始-结束 台词」，时间为该集内的相对时间。"
        "受上下文预算限制，每组是该集跨头尾的均匀摘录（集首与集尾台词必定保留），"
        "不是全量逐字。你的 quote 必须从这些台词行里摘录。"
    )
    style_block = f"\n解说风格要求：{style_directives}" if style_directives != "" else ""
    visual_suffix = format_visual_tracks(episode_inputs)
    visual_suffix = f"\n\n{visual_suffix}" if visual_suffix else ""
    mute_block = format_mute_canvas(episode_inputs)
    mute_suffix = f"\n\n{mute_block}" if mute_block else ""
    user_prompt = (
        f"项目：{project_name}\n"
        f"句子数随剧情需要而定：把关键冲突讲透、反转给足戏份；故事短就少写几句。\n"
        f"{anchor_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + visual_suffix
        + mute_suffix
        + genre_emphasis_block(genre)
        + f"{style_block}"
    )
    override = (prompts or {}).get("prompt.flow_system")
    system = override if override else _flow_system()
    return system, user_prompt


def _transcript_index(
    episode_inputs: list[dict[str, Any]],
) -> list[tuple[int, float, float, str]]:
    return [
        (
            int(ep["number"]),
            float(seg["start"]),
            float(seg["end"]),
            str(seg.get("text") or "").strip(),
        )
        for ep in episode_inputs
        for seg in (ep.get("segments") or [])
        if str(seg.get("text") or "").strip()
    ]


def _anchor_of_quote(
    quote: str,
    transcripts: list[tuple[int, float, float, str]],
) -> tuple[int, float, float] | None:
    """quote → 依据的转写段 (集号, start, end)：精确子串优先，失配走 difflib 模糊。"""
    q = quote.strip()
    if not q:
        return None
    for number, start, end, text in transcripts:
        if q in text or text in q:
            return number, start, end
    best: tuple[float, int, float, float] | None = None
    for number, start, end, text in transcripts:
        ratio = difflib.SequenceMatcher(None, q, text).ratio()
        if ratio >= _FUZZY_ANCHOR_RATIO and (best is None or ratio > best[0]):
            best = (ratio, number, start, end)
    if best is None:
        return None
    _ratio, number, start, end = best
    return number, start, end


def _flow_to_script(
    flow: FlowScript,
    episode_inputs: list[dict[str, Any]],
) -> Script:
    """锚定铺轴：每句 quote 定位转写段得 (集, start, end)；无锚句沿用上一句的
    集与光标续写（转场/情绪句跟随叙事流）。产出与剧本链同形的 Script——
    铺轴吸附/近邻衔接/CTA 尾铺由 build_from_script_episodes 原样接管。"""
    transcripts = _transcript_index(episode_inputs)
    placed: list[ScriptSegment] = []
    cursor_by_ep: dict[int, float] = {}
    # 只铺 body 句：Script.hook/cta 是独立字段（build 链路专窗呈现 hook 首窗与
    # cta 尾窗），把 hook/cta 行也铺进 segments 会造成双份旁白+锚窗重叠。
    for line in flow.segments:
        text = line.text.strip()
        if not text:
            continue
        anchor = _anchor_of_quote(line.quote, transcripts)
        if anchor is not None:
            number, a_start, a_end = anchor
            prev_end = cursor_by_ep.get(number)
            # 无锚句可能已把锚窗吃到过半：锚句 start 顺延到前尾之后（不倒序），
            # end 不早于 start+估算（文案短时保住锚窗剩余，长时按实测延展）
            start = max(a_start, prev_end) if prev_end is not None else a_start
            end = max(a_end, start + estimate_duration(text))
        elif placed:
            last = placed[-1]
            number, start = last.episode, last.end
            end = start + estimate_duration(text)
        else:
            number = transcripts[0][0] if transcripts else 1
            start, end = 0.0, estimate_duration(text)
        placed.append(
            ScriptSegment(episode=number, start=round(start, 2), end=round(end, 2), text=text)
        )
        cursor_by_ep[number] = max(cursor_by_ep.get(number, 0.0), end)
    hook = flow.hook.text.strip() or (placed[0].text if placed else "")
    cta = flow.cta.text.strip()
    return Script(hook=hook, segments=placed, cta=cta)


def write_flow_script(
    llm: LlmClient,
    episode_inputs: list[dict[str, Any]],
    *,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    genre: str = "",
    trace_path: Path | None = None,
    prompts: dict[str, str] | None = None,
    prior_texts: list[str] | None = None,
) -> Script:
    """整篇线主入口：生成 → 锚定铺轴 → 硬审查重掷（复用剧本链同款 audit）。
    产出与剧本链同形的 Script——清洗/铺轴/渲染下游零改动。
    """
    system, user_prompt = build_flow_request(
        episode_inputs,
        project_name=project_name,
        angle_block=angle_block,
        style_directives=style_directives,
        genre=genre,
        prompts=prompts,
    )
    transcript = [
        {
            "episode": int(ep["number"]),
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": str(seg.get("text") or ""),
        }
        for ep in episode_inputs
        for seg in ep.get("segments") or []
    ]
    durations = {
        int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs
    }
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    for attempt in range(_MAX_ATTEMPTS):
        ask = user_prompt + (
            "\n\n上一稿违反了这些硬规则，重写时逐条避免：\n"
            + "\n".join(f"- {q}" for q in attempts[-1].get("audit_quotes", []))
            if attempts and attempts[-1].get("audit_quotes")
            else user_prompt
        )
        raw: Any = None
        try:
            raw = llm.chat_json(system, ask, temperature=0.75)
            if not isinstance(raw, dict):
                raise ValueError("响应不是 JSON 对象")
            hook_raw = raw.get("hook") or {}
            cta_raw = raw.get("cta") or {}
            segs_raw = raw.get("segments") or []
            if not isinstance(segs_raw, list) or len(segs_raw) < _MIN_BODY_LINES:
                count = len(segs_raw) if isinstance(segs_raw, list) else 0
                raise ValueError(f"正文句数不足：{count}")
            flow = FlowScript(
                hook=FlowLine(**_str_fields(hook_raw)),
                segments=[FlowLine(**_str_fields(item)) for item in segs_raw],
                cta=FlowLine(**_str_fields(cta_raw)),
            )
            for line in flow.all_lines():
                line.text = to_chinese_numerals(line.text.strip())
            script = _flow_to_script(flow, episode_inputs)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError) as exc:
            attempt_trace: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            if raw is not None:
                attempt_trace["raw"] = raw
            attempts.append(attempt_trace)
            if isinstance(exc, LlmUnavailable) and attempt < _MAX_ATTEMPTS - 1:
                delay = _RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)]
                logger.warning(
                    "LLM 网络类失败，%.0fs 后重试 (%d/%d)", delay, attempt + 1, _MAX_ATTEMPTS
                )
                time.sleep(delay)
            continue
        if len(script.segments) < _MIN_BODY_LINES:
            kept = len(script.segments)
            attempts[-1]["rejected"] = f"正文仅 {kept} 句（要求至少 {_MIN_BODY_LINES} 句）"
            script = None
            continue
        report = narration_audit.audit_script(
            script, transcript, episode_durations=durations, prior_texts=prior_texts
        )
        hard_fails = [f for f in report.findings if f.severity == "hard" and not f.passed]
        attempts[-1]["audit"] = {
            "hard": [f.rule_id for f in hard_fails],
            "soft": [f.rule_id for f in report.findings if f.severity == "soft" and not f.passed],
        }
        if hard_fails:
            attempts[-1]["audit_quotes"] = [f.prompt_quote or "" for f in hard_fails]
            attempts[-1]["audit_details"] = [
                f"{f.message}（{f.fix_hint or '按规则修正'}）" for f in hard_fails
            ]
            script = None
            continue
        dump_trace(trace_path, {"attempts": attempts, "script": script.model_dump()})
        return script
    tail = attempts[-1] if attempts else {}
    raise ValueError(f"整篇线 {_MAX_ATTEMPTS} 轮未产出合格解说（最后状态：{tail}）")


def _str_fields(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("锚定句不是 JSON 对象")
    return {
        "quote": str(raw.get("quote") or ""),
        "text": str(raw.get("text") or ""),
    }
