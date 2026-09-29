"""解说剧本装配：口味层选题（每任务一次）+ 跨集剧本驱动的对话解说。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.engines import llm_prompts, llm_trace
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import scriptwriter, styles
from dramaclip.engines.narration.models import PlanData, StrategySpec
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

# 剧本生成实测可达 100s+（qwen3.7-plus），远超 LLM 客户端默认 60s 超时
SCRIPT_LLM_TIMEOUT_S = 240.0
_SELECT_TIMEOUT_S = 60.0

LogFn = Callable[[str, str], None]


def resolve_run_style(
    settings: dict[str, str],
    episode_inputs: list[dict[str, Any]],
    *,
    log: LogFn,
    trace_dir: Path | None = None,
) -> dict[str, Any]:
    """口味层解析，每个任务只跑一次（原状是每模式一次，produce 白付 6 次 LLM 往返）。
    """
    preferred = settings.get("narration.style_id")
    genre = settings.get("_genre")
    style_id = styles.resolve_style_id(preferred, genre)
    reason = ""
    if (
        preferred in (styles.AUTO_STYLE_ID, None, "")
        and episode_inputs
        and LlmConfig.from_settings(settings).configured
    ):
        selector = LlmClient(LlmConfig.from_settings(settings), timeout_s=_SELECT_TIMEOUT_S)
        stamp = time.strftime("%m%d_%H%M%S")
        try:
            selection = styles.select_style_with_reason(
                selector,
                _excerpt(episode_inputs),
                system_prompt=llm_prompts.system_override(settings, "prompt.style_select_system"),
                trace_path=llm_trace.trace_path(trace_dir, f"llm_style_select_{stamp}.json"),
            )
        except Exception:  # noqa: BLE001 - 选题失败必须降级而非中断出片
            selection = None
        if selection is None:
            log("warn", "AI 风格选题失败，按题材静态映射兜底")
        else:
            style_id, reason = selection
    style = styles.get_style(style_id)
    log("info", _style_log_line(preferred, style, genre, reason))
    return style


def script_dialogue_plan(
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    angle_block: str,
    trace_dir: Any = None,
) -> tuple[PlanData, list[str]]:
    """跨集剧本驱动的对话解说。LLM 未配置或剧本不合格一律抛（降级已禁止）。
    """
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：剧情解说由编剧模型成稿，请先在「引擎」页配置文本模型"
        )
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "300")),
    )

    # 基本功层内置于编剧 system prompt；口味层 directives 注入 user prompt
    llm = LlmClient(config, timeout_s=SCRIPT_LLM_TIMEOUT_S)
    trace_path = None
    if trace_dir is not None:
        trace_dir = Path(trace_dir)
        trace_path = trace_dir / f"llm_script_{time.strftime('%m%d_%H%M%S')}.json"
    script = scriptwriter.write_script_episodes(
        llm,
        episode_inputs,
        project_name=str(settings.get("_project_name") or "这部剧"),
        angle_block=angle_block,
        style_directives=str(settings.get("_style_directives") or ""),
        trace_path=trace_path,
        prompts=llm_prompts.overrides_from(settings),
    )

    episode_map = {
        int(ep["number"]): (
            str(ep["episode_id"]),
            [AsrSegment.model_validate(seg) for seg in ep["segments"]],
        )
        for ep in episode_inputs
    }
    durations = {int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs}
    scene_cuts = {
        int(ep["number"]): [float(c) for c in ep.get("scene_cuts") or []]
        for ep in episode_inputs
    }
    plan = narration_pipeline.build_from_script_episodes(
        episode_map, durations, script, strategy, scene_cuts=scene_cuts
    )
    # 清洗吃掉了几段随方案落库：方案卡据此说"剧本丢弃 N 段"（规格 §4.3 卡片可见性）
    plan = plan.model_copy(update={"dropped_segments": script.dropped_segments})
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
