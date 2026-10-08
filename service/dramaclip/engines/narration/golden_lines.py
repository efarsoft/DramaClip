"""LLM 金句提取：规则词表打分认不出修辞高光（《剑来》纠偏），语义判断交给 LLM。

按集一次调用：全部台词编号给 LLM，让它按「传播力」挑金句并**回填编号**——
编号越界/重复/非整数一律丢弃，零幻觉风险（金句原文永远来自真实台词）。
LLM 不可用/未配置 → 返回 None，调用方回退规则打分（line_scoring），
降级不可见。
"""

from __future__ import annotations

import logging

from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是短剧金句编辑。下面是同一部剧的台词，已编号。"
    "挑出最有传播力的金句——标准：观众看到就想截图转发、能记住、起鸡皮疙瘩。"
    "排比、对仗、意象、反差断言、狠话威胁、世间清醒都算；平淡叙事、过场对话不算。\n"
    '只输出 JSON：{"ids": [台词编号, ...]}，最多 8 条，按传播力从高到低排序。\n\n'
)

_MAX_GOLDEN_PER_EPISODE = 8


def pick_golden_lines(
    llm: LlmClient, asr_lines: list[tuple[int, float, float, str]]
) -> list[tuple[float, float]] | None:
    """单集金句提取：asr_lines = [(编号, start, end, text)]，回传选中行的 (start, end)。

    LLM 不可用/响应不合法 → None（调用方回退规则打分）；挑中的行按 LLM 给出的
    传播力排序回传。编号必须落在给定范围内，越界即弃。
    """
    if not asr_lines:
        return None
    numbered = "\n".join(
        f"{no}. [{start:.1f}-{end:.1f}s] {text.strip()}"
        for no, start, end, text in asr_lines
    )
    try:
        raw = llm.chat_json(_PROMPT, numbered)
    except LlmUnavailable as exc:
        logger.warning("LLM 金句提取失败，回退规则打分: %s", exc)
        return None
    ids = raw.get("ids") if isinstance(raw, dict) else None
    if not isinstance(ids, list):
        return None
    by_no = {no: (start, end) for no, start, end, _text in asr_lines}
    spans: list[tuple[float, float]] = []
    seen: set[int] = set()
    for item in ids:
        if not isinstance(item, int) or item not in by_no or item in seen:
            continue
        seen.add(item)
        spans.append(by_no[item])
        if len(spans) >= _MAX_GOLDEN_PER_EPISODE:
            break
    return spans or None


def pick_for_material(
    context_settings: dict[str, str],
    dialogue_by_episode: dict[str, list[tuple[int, float, float, str]]],
) -> dict[str, list[tuple[float, float]]]:
    """多集批量提取：{集 id: [(start, end), ...]}；未配置/全失败的集不进结果。"""
    config = LlmConfig.from_settings(context_settings)
    if not config.configured:
        return {}
    llm = LlmClient(config, timeout_s=float(context_settings.get("llm.timeout_s") or 120))
    result: dict[str, list[tuple[float, float]]] = {}
    for episode_id, asr_lines in dialogue_by_episode.items():
        spans = pick_golden_lines(llm, asr_lines)
        if spans:
            result[episode_id] = spans
    return result
