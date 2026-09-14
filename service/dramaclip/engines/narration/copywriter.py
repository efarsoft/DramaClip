"""逐槽文案编剧：编排器给出"这个画面段要说什么"，本模块让模型把话说出来。

槽位压在成片哪一段时间不是这里的数据：它是配对画面段（按 narration_id）的 start/end，
编剧读区间内的台词下笔，区间外的台词一概不进这一槽。

降级禁止（规格 §3.3.1）：LLM 未配置、槽位漏答、答非所问、句子超长、槽位没有配对画面段，
一律抛出，不再有模板池。失败粒度是单条方案——api 层逐模式捕获，其余模式继续出片。

槽位模式（intro/cross/ultra_short/full/dual_host/inner_monologue）共用本模块；
剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。
两类的方案都可以跨集取材（规格 §1）：本模块按 `segment.episode_id` 逐槽取台词，
scriptwriter 那边则把整份跨集转写按集分组喂给模型、由模型自己排集号。
卖点角度由 `angles.prompt_block` 措辞、经 `angle_block` 注入；两条链共用那一段字。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from dramaclip.engines.narration import casting, scriptwriter
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

COPY_LLM_TIMEOUT_S = 240.0  # 与编剧同量级：多槽位成稿实测可达 100s+
_MAX_LINE_CHARS = 60
_OVERSIZE_TOLERANCE = 1.2  # 容忍 20% 溢出，再长即判不合格重问
_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "你是短剧推广解说编剧。下面给出若干旁白槽位，每个槽位标注了它承担的职责、"
    "覆盖的画面区间，以及该区间内的原片台词。为每个槽位各写一条解说文案。\n"
    '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。\n'
    f"硬性要求：lines 必须覆盖全部槽位 id（数量与 id 一字不差）；每条不超过 {_MAX_LINE_CHARS} 字；"
    "按给定顺序书写，相邻两条要能连读成一条故事线；"
    "情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件。\n"
    + scriptwriter.FUNDAMENTALS
)


def _slot_block(
    texts: list[NarrationText],
    segments: list[TimelineSegment],
    material: casting.MaterialByEpisode,
) -> str:
    """每个槽位一段：职责 + 它压在的画面区间 + **它那一集**区间内的台词。

    台词必须按 `segment.episode_id` 取，不能拿一张摊平的 ASR 表按秒过滤：区间是
    **集内相对秒**，活库实测十集的场景起点全部从 `0.0` 开始，集与集的秒轴互相覆盖，
    于是第 3 集 12-20s 的槽位会捞到第 7 集 12-20s 的对白。而 system prompt 明写
    「情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件」——模型会老老实实照着
    **错的台词**写出一段通顺、可信、说的却不是这段画面的解说。不报错、不降级、
    成片看着正常，正是本仓最贵的那一类缺陷。跨集时间轴（规格 §1）让这个缺陷从
    "不可能发生"变成"必然发生"，故按集取台词是跨集的前置条件，不是可选优化。

    集名（`casting.EpisodeMaterial.label`）也进块：跨集时间轴上「画面区间 12.0-20.0s」
    不说是哪一集就等于没说，模型无从判断相邻两槽是不是同一条线。
    """
    by_id = {segment.narration_id: segment for segment in segments if segment.narration_id}
    lines: list[str] = []
    for text in texts:
        segment = by_id.get(text.id)
        if segment is None:
            raise ValueError(f"槽位 {text.id} 没有配对画面段：编排器漏写 narration_id")
        try:
            pool = casting.dialogue_of(material, segment.episode_id)
            label = casting.label_of(material, segment.episode_id)
        except ValueError as exc:
            # 缺键是装配漏了一集，不是"这一集没台词"：点名到槽位，否则错误串里只有
            # 一个 uuid，运维看不出是哪一条片的哪一段。
            raise ValueError(f"槽位 {text.id}：{exc}") from exc
        lines.append(f"[{text.id}] 要做的事：{text.brief}")
        lines.append(f"  取材：{label}，画面区间：{segment.start:.1f}-{segment.end:.1f}s")
        inside = [
            seg for seg in pool if seg.start < segment.end and seg.end > segment.start
        ]
        if inside:
            lines.append("  区间内台词：")
            lines.extend(
                f"    {scriptwriter.clock(seg.start)}-{scriptwriter.clock(seg.end)} "
                f"{seg.text.strip()}"
                for seg in inside
            )
        else:
            lines.append("    （该区间无台词转写：只按职责与前后槽位写，不得编造具体情节）")
    return "\n".join(lines)


def _sanitize(raw: Any, texts: list[NarrationText]) -> dict[str, str]:
    """按 id 取用，绝不按位置推断；漏答、空答、超长都算没答，交由调用方重试或抛。"""
    lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(lines, list):
        raise ValueError("编剧未返回 lines 数组")
    wanted = {text.id for text in texts}
    limit = int(_MAX_LINE_CHARS * _OVERSIZE_TOLERANCE)
    got: dict[str, str] = {}
    for item in lines:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id", "")).strip()
        value = str(item.get("text", "")).strip()
        if key not in wanted or value == "":
            continue
        if len(value) > limit:
            raise ValueError(f"槽位 {key} 文案 {len(value)} 字，超过上限 {limit} 字")
        got[key] = value
    missing = [text.id for text in texts if text.id not in got]
    if missing:
        raise ValueError(f"编剧漏了 {len(missing)} 个槽位：{', '.join(missing)}")
    return got


def write_plan_copy(
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。

    `material` 按集分开（episode_id → 集号 + 该集台词表）：一条方案的时间轴可以横跨
    多集（规格 §1），而槽位区间是**集内相对秒**，故每个槽位只能读它自己那一集的台词。
    理由与实测数字见 `_slot_block`。
    """
    if not plan.narration_texts:
        return plan
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：解说文案必须由编剧模型产出（已取消模板兜底），请在「引擎」页配置文本模型"
        )
    project_name = str(settings.get("_project_name") or "").strip()
    if not project_name:
        raise ValueError("缺少项目名：编剧需要剧名作为称谓")
    genre = str(settings.get("_genre") or "").strip()
    directives = str(settings.get("_style_directives") or "").strip()
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + f"\n模式：{mode_label}"
        + angle_block
        + "\n文案槽位：\n"
        + _slot_block(plan.narration_texts, plan.timeline, material)
        + (f"\n\n解说风格要求：{directives}" if directives else "")
    )
    llm = LlmClient(config, timeout_s=COPY_LLM_TIMEOUT_S)
    attempts: list[dict[str, Any]] = []
    filled: dict[str, str] | None = None
    for _ in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            filled = _sanitize(raw, plan.narration_texts)
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    if trace_dir is not None:
        stamp_time = time.strftime("%m%d_%H%M%S")
        scriptwriter.dump_trace(
            Path(trace_dir) / f"llm_copy_{plan.mode}_{stamp_time}.json",
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    if filled is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"编剧未产出合格文案：{detail}")
    return plan.model_copy(update={
        "narration_texts": [
            text.model_copy(update={"text": filled[text.id]}) for text in plan.narration_texts
        ],
        "planner": "llm_script",
    })
