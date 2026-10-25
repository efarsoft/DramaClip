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

from dramaclip.engines.narration.prompt_rules import RULE_TEXTS as _RULES

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
    # 可执行修法（指出问题不算批评，批评必须带怎么改——重掷/重写循环吃这条；
    # 给不出具体修法的问题就别填，空串=只有定位没有修法）
    fix_hint: str = ""


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

# 「第X集」要同时认阿拉伯与中文数词：数字中文化收口（numerals）先于内联审查跑，
# 「第3集」到 audit 手里已经是「第三集」——只认 \d 的话这条零容忍硬规则对该形态恒为死规则。
_METANARRATIVE_RE = re.compile(
    r"第[零〇一二三四五六七八九十百千两\d]+\s*集|画面里|镜头|素材|转写|台词前|字幕"
)
_ARABIC_NUM_RE = re.compile(r"\d{2,}")          # 两位及以上阿拉伯数字（应写中文）
_PERSON_FIRST = ("我", "咱们", "咱")
_PERSON_SECOND = ("你", "你们", "您")
_SPEAKER_LABEL_RE = re.compile(r"\[角色[^\]]*\]")
_FORBIDDEN_CTA_RE = re.compile(r"关注|点赞|收藏|二维码")
# 只拦空钩模式；裸「竟然/居然」可带实体事实（揭晓词已由业主裁决放开），
# 实体锚由 HOOK_ANCHOR 软检兜底
_SUSPECT_EMPTY_RE = re.compile(r"他竟然|后续更精彩|更精彩")
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


_EMOTION_BEAT_RE = re.compile(
    r"发烫|凉透|发凉|攥紧|指节|眼眶|鼻酸|哽咽|发抖|深吸|咬牙|咬着|僵在|红着眼|心[一-龥]"
)
_IMAGE_PHRASE_RE = re.compile(
    r"[一二两三四五六七八九十百千万零]{1,4}[斤吨年个月天夜尺丈里步块两]{1}"
)


def _narrative_texture_findings(segs: list[dict[str, Any]]) -> list[Finding]:
    """叙事质地组（全为软+需人工）：句式/意象/情绪落点的密度与去重。

    判据锚定 FUND_FULL_ONLY「叙事质地」段原句；纯启发式，宁可漏报不误伤——
    soft+needs_human 的语义是「人耳复核」，不是不合格。
    """
    texts = [
        str(s.get("text") or "")
        for s in segs
        if isinstance(s, dict) and str(s.get("text") or "").strip()
    ]
    findings: list[Finding] = []

    # 只剥收尾引号/括号，问号本体保留在串尾参与判定
    suspensive = [i for i, text in enumerate(texts) if text.rstrip("”’」』\"')").endswith("？")]
    findings.append(Finding(
        "NARR_SUSPENSE_QUOTA", "fund_full", "soft",
        len(suspensive) <= 2,
        "问号收尾配额内" if len(suspensive) <= 2
        else f"以问号收尾的段 {len(suspensive)} 个（下标 {suspensive}）——悬问连发节拍单一",
        location="segments" if suspensive else "",
        prompt_quote=_RULES["question_ending_cap"],
        needs_human=True,
    ))

    phrase_locations: dict[str, list[int]] = {}
    for i, text in enumerate(texts):
        for match in _IMAGE_PHRASE_RE.finditer(text):
            phrase_locations.setdefault(match.group(0), []).append(i)
    over = {phrase: locs for phrase, locs in phrase_locations.items() if len(locs) > 2}
    findings.append(Finding(
        "NARR_IMAGE_QUOTA", "fund_full", "soft",
        not over,
        "核心意象点名在配额内" if not over
        else f"同一「数字+量词」意象点名超两次：{over}——再提用代称或只讲新后果",
        location=";".join(sorted(over)) if over else "",
        prompt_quote=_RULES["core_motif_cap"],
        needs_human=True,
    ))

    window = 6
    beatless = [
        start
        for start in range(0, max(len(texts) - window + 1, 0))
        if not any(_EMOTION_BEAT_RE.search(texts[start + k]) for k in range(window))
    ]
    findings.append(Finding(
        "NARR_EMOTION_BEAT", "fund_full", "soft",
        not beatless,
        "情绪落点分布健康" if not beatless
        else f"连续 {window} 段无体感/心理落点的窗口：{beatless[:3]}"
        "——事件复述连排，情绪共鸣偏薄",
        location=";".join(f"segments[{i}]" for i in beatless[:3]) if beatless else "",
        prompt_quote=_RULES["body_sensation_sparse"],
        needs_human=True,
    ))
    findings.append(_phrase_monotony_finding(segs))
    return findings


_TAIL_PUNCT = "。，、；：！？…—,,.;:!?'\"」』）)>》"


def _phrase_monotony_finding(segs: list[dict[str, Any]]) -> Finding:
    """句式雷同三连（软+需人工）：连续 ≥3 段同头或同尾＝模板感。

    批1（e888a42）宣称落了「句式雷同」检测，实际只落了问号配额/意象配额/情绪
    落点三条，原始病灶「同款句式三连（模板感）」始终无判据——这里补上：开头
    2 字或去尾标点后收尾 2 字，连续三段全同即点名。文案层的「相邻槽位禁止
    同款收尾」承诺同用这条判据兜底。
    """
    texts = [str(s.get("text", "") or "").strip() for s in segs]
    heads = [t[:2] for t in texts if len(t) >= 2]
    tails = [t.rstrip(_TAIL_PUNCT)[-2:] for t in texts if len(t) >= 2]
    hits: list[str] = []
    for i in range(max(len(heads) - 2, 0)):
        if heads[i] and heads[i] == heads[i + 1] == heads[i + 2]:
            hits.append(f"段{i + 1}-{i + 3} 同头「{heads[i]}」")
        if tails[i] and tails[i] == tails[i + 1] == tails[i + 2]:
            hits.append(f"段{i + 1}-{i + 3} 同尾「{tails[i]}」")
    return Finding(
        "NARR_PHRASE_MONOTONY", "fund_full", "soft",
        not hits,
        "未检出句式雷同三连"
        if not hits
        else f"句式雷同三连：{'；'.join(hits[:4])}——换句式或换收尾，模板感是划走开关",
        location="segments",
        prompt_quote=_RULES["no_same_ending_adjacent"],
        needs_human=bool(hits),
    )


def _script_shape_findings(segs: list[dict[str, Any]]) -> list[Finding]:
    """结构组一：JSON 只输出（尾句）+ 每片段带 episode（首条）+ 跨集跳变点名（软）。"""
    findings: list[Finding] = []
    findings.append(Finding(
        "STRUCT_JSON_ONLY", "structure", "hard", True,
        "输出为合法 JSON（解析通过）", prompt_quote=_RULES["json_only"],
    ))
    missing_ep = [i for i, s in enumerate(segs) if "episode" not in s or s.get("episode") is None]
    findings.append(Finding(
        "STRUCT_EPISODE_REQUIRED", "structure",
        "hard",
        not missing_ep,
        "每个片段都带 episode" if not missing_ep else f"缺 episode 的片段下标：{missing_ep}",
        location="segments" if missing_ep else "",
        prompt_quote=_RULES["every_segment_episode"],
    ))
    findings.append(_episode_jump_finding(segs))
    return findings


def _episode_jump_finding(segs: list[dict[str, Any]]) -> Finding:
    """跨集跳变点名（软+需人工）：相邻段集号跨度 >1 即「相邻优先」承诺失守。

    prompt 承诺「换集优先取相邻集，大跨度跳集只许跳往确有关键爆点的集」——
    此前验证侧零覆盖，全靠模型自觉。跨度可算：点名交给人工判断「确有关键爆点」
    是否成立，不当 hard（大跨度跳集是 prompt 允许的例外路径，只是要过人眼）。
    """
    episodes = [int(s.get("episode", 1)) for s in segs]
    jumps: list[str] = []
    for i in range(len(episodes) - 1):
        span = abs(episodes[i + 1] - episodes[i])
        if span > 1:
            jumps.append(
                f"段{i + 1}→{i + 2}（第{episodes[i]}集→第{episodes[i + 1]}集，跨 {span} 集）"
            )
    return Finding(
        "STRUCT_EPISODE_JUMP", "structure", "soft",
        not jumps,
        "换集均为相邻集"
        if not jumps
        else f"存在大跨度跳集：{'；'.join(jumps[:4])}——须逐一确认目标集确有关键爆点",
        location="segments",
        prompt_quote=(
            "换集优先取相邻集，大跨度跳集只许跳往确有关键爆点的集，"
            "且前集段尾必须把跨集因果说破，禁止无因果跳切；"
        ),
        needs_human=bool(jumps),
    )


def _script_time_findings(
    segs: list[dict[str, Any]], ep_bounds: dict[int, float]
) -> list[Finding]:
    """结构组二：时间上界 + 同集递增互不重叠。"""
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
    return [
        Finding(
            "STRUCT_TIME_BOUNDS", "structure", "hard",
            not bound_viol,
            "start/end 均未超过所在集上界" if not bound_viol else f"超界片段下标：{bound_viol}",
            location="segments" if bound_viol else "",
            prompt_quote=_RULES["time_within_transcript"],
        ),
        Finding(
            "STRUCT_NON_OVERLAP", "structure", "hard",
            not overlap_viol,
            "同集内按时间递增且互不重叠"
            if not overlap_viol else f"重叠/倒序片段下标：{overlap_viol}",
            location="segments" if overlap_viol else "",
            prompt_quote=_RULES["timeline_sorted_no_overlap"],
        ),
    ]


def _hook_findings(hook: str) -> list[Finding]:
    """结构组三：空泛悬念（硬，零容忍目标） vs 无具体锚点（软，启发式不可全判）。"""
    hook_empty = bool(_SUSPECT_EMPTY_RE.search(hook))
    hook_has_anchor = bool(
        _has_chinese_num(hook)
        or _ARABIC_NUM_RE.search(hook)
        or _IDENTITY_DEATH_RE.search(hook)
        or _CONCRETE_OBJECT_RE.search(hook)
        or len(hook) >= 12  # 够长的 hook 通常已带具体内容，不再误杀
    )
    return [
        Finding(
            "STRUCT_HOOK_FACT", "structure", "hard",
            not hook_empty,
            "hook 非「他竟然…」式空泛悬念" if not hook_empty else "hook 为空泛悬念（'他竟然'式）",
            location="hook" if hook_empty else "",
            prompt_quote=_RULES["hook_concrete_contrast"],
        ),
        Finding(
            "STRUCT_HOOK_ANCHOR", "structure", "soft",
            hook_has_anchor,
            "hook 含具体反差锚点（数字/身份/生死/物件）" if hook_has_anchor
            else "hook 未检出具体反差锚点（可能偏虚，需人工复核）",
            location="hook" if not hook_has_anchor else "",
            prompt_quote=_RULES["hook_concrete_contrast"],
            needs_human=True,
        ),
    ]


def _hook_payoff_finding(hook: str, segs: list[dict[str, Any]]) -> Finding:
    """钩子兑现（软+需人工）：钩子抛出的具体锚（物件/数字/人名/身份）至少一个在正文再现。

    标题党一次就伤账号权重：钩子说「他背着一口锅」，正文再没提锅＝观众被骗一次。
    锚点抓不到（纯抽象/纯情绪钩子）不判——宁漏勿冤；锚点宽松匹配（正文出现
    即算兑现），抓「彻底悬空」的硬伤，不做精细的兑现度评分。
    """
    body = "".join(str(s.get("text", "") or "") for s in segs)
    anchors: list[str] = []
    for regex in (
        _CONCRETE_OBJECT_RE,
        _TITLE_CLAIM_RE,
        re.compile(r"[零〇一二三四五六七八九十百千万两]+\s*[斤吨年个月天夜尺丈里步块两银两贯]"),
        re.compile(r"[" + _SURNAME + r"][一-龥]{1,3}"),
    ):
        for match in regex.finditer(hook):
            text = match.group(0)
            if len(text) >= 2:
                anchors.append(text)
    payoff = any(anchor in body for anchor in anchors) if anchors else True
    detail = "；".join(anchors[:5]) if anchors else ""
    return Finding(
        "FUND_HOOK_PAYOFF", "fund_base", "soft",
        payoff,
        "钩子锚点在正文有兑现"
        if payoff
        else f"钩子抛出的锚点（{detail}）正文全部未再现——承诺的悬念没兑现＝标题党，"
             "要么正文给答案，要么钩子换锚",
        location="hook" if not payoff else "",
        prompt_quote=_RULES["hook_concrete_contrast"],
        needs_human=not payoff,
    )


def _cta_findings(cta: str) -> list[Finding]:
    """结构组四：cta 三段式 + 禁空喊。"""
    cta_forbidden = bool(_FORBIDDEN_CTA_RE.search(cta))
    cta_has_click = bool(_CLICK_RE.search(cta))
    cta_has_watch = bool(_WATCH_ALL_RE.search(cta))
    return [
        Finding(
            "STRUCT_CTA_FORBIDDEN", "structure", "hard",
            not cta_forbidden,
            "cta 未空喊关注/点赞/收藏/二维码"
            if not cta_forbidden
            else "cta 出现禁用引导词（关注/点赞/收藏/二维码）",
            location="cta" if cta_forbidden else "",
            prompt_quote=_RULES["no_spoiler_climax"],
        ),
        Finding(
            "STRUCT_CTA_THREE_PART", "structure", "soft",
            cta_has_click and cta_has_watch,
            "cta 含『点击引导 + 看全集』三段式要素" if (cta_has_click and cta_has_watch)
            else f"cta 三段式不全（点击={cta_has_click} 看全集={cta_has_watch}）",
            location="cta" if not (cta_has_click and cta_has_watch) else "",
            prompt_quote=_RULES["cta_three_part"],
            needs_human=True,
        ),
    ]


def _speaker_and_meta_findings(
    segs: list[dict[str, Any]], hook: str, cta: str
) -> list[Finding]:
    """基本功组一：声纹标签 [角色X] 应换真名 + 禁元叙述（零容忍）。"""
    findings: list[Finding] = []
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
        prompt_quote=_RULES["speaker_tag_realname"],
        needs_human=True,
    ))
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
        prompt_quote=_RULES["metanarrative"],
        fix_hint="删掉该字眼，改成角色的动作或台词直接呈现；hook 与 cta 里出现时整句重写",
    ))
    return findings


def _numerals_and_person_findings(
    segs: list[dict[str, Any]], hook: str, cta: str
) -> list[Finding]:
    """基本功组二：数字写中文（软）+ 人称二选一（软，启发式）。"""
    findings: list[Finding] = []
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
        prompt_quote=_RULES["numerals_cn"],
        needs_human=True,
        fix_hint="把这些片段里的阿拉伯数字逐个改写成中文数词（2000→两千，47→四十七）",
    ))
    joined = hook + cta + " ".join(s.get("text", "") for s in segs)
    fp = _count(joined, _PERSON_FIRST)
    sp = _count(joined, _PERSON_SECOND)
    findings.append(Finding(
        "FUND_PERSON_CONSISTENT", "fund_base", "soft",
        not (fp > 0 and sp > 0),
        "人称未混用（一/二人称未同时出现）" if not (fp > 0 and sp > 0)
        else f"一/二人称同时出现（第一={fp} 第二={sp}），可能中途切换",
        prompt_quote=_RULES["person_consistent"],
        needs_human=True,
    ))
    return findings


def _fabrication_findings(
    segs: list[dict[str, Any]], transcript: list[dict[str, Any]]
) -> list[Finding]:
    """基本功组三：编造转写外事件（软，靠 transcript 粗查「姓氏+称谓」式专名）。"""
    transcript_text = "".join(seg.get("text", "") for seg in transcript)
    fabricated = []
    for i, s in enumerate(segs):
        novel = [
            m.group(0) for m in _FABRIC_RE.finditer(s.get("text", "") or "")
            if m.group(0) not in transcript_text
        ]
        if novel:
            fabricated.append((i, novel[:3]))
    return [
        Finding(
            "FUND_NO_FABRICATION", "fund_base", "soft",
            not fabricated,
            "未检出明显转写外专名" if not fabricated else f"疑似编造专名：{fabricated[:3]}",
            prompt_quote=_RULES["no_fabrication"],
            needs_human=True,
        )
    ]


def _invented_anchor_findings(segs: list[dict[str, Any]]) -> list[Finding]:
    """基本功组四：可疑数量/称号锚点（软+需人工）：转写外「八千两/九千岁」式硬锚点。"""
    invent_hits = []
    for i, s in enumerate(segs):
        t = s.get("text", "") or ""
        q = _QUANTITY_RE.search(t)
        title = _TITLE_CLAIM_RE.search(t)
        if q or title:
            invent_hits.append((i, (q.group(0) if q else "") or (title.group(0) if title else "")))
    return [
        Finding(
            "FUND_NO_INVENTED_ANCHOR", "fund_base", "soft",
            not invent_hits,
            "未检出可疑转写外数量/称号锚点"
            if not invent_hits
            else f"疑似转写外硬锚点：{invent_hits[:3]}（须原样出自转写，禁止为凑锚点发明）",
            location=";".join(f"segment[{i}]" for i, _ in invent_hits) if invent_hits else "",
            prompt_quote=_RULES["anchor_from_transcript"],
            needs_human=True,
        )
    ]


def _cross_episode_finding(segs: list[dict[str, Any]]) -> Finding:
    """跨集因果桥接（软+需人工）：涉及多集时必须人工确认前集段尾已说破因果。"""
    eps_present = sorted({int(s.get("episode", 1)) for s in segs})
    cross = len(eps_present) > 1
    return Finding(
        "FUND_CROSS_EPISODE_BRIDGE", "fund_full", "soft",
        not cross,
        "本稿未跨集（无需桥接）"
        if not cross
        else f"跨集涉及 {eps_present}，需人工确认每处跳集前段尾已把跨集因果说破",
        location="segments" if cross else "",
        prompt_quote=_RULES["adjacent_episode_jump"],
        needs_human=cross,
    )


# 人物完整介绍的三种中文句式（追更纪律：同一人物全套介绍只许出现一次）。
# 称号词表与短剧题材对齐（古装宫斗/权谋为主）；单字称号（王/帝/后）太短、误报源，不收。
_INTRO_TITLES = (
    "皇帝|可汗|皇后|皇太后|太后|太妃|王爷|亲王|郡王|侯爷|将军|大将军|大人|公公|太监|"
    "皇子|公主|太子|世子|公子|小姐|夫人|娘子|姑娘|阁老|尚书|御史|太尉|侍卫|指挥使|"
    "千户|百户|县令|知府|丞相|宰相|首辅|军师|管家|掌柜|掌门|长老|国师|太师|太傅|驸马|锦衣卫|"
    "殿下|陛下|娘娘|状元|捕头|镖头|少主|家主|宗主|摄政王|九千岁|千岁"
)
# 式A：称号同位语「摄政王萧临，先帝胞弟」——称号后紧跟百家姓起头的人名，防「将军出征，」误报
_INTRO_APPOSITE_RE = re.compile(
    r"(?:" + _INTRO_TITLES + r")([" + _SURNAME + r"][\u4e00-\u9fa5]{1,2})[，,、]"
    r"[^,,。;;!?!?]{2,16}"
)
# 式B：名字+逗号+称号「李若琏，锦衣卫指挥使」「王承恩，司礼监秉笔太监」——人名以百家姓
# 起头；称号前允许 ≤6 字修饰（司礼监秉笔/当朝/先帝亲封式），偶发从句误报交软规则人工兜
_INTRO_DESC_RE = re.compile(
    r"([" + _SURNAME + r"][\u4e00-\u9fa5]{1,3})[，,]"
    r"[^,,。;;!?!?]{0,6}?(?:" + _INTRO_TITLES + r")"
)
# 式C：系词式「李若琏是当朝锦衣卫指挥使」——姓氏起头 + 系词 + 少量引导字 + 称号
_INTRO_COPULA_RE = re.compile(
    r"([" + _SURNAME + r"][\u4e00-\u9fa5]{1,3})(?:便是|正是|乃是|就是|是)"
    r"[^,,。;;!?!?]{0,6}?(?:" + _INTRO_TITLES + r")"
)


def _extract_intro_names(text: str) -> list[tuple[str, str]]:
    """从一段解说文本提取「完整介绍句」的人名键 + 展示片段。

    三式命中即算完整介绍（身份随出场带出的句式）；提取是启发式，人名键只用作
    「同一人名被介绍几次」的计数——软规则+需人工，宁可漏报不可冤枉从句。
    同一处介绍被多式同时命中（如「李若琏，锦衣卫指挥使」既中式B也似中式C的
    邻域）只计一次：按人名 span 重叠去重，重复计数会把一次介绍报成两次。
    """
    names: list[tuple[str, str]] = []
    seen_spans: list[tuple[int, int]] = []
    for regex in (_INTRO_APPOSITE_RE, _INTRO_DESC_RE, _INTRO_COPULA_RE):
        for match in regex.finditer(text):
            start, end = match.start(1), match.end(1)
            if any(start < seen_end and end > seen_start for seen_start, seen_end in seen_spans):
                continue
            name = match.group(1)
            if len(name) >= 2:
                seen_spans.append((start, end))
                names.append((name, text[max(0, match.start() - 2) : match.end() + 4]))
    return names


def _person_intro_findings(
    segs: list[dict[str, Any]], prior_texts: list[str] | None = None
) -> list[Finding]:
    """人物纪律组（软+需人工）：同一人物被「完整介绍」超过一次，或前集已介绍过再走全套。

    「完整介绍」= 身份随出场带出的句式（式A/B/C）；同稿内第二次出现就是违例
    ——观众刚认识又要重认识一遍；prior_texts（同剧前集稿文本，调用方注入）里
    已介绍过的人物再走全套，追更观众早已知晓。prompt 只许「身份或关系随出场
    带一句」，全套介绍重复出现即违反。与九规则组同款：固定一条记录通过/不通过，
    跨稿规则只在 prior_texts 在场时才参审（没有前集数据时不该装作查过）。
    """
    texts = [str(s.get("text", "") or "") for s in segs]
    hits: dict[str, list[str]] = {}
    for text in texts:
        for name, snippet in _extract_intro_names(text):
            hits.setdefault(name, []).append(snippet)
    findings: list[Finding] = []
    repeated = {name: spots for name, spots in hits.items() if len(spots) >= 2}
    detail = "；".join(
        f"『{name}』×{len(spots)}（{spots[0][:10]}…）" for name, spots in repeated.items()
    )
    findings.append(
        Finding(
            "FUND_PERSON_INTRO_ONCE", "fund_base", "soft",
            not repeated,
            "未检出同一人物被完整介绍多次"
            if not repeated
            else f"同一人物被完整介绍多次：{detail}——第二次只许一句带过，禁止重走全套介绍",
            location=",".join(
                f"segment[{i}]"
                for i, text in enumerate(texts)
                if any(name in text for name in repeated)
            )[:200],
            prompt_quote=_RULES["characters_recognizable"],
            needs_human=bool(repeated),
        )
    )
    if not prior_texts:
        return findings
    prior_names: set[str] = set()
    for text in prior_texts:
        prior_names.update(name for name, _ in _extract_intro_names(text))
    carried = {name: spots[0] for name, spots in hits.items() if name in prior_names}
    carried_detail = "；".join(
        f"『{name}』（{snippet[:10]}…）" for name, snippet in carried.items()
    )
    findings.append(
        Finding(
            "FUND_PERSON_INTRO_CARRIED", "fund_base", "soft",
            not carried,
            "前集无重复介绍"
            if not carried
            else f"前集已完整介绍过的人物本稿再走全套：{carried_detail}"
            "——追更观众早已知晓，应改为一句带过（如「上集说到的某人」）",
            location="segments",
            prompt_quote=_RULES["characters_recognizable"],
            needs_human=bool(carried),
        )
    )
    return findings


def review_script(
    script: dict[str, Any],
    transcript: list[dict[str, Any]] | None = None,
    *,
    prior_texts: list[str] | None = None,
    episode_durations: dict[int, float] | None = None,
) -> ReviewReport:
    """审查 _STRUCTURE_PROMPT + 基本功层（full）约束。

    transcript: 清洗后的带时间戳台词，字段 episode/start/end/speaker/text。
    用于时间上界、互不重叠、声纹换名、编造外事件等可验证项。
    prior_texts: 同剧前集稿的解说文本（调用方注入，缺省 None 只查同稿内重复）。
    episode_durations: 各集整集时长（秒）——时间上界与清洗层同源用它；缺省退回
    「转写摘录最大 end」旧口径。两口径差＝摘录尾到集尾的无台词段：模型在那写段
    合法，旧口径却硬判超界带原句重掷，最坏三次全废（真集摘录普遍只到 60-80%）。
    规则按组拆在 _*_findings 子函数里，这里只做装配；产出顺序与拆分前逐条一致。
    """
    transcript = transcript or []

    # 时间上界表：episode -> 上界秒。整集时长在场优先（与清洗钳制同一真相源）；
    # 缺省退旧口径（转写摘录最大 end），网关等无时长上下文的调用方不受影响。
    ep_bounds: dict[int, float] = {}
    if episode_durations:
        ep_bounds = {ep: float(dur) for ep, dur in episode_durations.items() if dur > 0}
    else:
        for seg in transcript:
            ep = int(seg.get("episode", 1))
            ep_bounds[ep] = max(ep_bounds.get(ep, 0.0), float(seg.get("end", 0.0)))

    segs = script.get("segments", []) if isinstance(script, dict) else []
    hook = (script.get("hook", "") if isinstance(script, dict) else "") or ""
    cta = (script.get("cta", "") if isinstance(script, dict) else "") or ""

    findings: list[Finding] = []
    findings.extend(_script_shape_findings(segs))
    findings.extend(_script_time_findings(segs, ep_bounds))
    findings.extend(_hook_findings(hook))
    findings.append(_hook_payoff_finding(hook, segs))
    findings.extend(_cta_findings(cta))
    findings.extend(_speaker_and_meta_findings(segs, hook, cta))
    findings.extend(_numerals_and_person_findings(segs, hook, cta))
    if transcript:
        findings.extend(_fabrication_findings(segs, transcript))
    findings.extend(_invented_anchor_findings(segs))
    findings.extend(_narrative_texture_findings(segs))
    findings.append(_cross_episode_finding(segs))
    findings.extend(_person_intro_findings(segs, prior_texts))

    return ReviewReport(target="script", findings=findings,
                        meta={"n_segments": len(segs), "ep_bounds": ep_bounds})


def audit_script(
    script: Any,
    transcript: list[dict[str, Any]] | None = None,
    *,
    prior_texts: list[str] | None = None,
    episode_durations: dict[int, float] | None = None,
) -> ReviewReport:
    """编剧链内联审查封装：`Script` 模型（或同形 dict）→ 规则审查报告。

    write_script_episodes 的 attempts 循环逐稿调用；hard 未过条目带 prompt_quote
    重掷（规则锚定原句），soft 只记账不拦。prior_texts/episode_durations 透传给
    人物介绍重复与时间上界规则。
    """
    payload = script.model_dump() if hasattr(script, "model_dump") else script
    return review_script(
        payload, transcript, prior_texts=prior_texts, episode_durations=episode_durations
    )


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
    from dramaclip.engines.narration.copywriter import _OVERSIZE_TOLERANCE, _line_cap_of
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
        prompt_quote=_RULES["lines_cover_all_slots"],
    ))

    # —— 每条不超过行长上限 ——
    # —— 每条不超过行长上限（验收按生产同款容差：copywriter 收稿按 cap×1.2 放行，
    # 这里若按裸 cap 判，生产已放行的 61–72 字稿在审查里恒 REJECT，假加固建议由此而来）——
    oversize_cap = int(cap * _OVERSIZE_TOLERANCE)
    over = [
        (line.get("id"), len(line.get("text", "")))
        for line in lines
        if len(line.get("text", "")) > oversize_cap
    ]
    findings.append(Finding(
        "COPY_LINE_CAP", "copy", "hard",
        not over,
        f"每条均 ≤ {oversize_cap} 字" if not over else f"超长：{over}",
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
        prompt_quote=_RULES["metanarrative"],
    ))

    # —— 完成「要做的事」（软：空文本 / 明显跑题无法全判，标需人工）——
    empty = [line.get("id") for line in lines if not (line.get("text") or "").strip()]
    findings.append(Finding(
        "COPY_DOES_THE_JOB", "fund_slot", "soft",
        not empty,
        "无空文案槽位" if not empty else f"空文案槽位：{empty}（未完成任务契约）",
        location=";".join(str(e) for e in empty) if empty else "",
        prompt_quote=_RULES["slot_contract"],
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
        prompt_quote=_RULES["speaker_tag_realname"],
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
