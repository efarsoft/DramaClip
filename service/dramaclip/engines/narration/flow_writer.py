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
from dramaclip.engines.narration import variant_scoring
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.narration.retell import retell_check
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
_BUDGET_TOL_S = 0.5  # 锚窗预算判定容差：小超不退稿（渲染期收短兜底够用）
_HOOK_MIN_CHARS = 6  # 首选钩子低于此字数视为无效，备选候选接管
_JUDGE_REJECT_BELOW = 7.0  # 六维评审总分低于此值触发重掷；7.0~8.0 只记批注不拒
_JUDGE_NOTE_BELOW = 8.0  # 批注线：≥8.0 干净采纳
_MAX_SEMANTIC_REJECTS = 2  # 语义类拒稿（预算/复述/评审）共享预算；audit 硬闸独立
_MAX_HIGHLIGHTS = 4  # 强拍标注确定性上限：全标 true 就退化成「拍拍都停」
_RETELL_FIX_BY_ISSUE = {
    # 复述缺口 → 修订指令（缺口分类处置：先删和拆，不是补——重写纪律）
    "unclear": "这句没讲明白：把指代和因果写直白",
    "persona_mix": "人物记混：首次出现处点名身份，后文指代换成具体的人",
    "dense": "信息太密：删次要信息或拆成两句，优先删不加解释",
    "boring": "流水账走神：这段前面补一个具体的悬念钩子",
    "jump": "跳接突兀：补一句时间/地点/因果路标",
}

class FlowLine(BaseModel):
    """整篇线的一句：解说文本 + 它所依据的原文台词引用（锚）+ 强拍标记。"""

    quote: str = ""
    text: str = ""
    highlight: bool = False


class HookLine(FlowLine):
    """开场钩子行：可带一个备选候选（首选无效时接管，多候选挑优）。"""

    alt: FlowLine | None = None


class FlowScript(BaseModel):
    """整篇产物：开场句 + 正文句列 + 结尾引导句。数字中文化出口单一收口。"""

    hook: HookLine
    segments: list[FlowLine] = Field(default_factory=list)
    cta: FlowLine = Field(default_factory=FlowLine)

    def all_lines(self) -> list[FlowLine]:
        extra = [self.hook.alt] if self.hook.alt is not None else []
        return [self.hook, *extra, *self.segments, self.cta]


def _flow_system() -> str:
    return (
        "你是这部剧的专属解说编剧：全集看了三遍，角色底细如数家珍，现在在饭桌上"
        "给朋友讲它——讲完他要连夜去刷原剧。事实只来自下面给出的台词。\n"
        "本轮交付形态：**一篇连贯的解说文章**，不是时间轴——不需要你算任何时间戳、"
        "不需要管画面窗口，画面落点由后置工序按你的台词引用自动对齐。只管把故事"
        "讲得抓人。\n"
        + FUNDAMENTALS
        + "\n开场钩子从四种形态里挑最贴这部题材的一种下笔（也可把转写里最冲突的那句"
        "台词原样搬来当第一句——剧中人自己开口，比任何转述都先声夺人）：\n"
        "①结局前置：第一句就抛最震撼的结果或瞬间，不做任何铺垫（复仇/犯罪/反转题材顺手）；\n"
        "②反常识断言：一句颠覆常识的判断或反问，逼观众想反驳（人性/现实题材顺手）；\n"
        "③绝境点名：把窒息级的困境和具体处境叠进一句（灾难/求生/家庭题材顺手）；\n"
        "④诡异疑问：呈现一个说不通的场景，让人必须问为什么（悬疑/奇幻题材顺手）。\n"
        "首句控制在口播三秒念得完的长度，写完自己默念一遍。\n"
        "输出 JSON（只输出 JSON，不要多余文字）："
        '{"hook": {"quote": "开场句依据的原文台词，一字不差摘录，无则空串", '
        '"text": "开场钩子句", "alt": {"quote": "…", "text": "备选钩子，换一个切角；'
        "没有把握就省略\"}, "
        '"segments": [{"quote": "该句依据的原文台词，无则空串", "text": "解说句", '
        '"highlight": true 可选}…], '
        '"cta": {"quote": "…", "text": "结尾引导句"}}。\n'
        "锚定纪律：每个句子的 quote 从下方转写台词行里**一字不差**摘录（可以是该句"
        "台词的开头片段），后置工序按它把这句对齐到画面窗口；多数句子应当有锚，"
        "纯转场/情绪句可给空串；**同一句台词最多被一个句子引用**——两处引用同一段"
        "画面就是紧挨着复读。text 是写给观众听的解说，不要照抄 quote 的台词原文"
        "——被引用的台词由画面原声呈现，你写的是承接与推进。\n"
        "highlight 标注纪律：全文挑 2~4 个最强拍标 true（枪响/死亡/重大反转/"
        "开场炸点这一级的事件）——只有这些句的解说结束后画面会留一小段原声呼吸"
        "（旁白停、剧情声透出来收尾）；留白是标点不是空格，句句都停等于没停。"
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
        "不是全量逐字。你的 quote 必须从这些台词行里摘录。\n"
        "句子长度参考节奏：每句解说锚定的台词片段时长，按每秒约四个字的口播速度"
        "折算，就是它顺口的长度——关键冲突可以多给两句戏份，转场过渡一句带过即可；"
        "这是参考不是硬性上限，讲得自然优先。"
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
) -> tuple[Script, list[dict[str, Any]], int]:
    """锚定铺轴：每句 quote 定位转写段得 (集, start, end)；无锚句沿用上一句的
    集与光标续写（转场/情绪句跟随叙事流）。产出与剧本链同形的 Script——
    铺轴吸附/近邻衔接/CTA 尾铺由 build_from_script_episodes 原样接管。

    返回 (script, 超预算明细, 同锚去重数)：
    - 同锚去重（W8）：同一转写行被第二个句子引用时，第二句降级为无锚续写——
      剪辑纪律「重复使用须写明意图」，LLM 没写意图，紧挨复读比跟随叙事更伤。
    - 超预算明细（W8·先排片后成稿）：文案估算时长超过「锚窗到集尾」可用上限
      的句子逐条列出，生成期就退回去收短，不留给渲染期截断（fit-relayout
      仍是最终防线，两道闸不冲突）。

    集上界钳制（装测实锤：长句 est 超集长被 audit 硬拦）：end 不越过所在集
    时长；文案长到锚窗装不下时窗口按 est 延展的上限就是集尾。"""
    durations = {
        int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs
    }
    transcripts = _transcript_index(episode_inputs)
    placed: list[ScriptSegment] = []
    cursor_by_ep: dict[int, float] = {}
    seen_anchors: set[tuple[int, float]] = set()
    deduped = 0
    overs: list[dict[str, Any]] = []
    # 只铺 body 句：Script.hook/cta 是独立字段（build 链路专窗呈现 hook 首窗与
    # cta 尾窗），把 hook/cta 行也铺进 segments 会造成双份旁白+锚窗重叠。
    for line in flow.segments:
        text = line.text.strip()
        if not text:
            continue
        anchor = _anchor_of_quote(line.quote, transcripts)
        if anchor is not None:
            number, a_start, a_end = anchor
            if (number, a_start) in seen_anchors:
                anchor = None  # 同锚降级：第二句按无锚续写
                deduped += 1
            else:
                seen_anchors.add((number, a_start))
        est = estimate_duration(text)
        if anchor is not None:
            number, a_start, a_end = anchor
            limit_by_ep = durations.get(number, 0.0)
            prev_end = cursor_by_ep.get(number)
            # 无锚句可能已把锚窗吃到过半：锚句 start 顺延到前尾之后（不倒序），
            # end 不早于 start+估算（文案短时保住锚窗剩余，长时按实测延展）
            start = max(a_start, prev_end) if prev_end is not None else a_start
            end = min(max(a_end, start + est), limit_by_ep)
            avail = limit_by_ep - start
            if est > avail + _BUDGET_TOL_S:
                overs.append(
                    {
                        "text": text[:40],
                        "est_s": round(est, 1),
                        "avail_s": round(avail, 1),
                        "target_chars": max(
                            8, int(avail / (est / max(len(text), 1)))
                        ),
                    }
                )
        elif placed:
            last = placed[-1]
            number, start = last.episode, last.end
            limit_by_ep = durations.get(number, 0.0)
            end = min(start + estimate_duration(text), limit_by_ep)
        else:
            number = transcripts[0][0] if transcripts else 1
            start, end = 0.0, min(estimate_duration(text), durations.get(number, 0.0))
        end = min(end, durations.get(number, 0.0))
        placed.append(
            ScriptSegment(
                episode=number,
                start=round(start, 2),
                end=round(end, 2),
                text=text,
                highlight=line.highlight,
            )
        )
        cursor_by_ep[number] = max(cursor_by_ep.get(number, 0.0), end)
    hook_line = flow.hook
    hook = hook_line.text.strip()
    if len(hook) < _HOOK_MIN_CHARS and hook_line.alt is not None:
        alt = hook_line.alt.text.strip()
        if len(alt) >= len(hook):
            hook = alt  # 多候选挑优：首选无效（空/过短）备选接管
    hook = hook or (placed[0].text if placed else "")
    cta = flow.cta.text.strip()
    return Script(hook=hook, segments=placed, cta=cta), overs, deduped


def _script_as_plan_like(script: Script) -> dict[str, Any]:
    """Script → 六维评审的 plan_data 形状（format_variant 只认 narration_texts）。"""
    texts = [script.hook, *(seg.text for seg in script.segments), script.cta]
    return {"narration_texts": [{"text": t} for t in texts if t.strip()]}


def _clamp_highlights(flow: FlowScript) -> int:
    """强拍标注确定性钳制：LLM 遵从率不稳（全标 true 就退化成拍拍都停），
    超上限按句序保留前 N 个——prompt 说不算数，代码兜底才算数。返回裁剪数。"""
    kept = 0
    clamped = 0
    for line in flow.segments:
        if line.highlight:
            kept += 1
            if kept > _MAX_HIGHLIGHTS:
                line.highlight = False
                clamped += 1
    return clamped


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
    settings: dict[str, str] | None = None,
) -> Script:
    """整篇线主入口：生成 → 锚定铺轴 → 闸链（audit 硬闸 → 预算闸 → 复述闸 →
    六维评审批注）→ 交付。

    闸链语义（W8）：audit hard 独立不限次内重掷；预算/复述/评审三类**语义拒稿
    共享预算** `_MAX_SEMANTIC_REJECTS`；最后一轮无论各闸结论如何都采纳带批注
    （评审低分/复述缺卡不该把活儿拦死——软信号红线）。评审与复述失败都安静
    跳过（质检是增益不是依赖）。``settings`` 缺省 None（测试/直调）：语义闸
    全关，行为与 W6 一致。
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
    retell_on = settings is not None and (
        str(settings.get("narration.flow_retell", "1")).strip() == "1"
    )
    judge_on = settings is not None and (
        str(settings.get("narration.flow_judge", "1")).strip() == "1"
    )
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    semantic_rejections = 0
    for attempt in range(_MAX_ATTEMPTS):
        feedback: list[str] = [
            str(item)
            for item in (attempts[-1].get("rewrite_feedback") if attempts else None) or []
        ]
        ask = (
            user_prompt + "\n\n上一稿按这些意见重写（逐条落实）：\n" + "\n".join(feedback)
            if feedback
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
                hook=_hook_line(hook_raw),
                segments=[_line_fields(item) for item in segs_raw],
                cta=_line_fields(cta_raw),
            )
            for line in flow.all_lines():
                line.text = to_chinese_numerals(line.text.strip())
            clamped = _clamp_highlights(flow)
            script, overs, deduped = _flow_to_script(flow, episode_inputs)
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
            attempts.append(
                {
                    "raw": raw,
                    "accepted": False,
                    "segments_kept": kept,
                    "rejected": f"正文仅 {kept} 句（要求至少 {_MIN_BODY_LINES} 句）",
                }
            )
            script = None
            continue
        attempts.append(
            {"raw": raw, "accepted": True, "segments_kept": len(script.segments)}
        )
        if deduped:
            attempts[-1]["anchor_deduped"] = deduped
        if clamped:
            attempts[-1]["highlights_clamped"] = clamped
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
            attempts[-1]["rewrite_feedback"] = [
                f"- 规则 {rule}：{detail}"
                for rule, detail in zip(
                    attempts[-1]["audit_quotes"],
                    attempts[-1]["audit_details"],
                    strict=True,
                )
            ]
            script = None
            continue
        semantic_left = (
            semantic_rejections < _MAX_SEMANTIC_REJECTS
            and attempt < _MAX_ATTEMPTS - 1
        )
        # 预算闸（先排片后成稿）：画面装不下的句子生成期退回收短
        if overs and semantic_left:
            semantic_rejections += 1
            attempts[-1]["rejected_by"] = "budget"
            attempts[-1]["rewrite_feedback"] = [
                f"- 「{item['text']}…」估算 {item['est_s']}s，画面窗只有 "
                f"{item['avail_s']}s（约 {item['target_chars']} 字）——收短到 "
                f"{item['target_chars']} 字左右，删修饰不删事实"
                for item in overs
            ]
            script = None
            continue
        attempts[-1]["budget_overs"] = overs
        # 复述闸（听懂了没，比评分狠）：无上下文观众闭卷复述 + 感受流缺口分类处置。
        # 文字稿=钩子+正文+引导（观众听到的全文）——钩子直接影响「主角目标明确」判定
        if retell_on:
            try:
                retell_report = retell_check(
                    "\n".join(
                        part
                        for part in (
                            script.hook,
                            *(seg.text for seg in script.segments),
                            script.cta,
                        )
                        if part.strip()
                    ),
                    llm,
                )
            except Exception:  # noqa: BLE001 - 复述是增益不是依赖：失败安静跳过
                retell_report = None
            if retell_report is not None:
                attempts[-1]["retell"] = retell_report.to_json()
                if not retell_report.passed and semantic_left:
                    semantic_rejections += 1
                    attempts[-1]["rejected_by"] = "retell"
                    items = [
                        "- 优先删和拆，不是补：密度超了删次要信息，不写解释句"
                    ]
                    if not retell_report.has_goal:
                        items.append("- 开场三句内让观众明确主角想要什么")
                    if not retell_report.has_suspense:
                        items.append(
                            "- 结尾一句点明主角此刻处境与下一步悬念（不剧透结局）"
                        )
                    items.extend(
                        f"- 「{c['quote']}」："
                        f"{_RETELL_FIX_BY_ISSUE.get(c['issue'], _RETELL_FIX_BY_ISSUE['unclear'])}"
                        for c in retell_report.confusions[:4]
                    )
                    attempts[-1]["rewrite_feedback"] = items
                    script = None
                    continue
        # 六维语义评审（软批注）：≥8 干净 / 7~8 批注 / <7 拒稿走语义预算
        if judge_on and settings is not None:
            verdict = variant_scoring.score_one(
                _script_as_plan_like(script),
                "整篇解说线",
                settings,
                trace_dir=trace_path.parent if trace_path is not None else None,
            )
            if verdict is not None:
                total = float(verdict.get("total") or 0.0)
                attempts[-1]["judge"] = {
                    "total": total,
                    "suggestion": str(verdict.get("suggestion") or "").strip(),
                    "tier": (
                        "clean"
                        if total >= _JUDGE_NOTE_BELOW
                        else ("note" if total >= _JUDGE_REJECT_BELOW else "reject")
                    ),
                }
                if (
                    total < _JUDGE_REJECT_BELOW
                    and semantic_left
                ):
                    semantic_rejections += 1
                    attempts[-1]["rejected_by"] = "judge"
                    suggestion = str(verdict.get("suggestion") or "").strip()
                    attempts[-1]["rewrite_feedback"] = (
                        [f"- 评审建议：{suggestion}"] if suggestion else []
                    )
                    script = None
                    continue
        dump_trace(trace_path, {"attempts": attempts, "script": script.model_dump()})
        return script
    tail = attempts[-1] if attempts else {}
    raise ValueError(f"整篇线 {_MAX_ATTEMPTS} 轮未产出合格解说（最后状态：{tail}）")


def _line_fields(raw: Any) -> FlowLine:
    """一行 JSON → FlowLine（quote/text/highlight；highlight 只在正文行有意义）。"""
    if not isinstance(raw, dict):
        raise ValueError("锚定句不是 JSON 对象")
    return FlowLine(
        quote=str(raw.get("quote") or ""),
        text=str(raw.get("text") or ""),
        highlight=bool(raw.get("highlight")),
    )


def _hook_line(raw: Any) -> HookLine:
    """钩子行：正文行字段 + 可选备选候选（多候选挑优）。"""
    line = _line_fields(raw)
    alt_raw = raw.get("alt") if isinstance(raw, dict) else None
    alt = _line_fields(alt_raw) if isinstance(alt_raw, dict) else None
    return HookLine(quote=line.quote, text=line.text, alt=alt)
