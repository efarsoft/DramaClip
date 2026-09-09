"""剧本驱动对话解说编排（跨集）：LLM 自选风格（口味层）+ 基本功写剧本（两级降级）。

由 api 层注入 log 回调；本模块不 import transport。
降级链：LLM 自选 → genre 静态映射 → 通用；编写失败 → 规则编排（api 层处理）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import scriptwriter, styles
from dramaclip.engines.narration.models import PlanData, StrategySpec
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig

# 剧本生成实测可达 100s+（qwen3.7-plus），远超 LLM 客户端默认 60s 超时
SCRIPT_LLM_TIMEOUT_S = 240.0
_SELECT_TIMEOUT_S = 60.0
_SELECT_LINES_PER_EPISODE = 8

LogFn = Callable[[str, str], None]


def script_dialogue_plan(
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    log: LogFn,
    trace_dir: Any = None,
) -> tuple[PlanData, list[str]] | None:
    """跨集剧本驱动的对话解说；LLM 未配置或编写失败时返回 None（api 层降级规则编排）。

    episode_inputs 每项：{"number", "episode_id", "duration",
    "segments": [{"start", "end", "text"}]}，按集号升序。
    返回 (编排方案, 使用的集 id 列表)。
    """
    if not LlmConfig.from_settings(settings).configured:
        return None
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "300")),
    )
    genre = settings.get("_genre")
    preferred = settings.get("narration.style_id")

    # 口味层：LLM 读跨集转写节选自选风格；选题失败降级题材静态映射
    style_id = styles.resolve_style_id(preferred, genre)
    reason = ""
    if preferred == styles.AUTO_STYLE_ID or not preferred:
        selector = LlmClient(LlmConfig.from_settings(settings), timeout_s=_SELECT_TIMEOUT_S)
        selection = styles.select_style_with_reason(selector, _excerpt(episode_inputs))
        if selection is None:
            log("warn", "AI 风格选题失败，按题材静态映射兜底")
        else:
            style_id, reason = selection
    style = styles.get_style(style_id)

    # 基本功层内置于编剧 system prompt；口味层 directives 注入 user prompt
    llm = LlmClient(LlmConfig.from_settings(settings), timeout_s=SCRIPT_LLM_TIMEOUT_S)
    trace_path = None
    if trace_dir is not None:
        trace_dir = Path(trace_dir)
        stamp = time.strftime("%m%d_%H%M%S")
        trace_path = trace_dir / f"llm_script_{stamp}.json"
    script = scriptwriter.write_script_episodes(
        llm,
        episode_inputs,
        target_min_s=strategy.min_duration_s,
        target_max_s=strategy.max_duration_s,
        project_name=str(settings.get("_project_name", "这部剧")),
        style_directives=str(style.get("directives", "")),
        trace_path=trace_path,
    )
    if script is None:
        log("warn", "AI 编剧未产出跨集剧本，剧情解说降级规则编排")
        return None
    log("info", _style_log_line(preferred, style, genre, reason))

    episode_map = {
        int(ep["number"]): (
            str(ep["episode_id"]),
            [AsrSegment.model_validate(seg) for seg in ep["segments"]],
        )
        for ep in episode_inputs
    }
    durations = {int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs}
    plan = narration_pipeline.build_from_script_episodes(episode_map, durations, script, strategy)
    used_ids = sorted({seg.episode_id for seg in plan.timeline})
    return plan, used_ids


def _excerpt(episode_inputs: list[dict[str, Any]], max_lines: int = 40) -> list[dict[str, Any]]:
    """跨集选题节选：每集轮流取前几行，保证各集在菜单选择时都被看见。"""
    pool = [list(ep["segments"]) for ep in episode_inputs]
    excerpt: list[dict[str, Any]] = []
    while len(excerpt) < max_lines and any(pool):
        for segments in pool:
            if segments and len(excerpt) < max_lines:
                excerpt.append(segments.pop(0))
    return excerpt


def _style_log_line(
    preferred: str | None,
    style: dict[str, Any],
    genre: str | None,
    reason: str,
) -> str:
    name = str(style.get("name", style.get("style_id", "")))
    if preferred == styles.AUTO_STYLE_ID or not preferred:
        if reason:
            return f"解说风格：AI 自选 {name} —— {reason}"
        origin = f"按题材「{genre}」自动匹配" if genre else "自动匹配"
        return f"解说风格：{origin} → {name}"
    return f"解说风格：{name}（手动选择）"
