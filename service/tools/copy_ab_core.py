"""文案规则 A/B 的纯函数半边：试验变量、配对、判决聚合、判定线、结论页。

不碰库、不调模型：出稿与盲评的读写都在 tools/copy_ab.py，这里只放能单测的逻辑。
判定线写在本文件的常量里，跑之前就定好——结论是数字对线得出的，不事后挑口径。
"""

from __future__ import annotations

import random
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.narration.prompt_rules import RULE_TEXTS

# 剧本链模式：七种解说模式里由「跨集剧本」出稿的那一种；B 文改的规则只在全稿版基本功里生效。
MODE = "dialogue_narration"
VARIANT_A, VARIANT_B = "A", "B"
VARIANTS = (VARIANT_A, VARIANT_B)
FUNDAMENTALS_KEY = "prompt.scriptwriter_fundamentals"

# ── 试验变量：A=现状；B 只换下面两句，其余提示词逐字相同 ──
OLD_RULE_KEY = "body_sensation_sparse"
OLD_EXAMPLE = "情绪用行动与选择呈现（「她把婚书扔进火里」胜过「她愤怒至极」）"
NEW_RULE = (
    "每三到四段给人物一个情绪落点，直说、体感、动作换着来——该直说就直说"
    "（「她慌了」「他气坏了」），别每回都靠攥拳、眼眶发红这类身体描写"
)
NEW_EXAMPLE = "情绪先让人听出来，再用行动坐实（「她气坏了，把婚书扔进火里」）"

# ── 判定线（跑之前登记；结论只认这几条）──
WIN_RATE_MIN = 0.60  # 一致胜率：分出高下的 A/B 对里 B 胜的占比下限
BEHIND_SAMPLE_MAX = 1  # B 净落后（A 胜多于 B 胜）的样本数上限：不靠单样本撑，也不被单样本拖垮
PLAIN_RATIO_MIN = 2.0  # 操纵检验：B 的直白情绪词密度均值至少是 A 的两倍
REGRESSION_TOL = 0.10  # 回归容差：出稿成功率、复述通过率 B 不比 A 低超过十个百分点
POSITION_BAND = (0.35, 0.65)  # 裁判可靠度：分出高下的单次判决里选「甲」位的占比区间
JUDGE_STRIKE_MAX = 5  # 连续无效判决到这个数就停（多为额度或网络），修好后重跑会接着评
JUDGE_TIMEOUT_S = 180.0

_WS = re.compile(r"\s+")
# 操纵检验用的两个词表：直白情绪词取宽口径（单字怒/怕/慌也算），身体化描写取常见体感词。
_PLAIN_WIDE = re.compile(
    r"气得|气坏|大怒|愤怒|怒|发怒|火了|恼怒|生气|怕|恐惧|吓|慌|心慌|急|难过|伤心|悲|崩溃"
    r"|绝望|恨|高兴|开心|乐|欣慰|嫉妒|眼红|羡慕|后悔|懊悔|悔|懵|愣|惊|震|委屈|心酸|心疼"
    r"|痛|羞|丢脸|松了口气|松了一口气|安心|放心|破防|受不了|忍不了|怒火|无奈|憋屈|郁闷"
    r"|烦躁|不安|心寒|心凉"
)
_BODY = re.compile(
    r"发烫|凉透|发凉|攥紧|指节|眼眶|鼻酸|哽咽|发抖|深吸|咬牙|咬着|僵在|红着眼|瞳孔|拳头"
    r"|颤抖|腿软|头皮发麻|指尖|手心|惨白|铁青|咬唇|抿唇|心头一|心里一|心脏|浑身一"
    r"|后背一凉|眼皮"
)

JUDGE_SYSTEM = (
    "你是刷短视频的普通观众，没看过这部剧。下面是同一部剧、同一个切入角的两篇解说文字稿，"
    "标为「甲」「乙」，顺序随机。只按一件事判断：听完哪一篇你更想继续看下去、更想点进去看全集。\n"
    "要求：\n"
    "1. 不猜是谁写的、不评价写作方法；篇幅长短不是理由。\n"
    "2. 引用的原句必须能在对应那一篇里逐字找到。\n"
    "3. 两篇确实分不出高下就选「差不多」，不要硬挑。\n"
    '只输出 JSON：{"prefer": "甲"|"乙"|"差不多", "quote_甲": "决定印象的一句原文", '
    '"quote_乙": "决定印象的一句原文", "reason": "一句话，说你依据的具体句子"}'
)
JUDGE_USER = "【甲】\n{first}\n\n【乙】\n{second}\n\n哪一篇更让你想看下去？"


# ---------------------------------------------------------------------------
# 数据形状
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    sample_id: str
    project_name: str
    genre: str
    episode_ids: tuple[str, ...]
    episode_numbers: tuple[int, ...]
    angle_name: str
    angle_block: str
    wanted: tuple[int, ...]  # 角度块取材的集号：出稿只喂这几集，与生产同口径


@dataclass(frozen=True)
class Script:
    script_id: str
    sample_id: str
    variant: str
    index: int
    ok: bool
    texts: tuple[str, ...]
    dropped: int
    error: str

    @property
    def text(self) -> str:
        return "\n".join(self.texts)

    @property
    def chars(self) -> int:
        return len(_WS.sub("", self.text))


@dataclass(frozen=True)
class Pair:
    pair_id: str
    kind: str  # ab=跨版对照；aa / bb=同组对照
    sample_id: str
    left_id: str
    right_id: str


@dataclass(frozen=True)
class Present:
    """一次呈现：哪一对、第几次（2=甲乙换位）、哪篇标甲。"""

    pair_id: str
    kind: str
    sample_id: str
    order_no: int
    first_id: str
    second_id: str


@dataclass(frozen=True)
class Judgment:
    pair_id: str
    order_no: int
    first_id: str
    picked_id: str  # 裁判选中的稿；「差不多」=空串
    quote_ok: bool
    reason: str
    quote_first: str
    quote_second: str
    error: str  # 非空=本次判决无效（调用失败或输出不合约定）


# ---------------------------------------------------------------------------
# 试验变量
# ---------------------------------------------------------------------------


def variant_b_fundamentals() -> str:
    """B 版基本功层：在 A 版（生产默认）里只换规则句与示例句。

    两句旧文必须在 A 版里各恰好出现一次——提示词以后改了措辞，这里先报错，
    而不是悄悄生成一份没换到变量的「B 版」。
    """
    base = scriptwriter.FUNDAMENTALS
    old_rule = RULE_TEXTS[OLD_RULE_KEY]
    for old in (old_rule, OLD_EXAMPLE):
        if base.count(old) != 1:
            raise ValueError(
                f"A 版基本功层里旧句出现 {base.count(old)} 次，B 版无从构造：{old[:16]}"
            )
    return base.replace(old_rule, NEW_RULE).replace(OLD_EXAMPLE, NEW_EXAMPLE)


def variant_settings(base: Mapping[str, str], sample: Sample, variant: str) -> dict[str, str]:
    """出稿用的 settings：任务级注入与生产同值，B 版多一条提示词覆盖。"""
    out = dict(base)
    out["_project_name"] = sample.project_name
    out["_genre"] = sample.genre
    # 风格自动时生产同样清空这一项（情绪配方随母题卡走在角度块里）。
    out["_style_directives"] = ""
    out["narration.flow_style"] = "0"
    if variant == VARIANT_B:
        out[FUNDAMENTALS_KEY] = variant_b_fundamentals()
    return out


# ---------------------------------------------------------------------------
# 配对 / 判决
# ---------------------------------------------------------------------------


def build_pairs(scripts: Sequence[Script]) -> list[Pair]:
    """每个样本内：A×B 全组合（跨版对照）+ 同版两两组合（同组对照）。只收出稿成功的。"""
    grouped: dict[tuple[str, str], list[Script]] = defaultdict(list)
    for script in scripts:
        if script.ok:
            grouped[(script.sample_id, script.variant)].append(script)
    pairs: list[Pair] = []
    for sample_id in sorted({key[0] for key in grouped}):
        a = sorted(grouped.get((sample_id, VARIANT_A), []), key=lambda s: s.index)
        b = sorted(grouped.get((sample_id, VARIANT_B), []), key=lambda s: s.index)
        combos = [("ab", x, y) for x in a for y in b]
        for kind, same in (("aa", a), ("bb", b)):
            combos.extend(
                (kind, same[i], same[j]) for i in range(len(same)) for j in range(i + 1, len(same))
            )
        pairs.extend(
            Pair(
                f"{sample_id}:{kind}:{left.script_id}:{right.script_id}",
                kind,
                sample_id,
                left.script_id,
                right.script_id,
            )
            for kind, left, right in combos
        )
    return pairs


def build_presents(pairs: Sequence[Pair], seed: int) -> list[Present]:
    """每对两次呈现，第二次甲乙换位；首次谁标甲只由 seed 决定（可复现）。"""
    rng = random.Random(seed)
    presents: list[Present] = []
    for pair in pairs:
        first, second = pair.left_id, pair.right_id
        if rng.random() < 0.5:
            first, second = second, first
        for order_no, (left, right) in enumerate(((first, second), (second, first)), start=1):
            presents.append(Present(pair.pair_id, pair.kind, pair.sample_id, order_no, left, right))
    return presents


def parse_judgment(raw: Any) -> tuple[str, str, str, str] | None:
    """裁判输出 → (选择, 甲引文, 乙引文, 理由)；不合约定返回 None。"""
    if not isinstance(raw, dict):
        return None
    prefer = str(raw.get("prefer") or "").strip()
    if prefer not in ("甲", "乙", "差不多"):
        return None
    return (
        prefer,
        str(raw.get("quote_甲") or "").strip(),
        str(raw.get("quote_乙") or "").strip(),
        str(raw.get("reason") or "").strip(),
    )


def _squash(text: str) -> str:
    return _WS.sub("", text)


def quote_found(quote: str, text: str) -> bool:
    """引文能在原文里逐字找到（忽略空白与首尾引号）；空引文不算。"""
    cleaned = quote.strip().strip('“”"‘’「」『』')
    return bool(cleaned) and _squash(cleaned) in _squash(text)


def verdicts(pairs: Sequence[Pair], judgments: Sequence[Judgment]) -> dict[str, str]:
    """每对的结论：两次呈现选同一篇=那篇胜；否则平；有效判决不足两次=无效。"""
    valid: dict[str, list[Judgment]] = defaultdict(list)
    for judgment in judgments:
        if not judgment.error:
            valid[judgment.pair_id].append(judgment)
    out: dict[str, str] = {}
    for pair in pairs:
        mine = valid.get(pair.pair_id, [])
        picks = {judgment.picked_id for judgment in mine}
        if len(mine) < 2:
            out[pair.pair_id] = "invalid"
        elif len(picks) == 1 and "" not in picks:
            out[pair.pair_id] = next(iter(picks))
        else:
            out[pair.pair_id] = "tie"
    return out


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tally:
    total: int
    wins_a: int
    wins_b: int
    ties: int
    invalid: int

    @property
    def decisive(self) -> int:
        return self.wins_a + self.wins_b


def tally(
    pairs: Iterable[Pair],
    verdict_of: Mapping[str, str],
    variant_of: Mapping[str, str],
    *,
    kind: str,
    sample_id: str | None = None,
) -> Tally:
    """某一类配对（可再限定到单样本）的胜负平账。"""
    wins = {VARIANT_A: 0, VARIANT_B: 0}
    ties = invalid = total = 0
    for pair in pairs:
        if pair.kind != kind or (sample_id is not None and pair.sample_id != sample_id):
            continue
        total += 1
        verdict = verdict_of.get(pair.pair_id, "invalid")
        if verdict == "tie":
            ties += 1
        elif verdict == "invalid":
            invalid += 1
        else:
            wins[variant_of[verdict]] += 1
    return Tally(total, wins[VARIANT_A], wins[VARIANT_B], ties, invalid)


def position_balance(
    judgments: Sequence[Judgment], kind_of: Mapping[str, str], *, kinds: Sequence[str]
) -> float | None:
    """分出高下的单次判决里，选「甲」位的占比；没有可计的判决返回 None。"""
    decisive = [
        judgment
        for judgment in judgments
        if not judgment.error and judgment.picked_id and kind_of.get(judgment.pair_id) in kinds
    ]
    first = sum(1 for judgment in decisive if judgment.picked_id == judgment.first_id)
    return round(first / len(decisive), 3) if decisive else None


def plain_density(script: Script) -> float:
    """一篇稿的直白情绪词每千字个数（宽口径词表）。"""
    body = _squash(script.text)
    return len(_PLAIN_WIDE.findall(body)) * 1000 / max(len(body), 1)


def _body_density(script: Script) -> float:
    body = _squash(script.text)
    return len(_BODY.findall(body)) * 1000 / max(len(body), 1)


def densities(scripts: Sequence[Script], variant: str) -> tuple[float, float]:
    """某版全部成稿的（直白情绪词, 身体化描写）每千字密度均值。"""
    rows = [script for script in scripts if script.ok and script.variant == variant]
    if not rows:
        return (0.0, 0.0)
    return (
        round(statistics.mean(plain_density(script) for script in rows), 2),
        round(statistics.mean(_body_density(script) for script in rows), 2),
    )


# ---------------------------------------------------------------------------
# 判定线与结论
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    name: str
    detail: str
    passed: bool | None  # None=算不出（缺数据），按不通过处理


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]
    tallies: dict[str, Tally]
    density: dict[str, tuple[float, float]]
    balance: dict[str, float | None]
    quote_ok_rate: float | None
    quotes: dict[str, list[tuple[str, str, str]]]  # 胜方版本 → (样本, 被引原句, 理由)

    @property
    def adopt(self) -> bool:
        return all(check.passed is True for check in self.checks)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _check_manipulation(scripts: Sequence[Script]) -> Check:
    plain_a, body_a = densities(scripts, VARIANT_A)
    plain_b, body_b = densities(scripts, VARIANT_B)
    ratio = plain_b / plain_a if plain_a else None
    passed = plain_b > 0 and ratio is not None and ratio >= PLAIN_RATIO_MIN
    ratio_text = f"{ratio:.1f}×" if ratio is not None else "A 为零，倍数算不出"
    detail = (
        f"直白情绪词每千字 A={plain_a} / B={plain_b}（{ratio_text}，下限 {PLAIN_RATIO_MIN}×）；"
        f"身体化描写 A={body_a} / B={body_b}"
    )
    return Check("操纵检验：B 的直白情绪词密度 ≥ A 的两倍", detail, passed)


def _check_win_rate(ab: Tally, per_sample: Mapping[str, Tally]) -> Check:
    rate = _rate(ab.wins_b, ab.decisive)
    behind = sum(1 for row in per_sample.values() if row.wins_a > row.wins_b)
    passed = rate is not None and rate >= WIN_RATE_MIN and behind <= BEHIND_SAMPLE_MAX
    rate_text = f"{rate:.0%}" if rate is not None else "算不出"
    detail = (
        f"A/B 对 {ab.total}：B 胜 {ab.wins_b} / A 胜 {ab.wins_a} / 平 {ab.ties} / 无效 {ab.invalid}；"
        f"一致胜率 {rate_text}（下限 {WIN_RATE_MIN:.0%}）；"
        f"B 净落后的样本 {behind}/{len(per_sample)}（上限 {BEHIND_SAMPLE_MAX}）"
    )
    return Check("一致胜率 ≥ 六成，且 B 净落后的样本不超过一个", detail, passed)


def _variant_rates(
    scripts: Sequence[Script], retells: Mapping[str, Mapping[str, Any]], variant: str
) -> tuple[float | None, float | None]:
    """某版的（出稿成功率, 复述通过率）；复述调用失败的稿不计入分母（那是未知不是没过）。"""
    rows = [script for script in scripts if script.variant == variant]
    usable = [
        retells[script.script_id]
        for script in rows
        if script.script_id in retells and not retells[script.script_id].get("error")
    ]
    return (
        _rate(sum(1 for script in rows if script.ok), len(rows)),
        _rate(sum(1 for row in usable if row.get("passed")), len(usable)),
    )


def _check_regression(scripts: Sequence[Script], retells: Mapping[str, Mapping[str, Any]]) -> Check:
    rate_a = _variant_rates(scripts, retells, VARIANT_A)
    rate_b = _variant_rates(scripts, retells, VARIANT_B)
    results: list[bool | None] = []
    lines: list[str] = []
    for label, base, mine in zip(("出稿成功率", "复述通过率"), rate_a, rate_b, strict=True):
        if base is None or mine is None:
            results.append(None)
            lines.append(f"{label} A={base} / B={mine}（缺数据，算不出）")
            continue
        results.append(mine >= base - REGRESSION_TOL)
        lines.append(f"{label} A={base:.0%} / B={mine:.0%}（容差 {REGRESSION_TOL:.0%}）")
    passed: bool | None = False if False in results else (None if None in results else True)
    return Check("回归：出稿成功率与复述通过率不比 A 低超过十个百分点", "；".join(lines), passed)


def _check_position(balance_all: float | None) -> Check:
    passed = balance_all is not None and POSITION_BAND[0] <= balance_all <= POSITION_BAND[1]
    detail = f"分出高下的单次判决里选「甲」位的占比 {balance_all}（应在 {POSITION_BAND} 内）"
    return Check("裁判位置平衡", detail, passed)


def _collect_quotes(
    pairs: Sequence[Pair],
    verdict_of: Mapping[str, str],
    variant_of: Mapping[str, str],
    valid: Sequence[Judgment],
    scripts: Sequence[Script],
) -> dict[str, list[tuple[str, str, str]]]:
    """跨版对照里每个胜出的对取一条证据：(样本, 胜方被引原句, 理由)。"""
    sample_of = {script.script_id: script.sample_id for script in scripts}
    quotes: dict[str, list[tuple[str, str, str]]] = {VARIANT_A: [], VARIANT_B: []}
    for pair in pairs:
        winner = verdict_of.get(pair.pair_id, "")
        if pair.kind != "ab" or winner not in variant_of:
            continue
        for judgment in valid:
            if judgment.pair_id == pair.pair_id and judgment.picked_id == winner:
                quote = (
                    judgment.quote_first if judgment.first_id == winner else judgment.quote_second
                )
                quotes[variant_of[winner]].append((sample_of[winner], quote, judgment.reason))
                break
    return quotes


def evaluate(
    scripts: Sequence[Script],
    pairs: Sequence[Pair],
    judgments: Sequence[Judgment],
    retells: Mapping[str, Mapping[str, Any]],
) -> Report:
    """四条判定线各出一个 Check；全过才采用 B。缺数据按不通过（算不出≠通过）。"""
    verdict_of = verdicts(pairs, judgments)
    variant_of = {script.script_id: script.variant for script in scripts}
    sample_ids = sorted({script.sample_id for script in scripts})
    kind_of = {pair.pair_id: pair.kind for pair in pairs}
    ab = tally(pairs, verdict_of, variant_of, kind="ab")
    per_sample = {
        sample_id: tally(pairs, verdict_of, variant_of, kind="ab", sample_id=sample_id)
        for sample_id in sample_ids
    }
    valid = [judgment for judgment in judgments if not judgment.error]
    balance = {
        "all": position_balance(judgments, kind_of, kinds=("ab", "aa", "bb")),
        "canary": position_balance(judgments, kind_of, kinds=("aa", "bb")),
    }
    return Report(
        checks=(
            _check_manipulation(scripts),
            _check_win_rate(ab, per_sample),
            _check_regression(scripts, retells),
            _check_position(balance["all"]),
        ),
        tallies={
            "ab": ab,
            "aa": tally(pairs, verdict_of, variant_of, kind="aa"),
            "bb": tally(pairs, verdict_of, variant_of, kind="bb"),
            **per_sample,
        },
        density={variant: densities(scripts, variant) for variant in VARIANTS},
        balance=balance,
        quote_ok_rate=_rate(sum(1 for judgment in valid if judgment.quote_ok), len(valid)),
        quotes=_collect_quotes(pairs, verdict_of, variant_of, valid, scripts),
    )


def _pct(value: float | None) -> str:
    return "算不出" if value is None else f"{value:.0%}"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(report: Report, meta: Mapping[str, Any]) -> str:
    """结论页：四条判定线逐条对数字，再给分样本表、裁判可靠度与被引原句。"""
    ab, aa, bb = report.tallies["ab"], report.tallies["aa"], report.tallies["bb"]
    lines = [
        f"# 文案规则 A/B · {meta.get('run_id', '')}",
        "",
        f"写作 {meta.get('writer', '?')} · 裁判 {meta.get('judge', '?')} · 样本 {meta.get('samples', '?')}",
        "",
        f"**结论：{'采用 B' if report.adopt else '保持 A'}**",
        "",
        "| 判定线 | 实测 | 结果 |",
        "|---|---|---|",
    ]
    for check in report.checks:
        mark = "算不出" if check.passed is None else ("过" if check.passed else "不过")
        lines.append(f"| {check.name} | {check.detail} | {mark} |")
    lines += [
        "",
        "## 分样本",
        "",
        "| 样本 | A/B 对 | B 胜 | A 胜 | 平 | 无效 |",
        "|---|---|---|---|---|---|",
    ]
    for key, row in report.tallies.items():
        if key not in ("ab", "aa", "bb"):
            lines.append(
                f"| {key} | {row.total} | {row.wins_b} | {row.wins_a} | {row.ties} | {row.invalid} |"
            )
    lines += [
        "",
        "## 裁判可靠度",
        "",
        f"- 换位一致率（A/B 对里两次选同一篇的比例）：{_pct(_rate(ab.decisive, ab.total))}",
        f"- 位置平衡（选甲位占比）：全部 {_pct(report.balance['all'])}；"
        f"只看同组对照 {_pct(report.balance['canary'])}；应在 {POSITION_BAND} 内",
        f"- 引文能在原文找到的判决占比：{_pct(report.quote_ok_rate)}",
        f"- 同组对照也分出高下的比例：A 对 A {_pct(_rate(aa.decisive, aa.total))}；"
        f"B 对 B {_pct(_rate(bb.decisive, bb.total))}",
        "",
        "## 密度（每千字）",
        "",
    ]
    for variant in VARIANTS:
        plain, body = report.density[variant]
        lines.append(f"- {variant} 版：直白情绪词 {plain}，身体化描写 {body}")
    lines += ["", "## 被引原句", ""]
    for variant in VARIANTS:
        lines.append(f"### {variant} 版胜出的对（{len(report.quotes[variant])} 对）")
        for sample_id, quote, reason in report.quotes[variant][:8]:
            lines.append(f"- {sample_id}：「{_clip(quote, 40)}」——{_clip(reason, 60)}")
        lines.append("")
    return "\n".join(lines)
