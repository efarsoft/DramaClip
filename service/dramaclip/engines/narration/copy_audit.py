"""逐槽文案（copywriter 链路）审查。

自 audit.py 拆出（拆分专项）：copy 层审查只消费 lines/slots 两个输入，与
script 审查（review_script）是两个独立目标——前者审「逐槽填词是否守住槽位
契约」，后者审「剧本结构与基本功层」。复用 audit 的 Finding / ReviewReport /
规则原文注册表（_RULES）与共享正则（_METANARRATIVE_RE / _SPEAKER_LABEL_RE），
单向依赖 audit，不反向。
"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.narration.audit import _METANARRATIVE_RE, _SPEAKER_LABEL_RE
from dramaclip.engines.narration.findings import Finding, ReviewReport
from dramaclip.engines.narration.prompt_rules import RULE_TEXTS as _RULES


def review_copy(
    lines: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    mode: str = "",
) -> ReviewReport:
    """审查 copywriter 结构指令 + 逐槽基本功约束。

    lines: 模型输出 [{"id","text"}]；slots: 编排器给的 [{"id","task","start","end","lines"}]。
    """
    findings: list[Finding] = []
    from dramaclip.engines.narration.copywriter import _OVERSIZE_TOLERANCE, _line_cap_of
    cap = _line_cap_of(mode)

    line_ids = [line.get("id") for line in lines]
    slot_ids = [slot.get("id") for slot in slots]

    # —— 覆盖全部槽位 id（硬性要求一字不差）——
    missing = [sid for sid in slot_ids if sid not in line_ids]
    findings.append(Finding(
        "COPY_COVER_ALL_IDS", "copy", "hard",
        not missing,
        "lines 覆盖全部槽位 id" if not missing else f"漏覆盖槽位：{missing}",
        location="lines" if missing else "",
        prompt_quote=_RULES["lines_cover_all_slots"],
    ))

    # —— 每条不超过行长上限 ——
    # —— 每条不超过行长上限（验收按生产同款容差：copywriter 收稿按 cap×1.2 放行，
    # 这里若按裸 cap 判，生产已放行的 61–72 字稿在审查里恒 REJECT，假加固建议由此而来）——
    oversize_cap = int(cap * _OVERSIZE_TOLERANCE)
    over = [
        (line.get("id"), len(line.get("text", "")))
        for line in lines
        if len(line.get("text", "")) > oversize_cap
    ]
    findings.append(Finding(
        "COPY_LINE_CAP", "copy", "hard",
        not over,
        f"每条均 ≤ {oversize_cap} 字" if not over else f"超长：{over}",
        location="lines" if over else "",
        prompt_quote=f"每条不超过 {cap} 字；",
    ))

    # —— 禁元叙述（零容忍，同样适用填词）——
    meta_hits = [
        line.get("id")
        for line in lines
        if _METANARRATIVE_RE.search(line.get("text", "") or "")
    ]
    findings.append(Finding(
        "COPY_NO_METANARRATIVE", "copy", "hard",
        not meta_hits,
        "无元叙述字眼" if not meta_hits else f"出现元叙述的槽位：{meta_hits}",
        location=";".join(str(h) for h in meta_hits) if meta_hits else "",
        prompt_quote=_RULES["metanarrative"],
    ))

    # —— 完成「要做的事」（软：空文本 / 明显跑题无法全判，标需人工）——
    empty = [line.get("id") for line in lines if not (line.get("text") or "").strip()]
    findings.append(Finding(
        "COPY_DOES_THE_JOB", "fund_slot", "soft",
        not empty,
        "无空文案槽位" if not empty else f"空文案槽位：{empty}（未完成任务契约）",
        location=";".join(str(e) for e in empty) if empty else "",
        prompt_quote=_RULES["slot_contract"],
        needs_human=True,
    ))

    # —— 声纹换名（软，同剧本）——
    unresolved = [
        line.get("id")
        for line in lines
        if _SPEAKER_LABEL_RE.search(line.get("text", "") or "")
    ]
    findings.append(Finding(
        "COPY_SPEAKER_RESOLVE", "fund_slot", "soft",
        not unresolved,
        "声纹标签已换真名" if not unresolved else f"未解析声纹标签槽位：{unresolved}",
        prompt_quote=_RULES["speaker_tag_realname"],
        needs_human=True,
    ))

    return ReviewReport(target="copy", findings=findings,
                        meta={"mode": mode, "cap": cap, "n_lines": len(lines)})
