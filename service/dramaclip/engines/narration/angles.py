"""角度选题：一个模式一次 LLM 调用，产出 K 条**卖点互异**的取材角度。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dramaclip.engines import llm_prompts
from dramaclip.engines.llm_trace import dump_trace, trace_path
from dramaclip.engines.narration import scriptwriter, story_arc
from dramaclip.engines.semantic.llm_client import LlmUnavailable, client_for

ANGLE_LLM_TIMEOUT_S = 240.0  # 与成稿同量级：要读完整剧摘录再给 K 条角度
_ATTEMPTS = 2
_MAX_NAME_CHARS = 12
_MAX_REASON_CHARS = 60
_MAX_HOOK_CHARS = 40

_SYSTEM_PROMPT = (
    "你是短剧切片分销的选题操盘手。下面给出一部剧的跨集台词转写与一个出片模式，"
    "为这个模式选出若干条**卖点互异**的取材角度：每条切进这部剧的不同一条线"
    "（不同的人物关系、不同的反转、不同的爽点类型），而不是把同一段剧情换个说法。"
    "每条角度都要能撑起一条「看完还想点全集」的推广片，禁止只够十五秒空钩的碎切片。\n"
    "每条角度还要指定一条叙事母题（arc 字段）——这段故事按哪种骨架讲：\n"
    f"{story_arc.menu_line()}。\n"
    "母题按角度最吃哪个引擎来挑（人物反差选先扬后揭、憋屈蓄力选蓄力爆发、"
    "死局解谜选层层揭皮…），同一批角度的母题尽量不重复。\n"
    '只输出 JSON：{"angles": [{"name": "角度名", "reason": "为什么这条角度值得单出一条片",'
    ' "hook": "这条片的开场钩子首句", "arc": "母题id", "episode_numbers": [集号整数]}]}，'
    "不要其他文字。\n"
    f"硬性要求：角度名互不相同且各不超过 {_MAX_NAME_CHARS} 字；"
    f"reason 不超过 {_MAX_REASON_CHARS} 字、hook 不超过 {_MAX_HOOK_CHARS} 字；"
    "arc 必须是上面列出的母题 id 之一；"
    "hook 必须含具体反差事实（身份/生死/数字/当众打脸），禁止「他竟然…」式空钩；"
    "hook 的下笔角度要服合所选母题的开场（先扬后揭的钩子抛的是风光、蓄力爆发的"
    "钩子抛的是当众羞辱、爆点回环的钩子抛的是最炸一瞬）；"
    "各条角度的取材集尽量不重叠——共用素材越多，两条片就越像同一部片；"
    "每个角度必须绑定具体的人物关系与一个明确的反转/爽点事件，禁止「逆袭人生」这类空泛概括；"
    "优先挖掘跨集因果链（前集埋线→后集爆发），单集内讲不完的爽点最值得单出一条片；"
    "取材集应够把冲突链讲完，不要只给开场两集；"
    "取材集必须覆盖所选母题骨架的关键拍：先扬后揭要含巅峰一幕与辛酸事件所在的集、"
    "逼近死线要含死线成立与压哨一幕所在的集、爆点回环要含最炸一幕所在的集、"
    "层层揭皮要含每层翻面所在的集——母题的开场拍与结尾拍都要有集可锚，"
    "锚不到的骨架等于没给；"
    "角度、理由与钩子只能来自给定转写，禁止编造转写之外的事件。"
)

# 零文案模式（raw_clip/高光混剪/字幕金句流）专用：没有旁白槽位，母题/钩子/
# 句式规则无处落地——选题只干一件不可替代的事：挑跨集冲突链并命名（2026-10-20，
# 业主否掉单集锚定：吸引力在跨集因果链）。提示词不付母题菜单与文案约束的成本。
_REEL_SYSTEM_PROMPT = (
    "你是短剧切片分销的选题操盘手。下面给出一部剧的跨集台词转写、每集冲突档案"
    "与一个零解说出片模式，为它选出若干条**卖点互异**的跨集冲突链取材方案："
    "每条绑定一条完整故事线（前集埋线→后集爆发的因果链），而不是把同一段剧情"
    "换个说法。\n"
    '只输出 JSON：{"angles": [{"name": "方案名", "reason": "为什么值得单出一条片",'
    ' "episode_numbers": [集号整数]}]}，不要其他文字。\n'
    "硬性要求：方案名互不相同且各不超过 12 字；reason 不超过 60 字；"
    "每条方案的 episode_numbers 必须覆盖该故事线的全部关键集（从埋线到反转），"
    "鼓励跨集组合——单集出片讲不完一条因果链；"
    "各条方案的取材集尽量不重叠；"
    "方案名与理由只能来自给定转写，禁止编造。"
)


class AngleBrief(BaseModel):
    """一条取材角度：界面卡片四要素里的三项（角度名/理由/钩子）+ 取材集 + 叙事母题。
    """

    name: str
    reason: str
    hook: str = ""  # 零文案选线（zero_copy）无钩子：没有旁白去念它
    arc: str = ""
    episode_numbers: list[int]


def prompt_block(brief: AngleBrief, *, include_style: bool = True) -> str:
    """卖点角度进成稿 prompt 的措辞；母题结构卡+情绪配方随行（两链共用此通道）。

    情绪配方是母题的从属维度（2026-10-20 裁决）：讲法定了文风跟着讲法走，
    全自动随选题落定——不再逐任务跑独立风格选题（根除风格×母题两个主人
    打架；真机实锤：层层揭皮×爽文向）。``include_style=False`` 用于业主
    显式手选风格：人工意图优先，情绪配方让位（结构卡仍注入）。
    """
    arc_block = ""
    card = story_arc.card_of(brief.arc)
    if card is not None:
        arc_block = (
            f"\n叙事母题：{card.name}——{card.essence}"
            f"\n母题结构（全部段落按这个骨架推进，画面锚点随骨架走）：{card.structure}"
        )
        if include_style:
            arc_block += f"\n{card.style}"
    return (
        f"\n本条片的取材角度：{brief.name}"
        f"\n这条角度为什么成立：{brief.reason}"
        f"\n开场钩子首句（第一个槽位据此下笔，可改写措辞但不得换卖点）：{brief.hook}"
        + arc_block
    )


def _sanitize(
    raw: Any,
    *,
    k: int,
    known_numbers: set[int],
    excluded: list[str],
    zero_copy: bool = False,
) -> list[AngleBrief]:
    """逐条验收；任何一条不合格即整批不合格（重试或抛），绝不拿残缺的凑够 K 条。
    """
    items = raw.get("angles") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("选题未返回 angles 数组")
    if len(items) < k:
        raise ValueError(f"选题只给出 {len(items)} 条角度，要求 {k} 条")
    briefs: list[AngleBrief] = []
    seen: set[str] = set()
    arc_seen: dict[str, int] = {}
    for item in items[:k]:
        if not isinstance(item, dict):
            raise ValueError("angles 里存在非对象项")
        try:
            candidate = AngleBrief.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"角度项字段不合法：{exc}") from exc
        name = candidate.name.strip()
        reason = candidate.reason.strip()
        hook = candidate.hook.strip()
        arc = candidate.arc.strip()
        numbers = sorted(set(candidate.episode_numbers))
        if not name or not reason:
            raise ValueError("角度名、理由都不得为空")
        if not zero_copy and not hook:
            raise ValueError("角度名、理由、钩子首句都不得为空")
        if not zero_copy and arc not in story_arc.ids():
            raise ValueError(
                f"角度「{name}」的母题不认识：{arc!r}（必须从母题菜单里选）"
            )
        if len(name) > _MAX_NAME_CHARS:
            raise ValueError(f"角度名超出长度上限（{_MAX_NAME_CHARS} 字）：{name}")
        if len(reason) > _MAX_REASON_CHARS:
            raise ValueError(f"角度「{name}」的理由超出长度上限（{_MAX_REASON_CHARS} 字）")
        if len(hook) > _MAX_HOOK_CHARS:
            raise ValueError(f"角度「{name}」的钩子超出长度上限（{_MAX_HOOK_CHARS} 字）")
        if name in seen:
            raise ValueError(f"角度名重复：{name}（同名即同卖点）")
        if name in excluded:
            raise ValueError(f"角度「{name}」已被排除，不得重复提出")
        if not numbers:
            raise ValueError(f"角度「{name}」没有给出取材集")
        unknown = [number for number in numbers if number not in known_numbers]
        if unknown:
            raise ValueError(f"角度「{name}」取材集不存在：{unknown}")
        arc_seen[arc] = arc_seen.get(arc, 0) + 1
        if not zero_copy and arc_seen[arc] > 2:
            # 批内同母题超过一半：prompt 承诺「母题尽量不重复」——母题轮换本身是
            # 对单一套路疲劳的解药（story_arc docstring），K 条全押一张卡等于白跑。
            raise ValueError(
                f"母题「{arc}」在本批出现 {arc_seen[arc]} 次（上限 2）：母题要轮换，"
                "同一骨架的多条角度是伪多样性"
            )
        seen.add(name)
        briefs.append(
            AngleBrief(
                name=name,
                reason=reason,
                hook=hook,
                arc="" if zero_copy else arc,
                episode_numbers=numbers,
            )
        )
    return briefs


def episode_profiles_block(episode_inputs: list[dict[str, Any]]) -> str:
    """每集档案：冲突高峰与高光（带时间窗、评分、理由），供绑集与定母题。

    档案说的是「这部剧的关键拍都落在哪些集」——转写摘录给的是台词的滋味，
    档案给的是密度地图，两者互补。没有分析数据的集（旧库/桩环境）不占行；
    全部缺席时返回空串，prompt 里整块不出现。
    """
    blocks: list[str] = []
    for episode in episode_inputs:
        conflicts = _top_windows(episode.get("conflict_scores"), 5)
        highlights = _top_windows(episode.get("highlights"), 5)
        if not conflicts and not highlights:
            continue
        number = episode.get("number")
        duration = float(episode.get("duration") or 0.0)
        segments = episode.get("segments")
        line_count = len(segments) if isinstance(segments, list) else 0
        parts = [f"第 {number} 集（时长 {duration:.0f}s，台词 {line_count} 段）"]
        if conflicts:
            parts.append(
                "  冲突高峰："
                + "；".join(
                    f"{window['start']:.0f}-{window['end']:.0f}s"
                    f"（{window['score']:.0f} 分）{window['reason']}"
                    for window in conflicts
                )
            )
        if highlights:
            parts.append(
                "  高光片段："
                + "；".join(
                    f"{window['start']:.0f}-{window['end']:.0f}s"
                    f"（{window['score']:.0f} 分）{window['reason']}"
                    for window in highlights
                )
            )
        blocks.append("\n".join(parts))
    return "\n".join(blocks)


def _top_windows(raw: Any, limit: int) -> list[dict[str, Any]]:
    """按评分取前 limit 个窗口；形状不对/缺失回空表（档案缺席不报错）。"""
    items = raw if isinstance(raw, list) else []
    windows = [item for item in items if isinstance(item, dict) and "start" in item]
    return sorted(windows, key=lambda w: float(w.get("score") or 0.0), reverse=True)[
        :limit
    ]


def select_angles(
    mode: str,
    *,
    mode_label: str,
    k: int,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    excluded: list[str],
    trace_dir: Path | None = None,
    zero_copy: bool = False,
) -> list[AngleBrief]:
    """为一个模式选出 K 条互异角度；答不出互异就抛，不凑数。

    ``zero_copy``（raw_clip/高光混剪/字幕金句流）：换零文案专用提示词——只挑
    跨集冲突链并命名，不付母题菜单/钩子/句式约束的成本（那些无处落地）；
    验收同步放宽 hook/arc（见 _sanitize）。
    """
    if k < 1:
        raise ValueError(f"方案数 k 必须 ≥ 1，实得 {k}")
    if not episode_inputs:
        raise ValueError("没有带转写的已完成集，无从选题")
    transcript = scriptwriter.format_transcript_episodes(episode_inputs)
    if not transcript:
        raise ValueError("选题无米下锅：所有集都没有台词转写")
    known_numbers = {int(episode["number"]) for episode in episode_inputs}
    profiles = episode_profiles_block(episode_inputs)
    profiles_block = (
        f"\n各集档案（冲突高峰与高光的时间窗——"
        f"{'故事线关键集落在哪些集' if zero_copy else '母题关键拍落在哪些集'}，"
        f"看这里定，别凭台词猜）：\n{profiles}\n"
        if profiles
        else ""
    )
    excluded_block = (
        f"\n已存在、不得重复的角度：{'、'.join(excluded)}" if excluded else ""
    )
    user_prompt = (
        f"项目：{str(settings.get('_project_name') or '')}"
        f"\n模式：{mode_label}（{mode}）\n"
        f"需要 {k} 条卖点互异的取材角度。\n"
        "每条角度的 episode_numbers 给出这条片要用到的全部集号（至少一个，可多个）："
        "一条方案可以从多集取画面拼在同一条时间轴上。\n"
        f"{profiles_block}"
        f"{excluded_block}\n"
        f"台词转写：\n{transcript}"
    )
    llm = client_for(settings, min_timeout_s=ANGLE_LLM_TIMEOUT_S, site="取材角度")
    attempts: list[dict[str, Any]] = []
    briefs: list[AngleBrief] | None = None
    for _ in range(_ATTEMPTS):
        try:
            system = llm_prompts.system_override(settings, "prompt.angles_system") or (
                _REEL_SYSTEM_PROMPT if zero_copy else _SYSTEM_PROMPT
            )
            raw = llm.chat_json(system, user_prompt)
            briefs = _sanitize(
                raw,
                k=k,
                known_numbers=known_numbers,
                excluded=excluded,
                zero_copy=zero_copy,
            )
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    stamp = time.strftime("%m%d_%H%M%S")
    dump_trace(
        trace_path(trace_dir, f"llm_angles_{mode}_{stamp}.json"),
        {"system": system, "user": user_prompt, "attempts": attempts},
    )
    if briefs is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"选题未产出 {k} 条合格角度：{detail}")
    return briefs
