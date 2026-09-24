"""成片转化门禁：钩子站得住、收尾指向看全集。不过关不能进作品库。"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData

_BANNED = ("关注我", "点赞", "二维码")
_CTA_OK = ("全集", "点进去", "后面更狠")


def defects(plan: PlanData) -> list[str]:
    """返回缺陷列表；空列表 = 过关。raw_clip 无旁白，只查时间轴。"""
    issues: list[str] = []
    if not plan.timeline:
        return ["空时间轴"]
    first = plan.timeline[0]
    if first.end - first.start < 0.5:
        issues.append("开场不足半秒，钩子站不住")
    issues.extend(_timeline_defects(plan))
    if plan.mode == "raw_clip":
        return issues
    last = _cta_text(plan)
    if not last.strip():
        issues.append("收尾没有文案")
        return issues
    if any(token in last for token in _BANNED):
        issues.append("收尾禁止关注/点赞/二维码")
    if not any(token in last for token in _CTA_OK):
        issues.append("收尾没有指向看全集")
    return issues


def _timeline_defects(plan: PlanData) -> list[str]:
    """纯 plan 数据可判的时间轴合法性：负起点、结束不晚于开始、同集区间重叠。

    负起点/结束不晚于开始对所有方案照查：规则编排器也写不出这种段，出现即
    存储损坏或未来代码 bug，便宜且必须拦。

    **同集重叠只查 dialogue_narration**——它是唯一时间轴由 LLM 剧本产出的模式
    （`build_from_script_episodes`），重叠检查防的就是 LLM 幻觉时间戳这个形状
    （scriptwriter 清洗层已先挡一道：重叠段推 start 并计数 segments_clamped，
    这里是第二道闸；新的 LLM 时间轴模式出现时必须加进这个判据）。

    其余八个模式的时间轴由规则编排器**确定性**产出，它们的重叠全是设计行为，
    不是幻觉（真机核验过四种形状）：
    - intro / ultra_short 的 CTA 卡复用最后场景尾部画面（`_CTA_FALLBACK_S`，
      结尾卡叠在既有画面上，不新取素材）；
    - cross 的场景间旁白桥「画面延续到下一场景开头」（modes_w5 注释原文）；
    - subtitle_flow 的结尾 CTA 卡同款复用（original 音频 + subtitle_text）。
    把设计当缺陷的后果是四个规则模式**恒为 draft、永远不能出片**（批次一引入
    的真回归：draft 不能渲，规则模式生产线全断；当时单测夹具全是手搓的
    full_narration 时间轴、无 CTA 卡形状，所以没兜住）。
    注意 `planner` 不能当判据：copywriter 给所有带旁白槽的方案填文案后都会置
    planner=llm_script（「文案来源」语义，test_plan_variants 钉死），grade 时
    规则模式的 planner 早已不是 "rule"。
    raw_clip 同样受查——它豁免的是 CTA 文案（无旁白），不是时间轴本身。
    """
    issues: list[str] = []
    by_episode: dict[str, list[tuple[float, float]]] = {}
    for index, segment in enumerate(plan.timeline):
        if segment.start < 0:
            issues.append(f"第 {index + 1} 段起点为负（{segment.start:g}s）")
        if segment.end <= segment.start:
            issues.append(
                f"第 {index + 1} 段结束不晚于开始（{segment.start:g}s → {segment.end:g}s）"
            )
        by_episode.setdefault(segment.episode_id, []).append((segment.start, segment.end))
    if plan.mode != "dialogue_narration":
        return issues  # 规则编排的重叠是设计（CTA 卡复用画面/旁白桥），见 docstring
    for episode_id, spans in by_episode.items():
        ordered = sorted(spans)
        for (prev_start, prev_end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
            if next_start < prev_end:
                issues.append(
                    f"{episode_id} 内段区间重叠"
                    f"（{prev_start:g}-{prev_end:g}s 与 {next_start:g}s 起）"
                )
                break  # 每集报一次就够：方案卡要的是「哪里坏了」，不是重叠全名录
    return issues


def grade(plan: PlanData) -> str:
    """过关 → ready（可出片）；有缺陷 → draft（能看不能渲）。"""
    return "draft" if defects(plan) else "ready"


def _cta_text(plan: PlanData) -> str:
    """收尾文案看时间轴最后一段，不看旁白列表末条。

    intro_narration 的钩子在片头：若用 ``narration_texts[-1]``，片头写了「看全集」
    也会过门禁，成片最后两秒仍是原声。字幕金句流的 CTA 在 ``subtitle_text``。
    """
    last = plan.timeline[-1]
    if last.narration_id:
        for item in plan.narration_texts:
            if item.id == last.narration_id:
                return item.text.strip()
        return ""
    return (last.subtitle_text or "").strip()
