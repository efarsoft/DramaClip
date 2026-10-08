"""LLM 金句提取：规则词表打分认不出修辞高光（《剑来》纠偏），语义判断交给 LLM。

按集一次调用：全部台词编号给 LLM，让它按「传播力」挑金句并**回填编号**——
编号越界/重复/非整数一律丢弃，零幻觉风险（金句原文永远来自真实台词）。
LLM 不可用/未配置 → **抛 ValueError 明示原因**（业主裁决 2026-10-08：
每域单启用、失败即报错不兜底——静默降级成规则打分，选出来的句子
质量不可预期，用户还以为 LLM 挑的）。
"""

from __future__ import annotations

import logging

from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是短剧金句编辑。下面是同一部剧的台词，已编号。"
    "挑出最有传播力的金句。金句没有固定套路——一句戳心的情感独白、"
    "一句人生哲理、一个颠覆认知的反转、一段豪情排比，"
    "只要让人想截图转发、能记住、起鸡皮疙瘩，就是金句。"
    "（形态仅举例，不是边界：情感独白如「只要你的心是善良的，对错都是别人的事」；"
    "哲理如「但愿世间人无病，宁可架上药成灰」；"
    "豪情排比如「唯有一剑，可搬山，倒海，降妖」；"
    "反差狠话如「你连给她提鞋都不配」。）\n"
    "平淡叙事、过场对话、没有记忆点的台词不算。\n"
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
    # LlmUnavailable 不在此吞：上抛由 pick_for_material 包装成带原因的
    # ValueError（无兜底裁决 2026-10-08——静默转 None 会丢失失败原因）
    raw = llm.chat_json(_PROMPT, numbered)
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
    """多集批量提取：{集 id: [(start, end), ...]}。

    失败即抛（业主裁决「不需要兜底策略」）：LLM 未配置/不可用/某集提取失败
    都原样上抛带原因的 ValueError——静默降级成规则打分，选出的句子质量
    不可预期，用户还以为 LLM 挑的。"""
    config = LlmConfig.from_settings(context_settings)
    if not config.configured:
        raise ValueError(
            "金句提取需要文本模型：请在引擎中心配置 LLM 端点后重试"
        )
    llm = LlmClient(config, timeout_s=float(context_settings.get("llm.timeout_s") or 120))
    result: dict[str, list[tuple[float, float]]] = {}
    for episode_id, asr_lines in dialogue_by_episode.items():
        try:
            spans = pick_golden_lines(llm, asr_lines)
        except LlmUnavailable as exc:
            raise ValueError(
                f"金句提取失败（LLM 不可用）：{exc}——重试即可，或检查引擎中心配置"
            ) from exc
        if spans is None:
            raise ValueError(
                f"金句提取失败：{episode_id} 的台词未能得到有效的选择结果"
            )
        if spans:
            result[episode_id] = spans
    return result
