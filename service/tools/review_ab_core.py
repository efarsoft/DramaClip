"""评审分趟对照实验的纯函数：造对照稿、分趟提示词、解析、指标。

要回答的问题：把「一次调用带整张六维量表」拆成「一稿一判据、只看局部、必须带引文」
之后，评审能不能更准地认出一篇稿子哪里弱。办法不是拿同质稿之间比相关——那些稿子
出自同一条产线，方差本来就小——而是**故意做坏**：同一篇稿子各造一份「开头垫铺垫」
「结尾去掉导看」「中段打乱顺序」的对照稿。认得出原稿比做坏的稿子好，才算认得出来。

尺子是另一个家族的模型对每篇稿子的独立打分（见 copy_ab_score）。
"""

from __future__ import annotations

import random
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dramaclip.engines.narration import variant_scoring

PLAIN = "plain"
PAD_OPEN = "pad_open"  # 开头垫三句报幕腔：真正的开头被推到它们后面
FLAT_END = "flat_end"  # 结尾去掉导看那一段
SHUFFLE_MID = "shuffle_mid"  # 中段顺序打乱：因果链断掉
CONDITIONS: tuple[str, ...] = (PLAIN, PAD_OPEN, FLAT_END, SHUFFLE_MID)
#: 没有导看段可去的短稿，补一句没有导看动作的收场
_FLAT_ENDING = "这部剧后面的情节，感兴趣的朋友可以自己去看一看。"
#: 报幕腔：三句零剧情信息的话，哪个题材的稿子都垫得上
_OPENING_PAD: tuple[str, ...] = (
    "今天给大家讲一部最近很火的短剧。",
    "这部剧上线以后讨论的人特别多，评论区也很热闹。",
    "话不多说，我们直接进入正题。",
)


@dataclass(frozen=True)
class Item:
    """实验里的一篇稿子：原稿或它的某一份对照稿。"""

    item_id: str
    base: str
    cond: str
    texts: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.texts)


def local_parts(texts: Sequence[str]) -> tuple[str, str, str]:
    """(开头, 中段, 结尾) 三段原文：局部盲评只给评审其中一段。"""
    if len(texts) >= 5:
        return "\n".join(texts[:2]), "\n".join(texts[2:-2]), "\n".join(texts[-2:])
    if len(texts) >= 3:
        return texts[0], "\n".join(texts[1:-1]), texts[-1]
    return "\n".join(texts), "", "\n".join(texts)


def degrade(base: str, texts: Sequence[str], cond: str, seed: int) -> Item | None:
    """造一份对照稿；这篇稿子造不出这种坏（段数不够）返回 None。"""
    if cond == PLAIN:
        return Item(f"{base}-{cond}", base, cond, tuple(texts))
    if cond == PAD_OPEN:
        return Item(f"{base}-{cond}", base, cond, (*_OPENING_PAD, *texts))
    if cond == FLAT_END:
        tail: tuple[str, ...] = texts[:-1] if len(texts) >= 4 else (*texts, _FLAT_ENDING)
        return Item(f"{base}-{cond}", base, cond, tail)
    if cond == SHUFFLE_MID:
        if len(texts) < 4:
            return None
        middle = list(texts[1:-1])
        random.Random(f"{base}|{seed}").shuffle(middle)
        return Item(f"{base}-{cond}", base, cond, (texts[0], *middle, texts[-1]))
    raise ValueError(f"未知对照类型：{cond}")


def build_items(bases: Mapping[str, Sequence[str]], seed: int = 20261126) -> list[Item]:
    return [
        item
        for base, texts in bases.items()
        for cond in CONDITIONS
        if (item := degrade(base, texts, cond, seed)) is not None
    ]


def pick_bases(
    texts_of: Mapping[str, Sequence[str]], yardstick_of: Mapping[str, float], per_sample: int
) -> dict[str, Sequence[str]]:
    """按尺子分数挑原稿：每个样本里各取最低分与最高分的那篇，拉开量程。

    `texts_of` 的键形如「样本-变体序号」，样本名取第一个连字符之前。
    """
    by_sample: dict[str, list[tuple[float, str]]] = {}
    for script_id, texts in texts_of.items():
        if script_id in yardstick_of and texts:
            by_sample.setdefault(script_id.split("-")[0], []).append(
                (yardstick_of[script_id], script_id)
            )
    picked: dict[str, Sequence[str]] = {}
    for ranked in by_sample.values():
        ranked.sort()
        chosen = ranked[: per_sample // 2] + ranked[-(per_sample - per_sample // 2) :]
        for _score, script_id in chosen:
            picked[script_id] = texts_of[script_id]
    return dict(sorted(picked.items()))


# ---------------------------------------------------------------------------
# 分趟提示词：行为锚点沿用生产评分器那一份（同一把尺子，只换看法）
# ---------------------------------------------------------------------------

_ANCHOR = re.compile(r"【(\w+) [^】]*】(.*?)(?=\n【|\n改进建议)", re.S)
_LOCAL_DIMS: tuple[tuple[str, str, str, str], ...] = (
    # (趟名, 对应的维度, 只给评审看哪一段, 怎么交代)
    ("hook", "hook_power", "opening", "下面只给你这段视频的**开头几句**（后面的内容你看不到）"),
    ("middle", "rhythm", "middle", "下面只给你这段视频的**中段**（开头和结尾你都看不到）"),
    ("ending", "cta_pull", "ending", "下面只给你这段视频的**结尾几句**（前面的内容你看不到）"),
)
_WHOLE_DIMS: tuple[str, ...] = ("conflict_clarity", "emotion_curve", "visual_potential")


def anchors() -> dict[str, str]:
    """生产评分器里各维度的行为锚点原文（按维度名）。"""
    return {
        match.group(1): match.group(2).strip()
        for match in _ANCHOR.finditer(variant_scoring._SYSTEM_PROMPT)
    }


def local_system(dim: str, anchor: str) -> str:
    return (
        "你是短视频平台上的普通观众，刷到一条短剧解说视频。"
        f"只判断下面这一件事，按行为锚点对号入座，打 1-10 分（整数）：\n"
        f"【{dim}】{anchor}\n"
        "先摘一句原文当依据（quote 必须逐字出自给你的文字），再用一句话说怎么改会更抓人"
        "（fix，具体到改哪一句，不要空话）。\n"
        '只输出 JSON：{"score": 1到10的整数, "quote": "原句", "fix": "一句话"}，不要其他文字。'
    )


def whole_system(all_anchors: Mapping[str, str]) -> str:
    listed = "\n".join(f"【{dim}】{all_anchors[dim]}" for dim in _WHOLE_DIMS if dim in all_anchors)
    return (
        "你是短视频平台上的普通观众，看完了一条短剧解说视频。下面是它的完整解说文案。"
        "按三个维度各打 1-10 分（整数），逐维按行为锚点对号入座：\n"
        f"{listed}\n"
        "每个维度摘一句原文当依据。\n"
        '只输出 JSON：{"dims": {"conflict_clarity": 分数, "emotion_curve": 分数, '
        '"visual_potential": 分数}, "quotes": {"维度": "原句"}}，不要其他文字。'
    )


def quoted_system(all_anchors: Mapping[str, str]) -> str:
    """不分趟的对照：同一篇稿子一次调用打六维，但必须逐维带引文、不带任何标签。"""
    listed = "\n".join(
        f"【{dim}】{all_anchors[dim]}" for dim in variant_scoring.DIMENSIONS if dim in all_anchors
    )
    return (
        "你是短剧推广片的文案评审。下面给出一篇解说文案，按六个维度各打 1-10 分（整数），"
        "逐维按行为锚点对号入座，禁止凭印象给分：\n"
        f"{listed}\n"
        "每个维度摘一句原文当依据（quote 必须逐字出自文案）。\n"
        "再给一句具体改进建议（suggestion）：具体到「改哪一句、怎么改、保留什么」，用中文；"
        "禁止「建议优化文案」这类空话。\n"
        '只输出 JSON：{"dims": {"hook_power": 分数, "rhythm": 分数, "emotion_curve": 分数, '
        '"conflict_clarity": 分数, "cta_pull": 分数, "visual_potential": 分数}, '
        '"quotes": {"维度": "原句"}, "suggestion": "一句具体改进建议"}，不要其他文字。'
    )


def _score(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(min(10, max(1, raw)))


def _text(raw: Any) -> str:
    return str(raw).strip() if isinstance(raw, str) else ""


def parse_local(raw: Any, excerpt: str) -> dict[str, Any] | None:
    """一趟能用的结果：分数合法、引文确实出自给它的那段文字。"""
    if not isinstance(raw, dict):
        return None
    score = _score(raw.get("score"))
    quote = _text(raw.get("quote"))
    if score is None or not quote or quote not in excerpt:
        return None
    return {"score": score, "quote": quote, "fix": _text(raw.get("fix"))}


def parse_whole(raw: Any, text: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    dims = variant_scoring._parse_dims(raw.get("dims"))
    quotes = raw.get("quotes") if isinstance(raw.get("quotes"), dict) else {}
    cited = {dim: _text(quotes.get(dim)) for dim in dims}
    if not dims or any(not quote or quote not in text for quote in cited.values()):
        return None
    return {"dims": dims, "quotes": cited}


def parse_quoted(raw: Any, text: str) -> dict[str, Any] | None:
    """六维齐全才算数：少一维的总分与别的评审不同尺。"""
    parsed = parse_whole(raw, text)
    if parsed is None or set(parsed["dims"]) != set(variant_scoring.DIMENSIONS):
        return None
    return {**parsed, "suggestion": _text(raw.get("suggestion"))}


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """某个评审对某一篇稿子的结论：总分 + 各维（局部趟折进对应的维度）。"""

    scorer: str
    item_id: str
    base: str
    cond: str
    total: float
    dims: dict[str, dict[str, Any]]


def staged_verdict(item: Item, passes: Mapping[str, Mapping[str, Any] | None]) -> Verdict | None:
    """四趟凑成一份结论：三个局部趟各折进自己的维度，整篇趟出另外三维。

    任何一维缺失就整份作废（缺维的总分与别的评审不同尺，不比）。
    """
    dims: dict[str, dict[str, Any]] = {}
    for name, dim, _part, _focus in _LOCAL_DIMS:
        verdict = passes.get(name)
        if verdict is not None:
            dims[dim] = dict(verdict)
    whole = passes.get("whole")
    if whole is not None:
        for dim, value in whole["dims"].items():
            dims.setdefault(dim, {"score": value})
    if set(dims) != set(variant_scoring.DIMENSIONS):
        return None
    flat = {dim: float(entry["score"]) for dim, entry in dims.items()}
    return Verdict(
        "staged", item.item_id, item.base, item.cond, variant_scoring.weighted_total(flat), dims
    )


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    covariance = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    variance_x = sum((x - mx) ** 2 for x in xs)
    variance_y = sum((y - my) ** 2 for y in ys)
    return covariance / (variance_x * variance_y) ** 0.5 if variance_x and variance_y else None


@dataclass(frozen=True)
class Metrics:
    scorer: str
    items: int
    sd: float  # 原稿得分的标准差：评审把好稿坏稿拉得多开
    plain_top: float  # 原稿在四份里被排第一的比例
    detected: dict[str, float]  # 各对照类型：原稿得分高于对照稿的稿子占比
    gap: dict[str, float]  # 各对照类型：原稿减对照稿的平均分差
    pearson: float | None  # 与尺子的逐篇相关
    yard_top_match: float  # 该评审排第一的那篇正是尺子排第一那篇的稿子占比


def _totals(verdicts: Sequence[Verdict], cond: str | None) -> dict[str, float]:
    return {v.item_id: v.total for v in verdicts if cond is None or v.cond == cond}


def _paired(
    verdicts: Sequence[Verdict], yard: Mapping[str, float]
) -> tuple[list[float], list[float]]:
    scored = _totals(verdicts, None)
    common = sorted(key for key in scored if key in yard)
    return [scored[key] for key in common], [yard[key] for key in common]


def metrics(
    verdicts: Sequence[Verdict],
    yard: Mapping[str, float],
    conds: Sequence[str] = CONDITIONS,
) -> Metrics:
    """一个评审在一批稿子上的表现。`yard` 是尺子对各篇的均分（按 item_id）。"""
    by_base: dict[str, dict[str, float]] = {}
    for verdict in verdicts:
        by_base.setdefault(verdict.base, {})[verdict.cond] = verdict.total
    # 四份都评过分的原稿才进账：缺一份的组算不出「原稿排第一」
    bases = sorted(b for b, row in by_base.items() if all(cond in row for cond in conds))

    def rate(hit: Callable[[str], bool], pool: Sequence[str] = bases) -> float:
        return round(sum(1 for base in pool if hit(base)) / len(pool), 3) if pool else 0.0

    damaged = [cond for cond in conds if cond != PLAIN]
    yard_base: dict[str, dict[str, float]] = {}
    for item_id, score in yard.items():
        base, _sep, cond = item_id.rpartition("-")
        if cond in conds:
            yard_base.setdefault(base, {})[cond] = score
    both = [base for base in bases if set(yard_base.get(base, {})) >= set(conds)]
    plain_scores = [by_base[base][PLAIN] for base in bases]
    xs, ys = _paired(verdicts, yard)
    return Metrics(
        scorer=verdicts[0].scorer if verdicts else "",
        items=len(_totals(verdicts, None)),
        sd=round(statistics.pstdev(plain_scores), 2) if len(plain_scores) > 1 else 0.0,
        plain_top=rate(lambda base: by_base[base][PLAIN] > max(by_base[base][c] for c in damaged)),
        detected={
            cond: rate(lambda base, c=cond: by_base[base][PLAIN] > by_base[base][c])
            for cond in damaged
        },
        gap={
            cond: round(statistics.mean(by_base[b][PLAIN] - by_base[b][cond] for b in bases), 2)
            if bases
            else 0.0
            for cond in damaged
        },
        pearson=pearson(xs, ys),
        yard_top_match=rate(
            lambda base: (
                max(by_base[base], key=by_base[base].get)
                == max(yard_base[base], key=yard_base[base].get)
            ),
            both,
        ),
    )


def render_report(tables: Sequence[Metrics], pass_table: Mapping[str, Mapping[str, float]]) -> str:
    names = {PLAIN: "原稿", PAD_OPEN: "开头垫铺垫", FLAT_END: "结尾去导看", SHUFFLE_MID: "中段打乱"}
    lines = [
        "| 评审 | 篇数 | 原稿分标准差 | 原稿排第一 | 认出开头垫铺垫 | 认出结尾去导看 | 认出中段打乱 | 与尺子相关 | 与尺子首选一致 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in tables:
        correlation = "—" if row.pearson is None else f"{row.pearson:.2f}"
        cells = [
            f"{row.detected.get(c, 0):.0%}（{row.gap.get(c, 0):+.1f}）"
            for c in (PAD_OPEN, FLAT_END, SHUFFLE_MID)
        ]
        lines.append(
            f"| {row.scorer} | {row.items} | {row.sd} | {row.plain_top:.0%} | "
            + " | ".join(cells)
            + f" | {correlation} | {row.yard_top_match:.0%} |"
        )
    lines += ["", "认出 = 原稿得分高于对照稿的稿子占比（括号里是平均分差，1-10 分制）。", ""]
    if pass_table:
        lines += ["分趟各趟自己的分差（原稿 − 对照稿；只列该趟该认的那种）：", ""]
        for name, row in pass_table.items():
            shown = "，".join(f"{names[c]} {value:+.1f}" for c, value in row.items())
            lines.append(f"- {name}：{shown}")
    return "\n".join(lines) + "\n"
