"""提示词 → 生成内容 审查 / 复核 / 持续优化闭环。

设计意图（对照 2026-10-09 提示词重写）：
- 每条审计规则都「锚定回 prompt 原文」——finding.prompt_quote 直接引用
  _STRUCTURE_PROMPT / _FUND_BASE / _FUND_FULL_ONLY / _FUND_SLOT_ONLY 里的原句，
  改 prompt 导致规则失效时，这里会先红，而不是默默放行。
- 区分 hard（违反即不合格，对应 prompt「结构硬约束」「零容忍」）与 soft
  （手艺方向，标「需人工复核」，绝不给虚高分）。
- 不堆虚荣指标：没有「综合得分」，只有「哪条规则没守住 + 原文在哪」。

典型用法见 tools/narration_review.py（CLI）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    rule_id: str
    layer: str          # structure | fund_base | fund_full | fund_slot | copy
    severity: str       # hard | soft
    passed: bool
    message: str
    location: str = ""              # 出问题的字段路径，如 segment[3].text
    prompt_quote: str = ""          # 该规则对应的 prompt 原文（溯源）
    needs_human: bool = False       # soft 规则默认需人工复核


@dataclass
class ReviewReport:
    target: str                     # "script" | "copy"
    findings: list[Finding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_fails(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "hard"]

    @property
    def soft_flags(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "soft"]

    @property
    def passed(self) -> bool:
        return not self.hard_fails

    def summary_line(self) -> str:
        return (
            f"[{self.target}] hard_fail={len(self.hard_fails)} "
            f"soft_flag={len(self.soft_flags)} "
            f"verdict={'REJECT' if self.hard_fails else 'PASS'}"
        )


# ---------------------------------------------------------------------------
# 通用侦探（heuristics）
# ---------------------------------------------------------------------------

_METANARRATIVE_RE = re.compile(r"第\s*\d+\s*集|画面里|镜头|素材|转写|台词前|字幕")
_ARABIC_NUM_RE = re.compile(r"\d{2,}")          # 两位及以上阿拉伯数字（应写中文）
_PERSON_FIRST = ("我", "咱们", "咱")
_PERSON_SECOND = ("你", "你们", "您")
_SPEAKER_LABEL_RE = re.compile(r"\[角色[^\]]*\]")
_FORBIDDEN_CTA_RE = re.compile(r"关注|点赞|收藏|二维码")
_SUSPECT_EMPTY_RE = re.compile(r"他竟然|竟然|居然|后续更精彩|更精彩")
_IDENTITY_DEATH_RE = re.compile(r"死|亡|杀|真实身份|竟是|身份竟|公主|皇子|王爷|娘娘|陛下|皇帝")
# 具体反差锚点（除数字/身份/生死外的「物件/信物」类，避免漏判好 hook）
_CONCRETE_OBJECT_RE = re.compile(
    r"婚书|玉佩|信物|刀|剑|银子|银两|金|毒|血|诏|旨|印|契|账|银票|地契|书信|遗嘱|密函"
)
# 编造外实体粗筛：仅盯「姓氏+称谓」式专名（百家姓首字 + 常见称谓尾字），大幅降噪；
# 仍标 soft+需人工，因为中文无大小写，纯靠字形无法 100% 判定。
_SURNAME = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹"
    "严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳"
)
_FABRIC_RE = re.compile(r"^([" + _SURNAME + r"])[爷娘姐妹哥弟子女君主公婆夫郎妃后王帝翁侄]$")
_CLICK_RE = re.compile(r"点击|左下角|右下角")
_WATCH_ALL_RE = re.compile(r"免费|立即观看|看全集|全集")
# 揭晓腔（全篇禁，不只 hook）：事后抖包袱式「竟是/竟然/居然/原来/没想到」
_REVEAL_RE = re.compile(r"竟是|竟然|居然|原来如此|没想到|万万没")
# 可疑数量/专名锚点：无转写时也要标软风险（arabic 数 + 中文数量/称谓式专名）
_QUANTITY_RE = re.compile(
    r"\d{2,}|[零〇一二三四五六七八九十百千万亿]+\s*(两|金银|斤|块|岁|人|个|贯|锭|两银)"
)
# 转写外身份/称号类（如「九千岁/王爷/公主」）——出现即高疑似编造，需对照转写
_TITLE_CLAIM_RE = re.compile(r"九千岁|王爷|公主|皇子|娘娘|陛下|皇帝|宰相|丞相|将军|圣上")


def _count(text: str, needles: Iterable[str]) -> int:
    return sum(text.count(n) for n in needles)


def _has_chinese_num(text: str) -> bool:
    # 粗判：出现「两/三/四/五/六/七/八/九/十/百/千/万/亿」任一即视为已中文化
    return bool(re.search(r"[两三四五六七八九十百千万亿零〇]", text))


# ---------------------------------------------------------------------------
# 剧本（scriptwriter 链路）审查
# ---------------------------------------------------------------------------


def review_script(
    script: dict[str, Any],
    transcript: list[dict[str, Any]] | None = None,
) -> ReviewReport:
    """审查 _STRUCTURE_PROMPT + 基本功层（full）约束。

    transcript: 清洗后的带时间戳台词，字段 episode/start/end/speaker/text。
    用于时间上界、互不重叠、声纹换名、编造外事件等可验证项。
    """
    findings: list[Finding] = []
    transcript = transcript or []

    # 时间上界表：episode -> 该集最大 end
    ep_bounds: dict[int, float] = {}
    for seg in transcript:
        ep = int(seg.get("episode", 1))
        ep_bounds[ep] = max(ep_bounds.get(ep, 0.0), float(seg.get("end", 0.0)))

    # —— JSON 只输出（结构硬约束尾句）——
    findings.append(Finding(
        "STRUCT_JSON_ONLY", "structure", "hard", True,
        "输出为合法 JSON（解析通过）", prompt_quote="只输出 JSON，不要多余文字。",
    ))

    segs = script.get("segments", []) if isinstance(script, dict) else []
    hook = (script.get("hook", "") if isinstance(script, dict) else "") or ""
    cta = (script.get("cta", "") if isinstance(script, dict) else "") or ""

    # —— 每片段带 episode（结构硬约束首条）——
    missing_ep = [i for i, s in enumerate(segs) if "episode" not in s or s.get("episode") is None]
    findings.append(Finding(
        "STRUCT_EPISODE_REQUIRED", "structure", "hard",
        not missing_ep,
        "每个片段都带 episode" if not missing_ep else f"缺 episode 的片段下标：{missing_ep}",
        location="segments" if missing_ep else "",
        prompt_quote="每个片段都必须带 episode，一个都不能漏；",
    ))

    # —— 时间上界 + 同集递增互不重叠 ——
    bound_viol, overlap_viol = [], []
    last_end_per_ep: dict[int, float] = {}
    for i, s in enumerate(segs):
        ep = int(s.get("episode", 1))
        start, end = float(s.get("start", 0)), float(s.get("end", 0))
        ub = ep_bounds.get(ep)
        if ub is not None and end > ub + 1e-6:
            bound_viol.append(i)
        prev = last_end_per_ep.get(ep)
        if prev is not None and start < prev - 1e-6:
            overlap_viol.append(i)
        last_end_per_ep[ep] = max(prev if prev is not None else 0.0, end)
    findings.append(Finding(
        "STRUCT_TIME_BOUNDS", "structure", "hard",
        not bound_viol,
        "start/end 均未超过所在集上界" if not bound_viol else f"超界片段下标：{bound_viol}",
        location="segments" if bound_viol else "",
        prompt_quote="start/end 取自转写台词的时间区间，不得超过该集上界；",
    ))
    findings.append(Finding(
        "STRUCT_NON_OVERLAP", "structure", "hard",
        not overlap_viol,
        "同集内按时间递增且互不重叠" if not overlap_viol else f"重叠/倒序片段下标：{overlap_viol}",
        location="segments" if overlap_viol else "",
        prompt_quote="同集内按时间递增且互不重叠；",
    ))

    # —— hook：空泛悬念（硬，零容忍目标） vs 无具体锚点（软，启发式不可全判）——
    hook_empty = bool(_SUSPECT_EMPTY_RE.search(hook))
    hook_has_anchor = bool(
        _has_chinese_num(hook)
        or _ARABIC_NUM_RE.search(hook)
        or _IDENTITY_DEATH_RE.search(hook)
        or _CONCRETE_OBJECT_RE.search(hook)
        or len(hook) >= 12  # 够长的 hook 通常已带具体内容，不再误杀
    )
    findings.append(Finding(
        "STRUCT_HOOK_FACT", "structure", "hard",
        not hook_empty,
        "hook 非「他竟然…」式空泛悬念" if not hook_empty else "hook 为空泛悬念（'他竟然'式）",
        location="hook" if hook_empty else "",
        prompt_quote="hook 必须含一个具体反差事实（身份/生死/数字），禁「他竟然…」式空泛悬念；",
    ))
    findings.append(Finding(
        "STRUCT_HOOK_ANCHOR", "structure", "soft",
        hook_has_anchor,
        "hook 含具体反差锚点（数字/身份/生死/物件）" if hook_has_anchor
        else "hook 未检出具体反差锚点（可能偏虚，需人工复核）",
        location="hook" if not hook_has_anchor else "",
        prompt_quote="hook 必须含一个具体反差事实（身份/生死/数字）",
        needs_human=True,
    ))

    # —— cta 三段式 + 禁空喊 ——
    cta_forbidden = bool(_FORBIDDEN_CTA_RE.search(cta))
    cta_has_click = bool(_CLICK_RE.search(cta))
    cta_has_watch = bool(_WATCH_ALL_RE.search(cta))
    findings.append(Finding(
        "STRUCT_CTA_FORBIDDEN", "structure", "hard",
        not cta_forbidden,
        "cta 未空喊关注/点赞/收藏/二维码"
        if not cta_forbidden
        else "cta 出现禁用引导词（关注/点赞/收藏/二维码）",
        location="cta" if cta_forbidden else "",
        prompt_quote="禁剧透最大反转、禁空喊关注/点赞/收藏/二维码；",
    ))
    findings.append(Finding(
        "STRUCT_CTA_THREE_PART", "structure", "soft",
        cta_has_click and cta_has_watch,
        "cta 含『点击引导 + 看全集』三段式要素" if (cta_has_click and cta_has_watch)
        else f"cta 三段式不全（点击={cta_has_click} 看全集={cta_has_watch}）",
        location="cta" if not (cta_has_click and cta_has_watch) else "",
        prompt_quote=(
            "cta 必须是三段式转化引导（悬念半句+「点击左下角」+「免费/立即观看全集」，可带剧名）"
        ),
        needs_human=True,
    ))

    # —— 声纹标签 [角色X] 应换真名 ——
    unresolved = []
    for i, s in enumerate(segs):
        t = s.get("text", "") or ""
        if _SPEAKER_LABEL_RE.search(t):
            unresolved.append(i)
    findings.append(Finding(
        "FUND_SPEAKER_RESOLVE", "fund_base", "soft",
        not unresolved,
        "声纹标签 [角色X] 已全部换成推断真名" if not unresolved
        else f"仍存在未解析声纹标签的片段下标：{unresolved}（应换真名或保留原标签并说明）",
        location="segments" if unresolved else "",
        prompt_quote="台词前的[角色X]是声纹聚类标签…写文案时换成你从称呼与剧情推断出的真名，推断不出再保留原标签；",
        needs_human=True,
    ))

    # —— 禁元叙述（零容忍）——
    meta_hits = []
    for key, txt in (("hook", hook), ("cta", cta)):
        if _METANARRATIVE_RE.search(txt):
            meta_hits.append(key)
    for i, s in enumerate(segs):
        if _METANARRATIVE_RE.search(s.get("text", "") or ""):
            meta_hits.append(f"segment[{i}]")
    findings.append(Finding(
        "FUND_NO_METANARRATIVE", "fund_base", "hard",
        not meta_hits,
        "无元叙述字眼（第X集/画面里/镜头/素材/转写）"
        if not meta_hits
        else f"出现元叙述：{meta_hits}",
        location=";".join(meta_hits) if meta_hits else "",
        prompt_quote="禁元叙述（零容忍）：…「第X集」「画面里」「镜头」「素材」这类字眼一个不许有…",
    ))

    # —— 数字写中文（软）——
    arabic_in_text = []
    for i, s in enumerate(segs):
        t = s.get("text", "") or ""
        if _ARABIC_NUM_RE.search(t):
            arabic_in_text.append(i)
    findings.append(Finding(
        "FUND_NUMERALS_CN", "fund_base", "soft",
        not arabic_in_text,
        "解说文案中未见阿拉伯数字（已中文化）" if not arabic_in_text
        else f"含阿拉伯数字的片段下标：{arabic_in_text}（应写中文）",
        location="segments" if arabic_in_text else "",
        prompt_quote="数字一律写中文（两千斤/八年/四十七块）…",
        needs_human=True,
    ))

    # —— 人称二选一（软，启发式）——
    fp = _count(hook + cta + " ".join(s.get("text", "") for s in segs), _PERSON_FIRST)
    sp = _count(hook + cta + " ".join(s.get("text", "") for s in segs), _PERSON_SECOND)
    findings.append(Finding(
        "FUND_PERSON_CONSISTENT", "fund_base", "soft",
        not (fp > 0 and sp > 0),
        "人称未混用（一/二人称未同时出现）" if not (fp > 0 and sp > 0)
        else f"一/二人称同时出现（第一={fp} 第二={sp}），可能中途切换",
        prompt_quote="人称二选一并全篇统一，禁止中途切换。",
        needs_human=True,
    ))

    # —— 编造转写外事件（软，靠 transcript 粗查「姓氏+称谓」式专名）——
    if transcript:
        transcript_text = "".join(seg.get("text", "") for seg in transcript)
        fabricated = []
        for i, s in enumerate(segs):
            novel = [
                m.group(0) for m in _FABRIC_RE.finditer(s.get("text", "") or "")
                if m.group(0) not in transcript_text
            ]
            if novel:
                fabricated.append((i, novel[:3]))
        findings.append(Finding(
            "FUND_NO_FABRICATION", "fund_base", "soft",
            not fabricated,
            "未检出明显转写外专名" if not fabricated else f"疑似编造专名：{fabricated[:3]}",
            prompt_quote="所有情节、细节、台词必须来自给定转写，禁止编造转写外的事件或设定；",
            needs_human=True,
        ))

    # —— 揭晓腔（全篇禁，软+需人工）：无转写也要抓「竟是/竟然」式抖包袱 ——
    reveal_hits = []
    for key, txt in (("hook", hook), ("cta", cta)):
        if _REVEAL_RE.search(txt):
            reveal_hits.append(key)
    for i, s in enumerate(segs):
        if _REVEAL_RE.search(s.get("text", "") or ""):
            reveal_hits.append(f"segment[{i}]")
    findings.append(Finding(
        "FUND_NO_REVEAL_TELL", "fund_base", "soft",
        not reveal_hits,
        "全篇无「竟是/竟然」式揭晓腔"
        if not reveal_hits
        else f"出现揭晓腔：{reveal_hits}（应在画面里自然带出，不靠'竟是'抖包袱）",
        location=";".join(reveal_hits) if reveal_hits else "",
        prompt_quote="全篇禁揭晓腔：禁「竟是/竟然/居然/原来/没想到」式事后揭秘——解说在讲正在发生的事，不是抖包袱；",
        needs_human=True,
    ))

    # —— 可疑数量/称号锚点（软+需人工）：转写外「八千两/九千岁」式硬锚点，需对照核实 ——
    invent_hits = []
    for i, s in enumerate(segs):
        t = s.get("text", "") or ""
        q = _QUANTITY_RE.search(t)
        title = _TITLE_CLAIM_RE.search(t)
        if q or title:
            invent_hits.append((i, (q.group(0) if q else "") or (title.group(0) if title else "")))
    findings.append(Finding(
        "FUND_NO_INVENTED_ANCHOR", "fund_base", "soft",
        not invent_hits,
        "未检出可疑转写外数量/称号锚点"
        if not invent_hits
        else f"疑似转写外硬锚点：{invent_hits[:3]}（须原样出自转写，禁止为凑锚点发明）",
        location=";".join(f"segment[{i}]" for i, _ in invent_hits) if invent_hits else "",
        prompt_quote="真实锚点（年份/金额/物件/称呼）只能原样摘自转写，转写里没有就少写，禁止为凑数发明；",
        needs_human=True,
    ))

    # —— 跨集因果桥接（软+需人工）：涉及多集时必须人工确认前集段尾已说破因果 ——
    eps_present = sorted({int(s.get("episode", 1)) for s in segs})
    cross = len(eps_present) > 1
    findings.append(Finding(
        "FUND_CROSS_EPISODE_BRIDGE", "fund_full", "soft",
        not cross,
        "本稿未跨集（无需桥接）"
        if not cross
        else f"跨集涉及 {eps_present}，需人工确认每处跳集前段尾已把跨集因果说破",
        location="segments" if cross else "",
        prompt_quote="换集优先取相邻集，大跨度跳集只许跳往确有关键爆点的集，且前集段尾必须把跨集因果说破；",
        needs_human=cross,
    ))

    return ReviewReport(target="script", findings=findings,
                        meta={"n_segments": len(segs), "ep_bounds": ep_bounds})


# ---------------------------------------------------------------------------
# 逐槽文案（copywriter 链路）审查
# ---------------------------------------------------------------------------


def review_copy(
    lines: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    mode: str = "",
) -> ReviewReport:
    """审查 copywriter 结构指令 + 逐槽基本功约束。

    lines: 模型输出 [{"id","text"}]；slots: 编排器给的 [{"id","task","start","end","lines"}]。
    """
    findings: list[Finding] = []
    from dramaclip.engines.narration.copywriter import _line_cap_of
    cap = _line_cap_of(mode)

    line_ids = [line.get("id") for line in lines]
    slot_ids = [slot.get("id") for slot in slots]

    # —— 覆盖全部槽位 id（硬性要求一字不差）——
    missing = [sid for sid in slot_ids if sid not in line_ids]
    findings.append(Finding(
        "COPY_COVER_ALL_IDS", "copy", "hard",
        not missing,
        "lines 覆盖全部槽位 id" if not missing else f"漏覆盖槽位：{missing}",
        location="lines" if missing else "",
        prompt_quote="lines 必须覆盖全部槽位 id；",
    ))

    # —— 每条不超过行长上限 ——
    over = [
        (line.get("id"), len(line.get("text", "")))
        for line in lines
        if len(line.get("text", "")) > cap
    ]
    findings.append(Finding(
        "COPY_LINE_CAP", "copy", "hard",
        not over,
        f"每条均 ≤ {cap} 字" if not over else f"超长：{over}",
        location="lines" if over else "",
        prompt_quote=f"每条不超过 {cap} 字；",
    ))

    # —— 禁元叙述（零容忍，同样适用填词）——
    meta_hits = [
        line.get("id")
        for line in lines
        if _METANARRATIVE_RE.search(line.get("text", "") or "")
    ]
    findings.append(Finding(
        "COPY_NO_METANARRATIVE", "copy", "hard",
        not meta_hits,
        "无元叙述字眼" if not meta_hits else f"出现元叙述的槽位：{meta_hits}",
        location=";".join(str(h) for h in meta_hits) if meta_hits else "",
        prompt_quote="禁元叙述（零容忍）：…「第X集」「画面里」「镜头」「素材」这类字眼一个不许有…",
    ))

    # —— 完成「要做的事」（软：空文本 / 明显跑题无法全判，标需人工）——
    empty = [line.get("id") for line in lines if not (line.get("text") or "").strip()]
    findings.append(Finding(
        "COPY_DOES_THE_JOB", "fund_slot", "soft",
        not empty,
        "无空文案槽位" if not empty else f"空文案槽位：{empty}（未完成任务契约）",
        location=";".join(str(e) for e in empty) if empty else "",
        prompt_quote="文案必须完成该槽位的「要做的事」，不得答非所问；",
        needs_human=True,
    ))

    # —— 声纹换名（软，同剧本）——
    unresolved = [
        line.get("id")
        for line in lines
        if _SPEAKER_LABEL_RE.search(line.get("text", "") or "")
    ]
    findings.append(Finding(
        "COPY_SPEAKER_RESOLVE", "fund_slot", "soft",
        not unresolved,
        "声纹标签已换真名" if not unresolved else f"未解析声纹标签槽位：{unresolved}",
        prompt_quote="台词前的[角色X]是声纹聚类标签…写文案时换成你从称呼与剧情推断出的真名",
        needs_human=True,
    ))

    return ReviewReport(target="copy", findings=findings,
                        meta={"mode": mode, "cap": cap, "n_lines": len(lines)})


# ---------------------------------------------------------------------------
# 报告渲染 + 持续优化
# ---------------------------------------------------------------------------


def format_report(report: ReviewReport) -> str:
    out = [f"# 审查报告 · {report.target}  ({report.summary_line()})", ""]
    if report.hard_fails:
        out.append("## ❌ 硬约束未守住（REJECT）")
        for f in report.hard_fails:
            loc = f" @ {f.location}" if f.location else ""
            out.append(f"- **{f.rule_id}**{loc}：{f.message}")
            out.append(f"  - 规则原文：_{f.prompt_quote}_")
        out.append("")
    if report.soft_flags:
        out.append("## ⚠️ 手艺方向需复核（soft，非一票否决）")
        for f in report.soft_flags:
            loc = f" @ {f.location}" if f.location else ""
            tag = "（需人工复核）" if f.needs_human else ""
            out.append(f"- **{f.rule_id}**{loc}：{f.message} {tag}")
            out.append(f"  - 规则原文：_{f.prompt_quote}_")
        out.append("")
    ok = [f for f in report.findings if f.passed]
    out.append(f"## ✅ 已守住 {len(ok)}/{len(report.findings)} 条")
    return "\n".join(out)


# 把 finding 展平为可聚合的记录
def _flat(findings: list[Finding], sample_id: str) -> list[dict[str, Any]]:
    return [{"sample_id": sample_id, **asdict(f)} for f in findings]


def propose_prompt_tweaks(
    records: list[dict[str, Any]], min_hits: int = 2
) -> list[dict[str, Any]]:
    """持续优化：从累积的审查记录里找「反复失守」的硬规则，给出 prompt 加固建议。

    只建议、不自动改 prompt（避免回归 354 条 substring 断言）。每条建议带：
    rule_id / 失守次数 / 当前 prompt 原文 / 建议动作。
    """
    from collections import Counter

    fail: Counter[str] = Counter()
    quote: dict[str, str] = {}
    for r in records:
        if not r["passed"] and r["severity"] == "hard":
            fail[r["rule_id"]] += 1
            quote.setdefault(r["rule_id"], r["prompt_quote"])
    proposals: list[dict[str, Any]] = []
    for rid, n in fail.items():
        if n >= min_hits:
            proposals.append({
                "rule_id": rid,
                "fail_count": n,
                "current_prompt": quote.get(rid, ""),
                "action": (
                    "该硬规则反复被突破 → 在对应 prompt 段加重语气/补反例，"
                    "或在重试强化里显式点名此规则（见 _FORMAT_REINFORCEMENT 模式）。"
                ),
            })
    proposals.sort(key=lambda proposal: int(proposal["fail_count"]), reverse=True)
    return proposals
