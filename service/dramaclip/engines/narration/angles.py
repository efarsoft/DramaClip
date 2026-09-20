"""角度选题：一个模式一次 LLM 调用，产出 K 条**卖点互异**的取材角度。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

ANGLE_LLM_TIMEOUT_S = 240.0  # 与成稿同量级：要读完整剧摘录再给 K 条角度
_ATTEMPTS = 2
_MAX_NAME_CHARS = 12
_MAX_REASON_CHARS = 60
_MAX_HOOK_CHARS = 40

_SYSTEM_PROMPT = (
    "你是短剧切片分销的选题操盘手。下面给出一部剧的跨集台词转写与一个出片模式，"
    "为这个模式选出若干条**卖点互异**的取材角度：每条切进这部剧的不同一条线"
    "（不同的人物关系、不同的反转、不同的爽点类型），而不是把同一段剧情换个说法。\n"
    '只输出 JSON：{"angles": [{"name": "角度名", "reason": "为什么这条角度值得单出一条片",'
    ' "hook": "这条片的开场钩子首句", "episode_numbers": [集号整数]}]}，不要其他文字。\n'
    f"硬性要求：角度名互不相同且各不超过 {_MAX_NAME_CHARS} 字；"
    f"reason 不超过 {_MAX_REASON_CHARS} 字、hook 不超过 {_MAX_HOOK_CHARS} 字；"
    "各条角度的取材集尽量不重叠——共用素材越多，两条片就越像同一部片；"
    "每个角度必须绑定具体的人物关系与一个明确的反转/爽点事件，禁止「逆袭人生」这类空泛概括；"
    "优先挖掘跨集因果链（前集埋线→后集爆发），单集内讲不完的爽点最值得单出一条片；"
    "角度、理由与钩子只能来自给定转写，禁止编造转写之外的事件。"
)


class AngleBrief(BaseModel):
    """一条取材角度：界面卡片四要素里的三项（角度名/理由/钩子）+ 取材集。
    """

    name: str
    reason: str
    hook: str
    episode_numbers: list[int]


def prompt_block(brief: AngleBrief) -> str:
    """卖点角度进成稿 prompt 的措辞。
    """
    return (
        f"\n本条片的取材角度：{brief.name}"
        f"\n这条角度为什么成立：{brief.reason}"
        f"\n开场钩子首句（第一个槽位据此下笔，可改写措辞但不得换卖点）：{brief.hook}"
    )


def _sanitize(
    raw: Any,
    *,
    k: int,
    known_numbers: set[int],
    excluded: list[str],
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
        numbers = sorted(set(candidate.episode_numbers))
        if not name or not reason or not hook:
            raise ValueError("角度名、理由、钩子首句都不得为空")
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
        seen.add(name)
        briefs.append(
            AngleBrief(name=name, reason=reason, hook=hook, episode_numbers=numbers)
        )
    return briefs


def select_angles(
    mode: str,
    *,
    mode_label: str,
    k: int,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    excluded: list[str],
    trace_dir: Path | None = None,
) -> list[AngleBrief]:
    """为一个模式选出 K 条互异角度；答不出互异就抛，不凑数。
    """
    if k < 1:
        raise ValueError(f"方案数 k 必须 ≥ 1，实得 {k}")
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：取材角度由模型选定（规格 §4.3 角度归模型），"
            "请先在「引擎」页配置文本模型"
        )
    if not episode_inputs:
        raise ValueError("没有带转写的已完成集，无从选题")
    transcript = scriptwriter.format_transcript_episodes(episode_inputs)
    if not transcript:
        raise ValueError("选题无米下锅：所有集都没有台词转写")
    known_numbers = {int(episode["number"]) for episode in episode_inputs}
    excluded_block = (
        f"\n已存在、不得重复的角度：{'、'.join(excluded)}" if excluded else ""
    )
    user_prompt = (
        f"项目：{str(settings.get('_project_name') or '')}"
        f"\n模式：{mode_label}（{mode}）\n"
        f"需要 {k} 条卖点互异的取材角度。\n"
        "每条角度的 episode_numbers 给出这条片要用到的全部集号（至少一个，可多个）："
        "一条方案可以从多集取画面拼在同一条时间轴上。\n"
        f"{excluded_block}\n"
        f"台词转写：\n{transcript}"
    )
    llm = LlmClient(config, timeout_s=ANGLE_LLM_TIMEOUT_S)
    attempts: list[dict[str, Any]] = []
    briefs: list[AngleBrief] | None = None
    for _ in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            briefs = _sanitize(
                raw,
                k=k,
                known_numbers=known_numbers,
                excluded=excluded,
            )
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    if trace_dir is not None:
        stamp = time.strftime("%m%d_%H%M%S")
        scriptwriter.dump_trace(
            Path(trace_dir) / f"llm_angles_{mode}_{stamp}.json",
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    if briefs is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"选题未产出 {k} 条合格角度：{detail}")
    return briefs
