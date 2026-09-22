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
