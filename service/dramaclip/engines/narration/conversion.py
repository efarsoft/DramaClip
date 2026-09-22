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

    这些是 LLM 幻觉时间戳的三种形状，此前要到渲染期才暴雷；门禁层拦住，
    方案卡直接给出原因。重叠按 episode_id 分组两两比：跨集用相似时间码是
    常态（每集都有自己的相对秒），只有同集内重叠才等于成片重播素材。
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
