"""逐槽文案编剧：编排器给出"在哪段画面、以什么职责说话"，本模块让模型把话说出来。

降级禁止（规格 §3.3.1）：LLM 未配置、槽位漏答、答非所问、句子超长，一律抛出，
不再有模板池。失败粒度是单条方案——api 层逐模式捕获，其余模式继续出片。

单集槽位模式（intro/cross/ultra_short/full/dual_host/inner_monologue）共用本模块；
跨集剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.narration.models import NarrationText, PlanData
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

_LOGGER = logging.getLogger(__name__)

COPY_LLM_TIMEOUT_S = 240.0  # 与编剧同量级：多槽位成稿实测可达 100s+
_MAX_LINE_CHARS = 60
_OVERSIZE_TOLERANCE = 1.2  # 容忍 20% 溢出，再长即判不合格重问
_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "你是短剧推广解说编剧。下面给出若干旁白槽位，每个槽位标注了它在成片里的位置、"
    "承担的职责、覆盖的画面区间，以及该区间内的原片台词。为每个槽位各写一条解说文案。\n"
    '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。\n'
    f"硬性要求：lines 必须覆盖全部槽位 id（数量与 id 一字不差）；每条不超过 {_MAX_LINE_CHARS} 字；"
    "按给定顺序书写，相邻两条要能连读成一条故事线；"
    "情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件。\n"
    + scriptwriter.FUNDAMENTALS
)


def _clock(seconds: float) -> str:
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def _slot_block(
    texts: list[NarrationText],
    asr_segments: list[AsrSegment],
) -> str:
    """每个槽位一段：职责 + 画面区间 + 区间内台词。台词为编剧唯一的事实来源。"""
    lines: list[str] = []
    for text in texts:
        lines.append(f"[{text.id}] 职责：{text.slot}")
        if text.window is not None:
            start, end = text.window
            lines.append(f"  画面区间：{start:.1f}-{end:.1f}s")
            inside = [
                seg for seg in asr_segments if seg.start < end and seg.end > start
            ]
        else:
            inside = []
        if inside:
            lines.append("  区间内台词：")
            lines.extend(
                f"    {_clock(seg.start)}-{_clock(seg.end)} {seg.text.strip()}"
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
    asr_segments: list[AsrSegment],
    settings: dict[str, str],
    *,
    mode_label: str = "",
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。"""
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
        + (f"\n模式：{mode_label}" if mode_label else "")
        + f"\n文案槽位：\n{_slot_block(plan.narration_texts, asr_segments)}"
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
        stamp = time.strftime("%m%d_%H%M%S")
        scriptwriter.dump_trace(
            Path(trace_dir) / f"llm_copy_{plan.mode}_{stamp}.json",
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    if filled is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(
            f"编剧未产出合格文案（{'，'.join(t.id for t in plan.narration_texts)}）：{detail}"
        )
    return plan.model_copy(update={
        "narration_texts": [
            text.model_copy(update={"text": filled[text.id]}) for text in plan.narration_texts
        ],
        "planner": "llm_script",
    })
