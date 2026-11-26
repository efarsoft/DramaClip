"""方案产出的编排执行体：选题变体构建与重叠裁决 + 两块软质检。

自 api/narration_plans.py 逐字下沉（2026-11-26 工程债 ② 分批，语义零变化）：
都不碰 RPC/落方案主流程。`_NO_TTS_MODES`
仍是模式词汇表、留在 narration_plans（expected_copy_source 与渲染审计共用），
这里惰性引入避循环。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.narration import (
    angles,
    copywriter,
    overlap,
    variant_scoring,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import (
    styles as styles_lib,
)
from dramaclip.engines.narration.casting import MaterialByEpisode
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.llm_client import is_configured
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import plans as plans_repo


def _score_batch(
    context: AppContext, job_id: str, project_id: str, settings: dict[str, str]
) -> None:
    """B10 尾部评分：整批一次 LLM 往返，写三列软信号。

    任何失败（未配置/网关坏/产出全废）都只留一句日志：评分是排序信号，
    绝不让规划 job 因它变红——job 的成败只由方案生成本身决定。
    grade/defects 在此零触碰：`set_scores` 只写 score_* 与 suggestion 三列。
    """
    from dramaclip.api.narration_plans import _NO_TTS_MODES  # noqa: PLC0415 - 惰性避循环

    if not is_configured(settings):
        return  # 没配 LLM 的项目：静默跳过，不发请求不留错误
    rows = plans_repo.list_by_batch(context.conn, project_id, job_id)
    if not rows:
        return
    # 纯原片剪辑/字幕金句流设计上就没有旁白文案：拿「文案六维」去评它们，
    # 评分器只能给全 1 分外加一句「补上开场首句口播」——那是把设计当缺陷报。
    # 真机实测：1.0 分把这两个模式永久踩在方案列表底部，建议还劝用户给不该有
    # 旁白的模式加旁白。它们不参与文案评分，score_total 留 NULL，
    # 由 rank_variants 的「无分沉底」处理，顺序语义不变。
    rows = [row for row in rows if row.get("narration_mode") not in _NO_TTS_MODES]
    if not rows:
        return
    try:
        scored = variant_scoring.score_variants(
            rows, settings, trace_dir=llm_trace_dir(context)
        )
    except Exception as exc:  # noqa: BLE001 - 评分失败不挡规划 job（业主红线）
        context.notifier.log("warn", f"方案评分跳过（不影响方案生成）: {exc}")
        return
    for plan_id, entry in scored.items():
        plans_repo.set_scores(
            context.conn,
            plan_id,
            float(entry["total"]),
            entry["dims"],
            str(entry.get("suggestion") or ""),
        )
    context.notifier.log("info", f"方案评分完成：{len(scored)}/{len(rows)} 条")


def _collect_prior_texts(context: AppContext, project_id: str, *, limit: int = 3) -> list[str]:
    """同剧既往稿的解说文本（最近 limit 条 ready）：跨稿人物介绍重复规则的比对源。

    追更观众看的是同剧的多条视频——上一条介绍过的人物这一条再走全套就是浪费。
    只取 ready（draft 是有缺陷被拦下的稿，它的重复不该污染比对基准）；文本直接
    拼槽位 text（不拼 brief），经 settings 进剧本链的 audit（不进生成 prompt，
    不占上下文预算）。
    """
    texts: list[str] = []
    for row in plans_repo.list_by_project(context.conn, project_id):
        if len(texts) >= limit:
            break
        if row.get("status") != "ready":
            continue
        raw = row.get("plan_data")
        try:
            plan_data = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if not isinstance(plan_data, dict):
            continue
        slots = [
            str(item.get("text", "")).strip()
            for item in plan_data.get("narration_texts") or []
            if item.get("text")
        ]
        joined = "\n".join(slots)
        if joined.strip():
            texts.append(joined)
    return texts


def _rewrite_copy_until_retellable(
    context: AppContext,
    plan: PlanData,
    material: MaterialByEpisode,
    settings: dict[str, str],
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None,
    angle_name: str = "",
) -> PlanData:
    """复述驱动的重写循环：初稿不达标 → 带卡点重写一次 → 择优保留（批 ① 下半）。

    择优判据：重写稿复述达标才换血，否则保原稿（重写是有成本的，不靠新鲜感换血）。
    重写走同一 copywriter 链，feedback 只喂复述卡点与缺失项——让模型知道哪里
    听不懂，而不是让它自由发挥。
    """
    first_report = _retell_gate(
        plan, settings, trace_dir, context.notifier, context=context, round_index=1
    )
    if first_report is None or first_report.passed:
        return plan
    if settings.get("narration.rewrite_loop", "1") != "1":
        return plan

    # 卡点带原句定位（quote=哪句卡住）：只给 note（「太密」）不定位，重写模型只能全篇盲改
    notes = [
        f"复述卡点：{c.get('note', '')}（原句：{c.get('quote', '')[:40]}）"
        if c.get('quote') else f"复述卡点：{c.get('note', '')}"
        for c in first_report.confusions[:4]
    ]
    notes.extend(first_report.reasons)
    # 评分器六维诊断并流（2026-10-20 审计①）：两个 LLM 各看一半——复述抓
    # 「听不懂」，评分抓「不吸引」（节奏/钩子/CTA）；只喂复述卡点会把可读但
    # 平的稿放行。单稿调用只在本分支发生（初稿不达标才评），不是每条方案付费。
    try:
        score_note = variant_scoring.score_one(
            plan.model_dump(), angle_name, settings, trace_dir=trace_dir
        )
    except Exception:  # noqa: BLE001 - 诊断是增益不是依赖：任何失败只缺建议
        score_note = None
    if score_note is not None and str(score_note.get("suggestion") or "").strip():
        notes.append(f"评分建议：{str(score_note['suggestion']).strip()}")
    feedback = "；".join(notes)
    context.notifier.log("info", f"复述不达标，带卡点重写一轮（{feedback[:80]}）")
    try:
        rewritten = copywriter.write_plan_copy(
            plan,
            material,
            settings,
            mode_label=mode_label,
            angle_block=angle_block,
            trace_dir=trace_dir,
            rewrite_notes=feedback,
        )
    except Exception as exc:  # noqa: BLE001 - 重写失败保留原稿，不阻塞出片
        context.notifier.log("warning", f"重写失败保留原稿：{str(exc)[:120]}")
        return plan

    second_report = _retell_gate(
        rewritten, settings, trace_dir, context.notifier, context=context, round_index=2
    )
    if second_report is not None and second_report.passed:
        context.notifier.log("info", "重写稿复述达标，采用重写稿")
        return rewritten
    if (
        second_report is not None
        and first_report is not None
        and len(second_report.confusions) < len(first_report.confusions)
        and len(second_report.reasons) < len(first_report.reasons)
    ):
        # 严格更优也换血：卡点 6→2 的重写稿比原稿真实进步，全有全无会把
        # 真改进丢掉白付一轮 LLM（2026-11-04 审查 #4）。
        context.notifier.log(
            "info",
            f"重写稿未达标但严格更优（卡点 {len(first_report.confusions)}→"
            f"{len(second_report.confusions)}，理由 {len(first_report.reasons)}→"
            f"{len(second_report.reasons)}），采用重写稿",
        )
        return rewritten
    context.notifier.log("warning", "重写稿复述仍未达标，保留原稿")
    return plan


def _original_dialogue_annex(context: AppContext, plan: PlanData) -> str:
    """原声窗台词摘录：观众听到的另一半剧情，给复述裁判当上下文。

    每个原声段抽窗内 ASR 行（至多 6 行），标注时间窗——旁白仍是主体（卡点
    quote 定位以旁白为锚），原声做补充；集无分析记录/窗内无台词则该段跳过。
    """
    lines: list[str] = []
    for segment in plan.timeline:
        if segment.audio != "original":
            continue
        try:
            record = analysis_repo.get(context.conn, str(segment.episode_id))
        except Exception:  # noqa: BLE001 - 软质检的增益输入，坏行跳过
            continue
        if record is None:
            continue
        rows = [
            item
            for item in narration_pipeline.parse_asr_segments(
                str(record.get("asr_segments") or "")
            )
            if float(segment.start) - 1e-6 <= item.start < float(segment.end)
        ]
        texts = [row.text for row in rows if str(row.text).strip()][:6]
        if texts:
            lines.append(
                f"〔原声 {float(segment.start):.0f}s-{float(segment.end):.0f}s〕"
                + " ".join(str(t) for t in texts)
            )
    return "\n".join(lines)


def _retell_gate(
    plan: PlanData,
    settings: dict[str, str],
    trace_dir: Path | None,
    notifier: Any,
    *,
    context: AppContext | None = None,
    round_index: int = 1,
) -> Any | None:
    """复述测试（软质检）：无上下文观众闭卷复述，结论进 trace 供审计；失败不阻塞出片。

    裁判读的文本=旁白全文+原声窗台词摘录（context 可得时）：cross/对谈等
    模式剧情大量由原声对白承载，只听旁白必然误报 jump/人物记混，卡点定位
    失真（2026-11-04 审查 #2）。trace 按轮次落盘 retell_N.json——重写循环
    的改前/改后对比证据不再被第二轮覆盖（#3）。
    返回 RetellReport 供重写循环取卡点；关闭/跳过/失败返回 None——retell 走
    真实 LLM 客户端，桩覆盖不到就别让它等（如测试桩环境）。
    """
    from dramaclip.engines.narration.retell import retell_check
    from dramaclip.engines.semantic.llm_client import client_for

    if settings.get("narration.retell_check", "1") != "1":
        return None
    text = "\n".join(item.text for item in plan.narration_texts)
    annex = _original_dialogue_annex(context, plan) if context is not None else ""
    if annex:
        text = f"{text}\n\n{annex}" if text.strip() else annex
    if not text.strip():
        return None
    try:
        client = client_for(settings)
        report = retell_check(text, client)
    except Exception as exc:  # noqa: BLE001 - 软质检任何失败都降级跳过
        notifier.log("warning", f"复述测试跳过：{str(exc)[:120]}")
        return None
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"retell_{round_index}.json").write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    notifier.log(
        "info" if report.passed else "warning",
        f"复述测试：{report.summary_line()}"
        + (f"（首条卡点：{report.confusions[0]['note']}）" if report.confusions else ""),
    )
    return report

# ---------------------------------------------------------------------------
# 选题变体与重叠裁决（②-2 下沉）：api 主循环按它选题、判兄弟重叠。
# ---------------------------------------------------------------------------

# 剧本驱动的唯一模式。2026-09-12 裁决之后**九个模式都能在一条方案里跨集取画面**
# （Task 3c 的 casting 层给六个规则编排器补上了集身份），所以这个集合不再表示
# "只有它能跨集"——那是一句已经作废的话，留着它就是留下一句关于代码的假话。
# 它现在只表示一件事：**这条方案的时间轴不是 (mode, 取材集) 的纯函数**，
# 因为剧本由模型按角度现写（script_driver.script_dialogue_plan）。于是成稿**前**那道
# 重叠闸门（_reject_same_episode_sibling）对它无效，只能靠成稿**后**的 _worst_overlap 兜。
_SCRIPT_DRIVEN_MODES = frozenset({"dialogue_narration"})


@dataclass(frozen=True)
class _Variant:
    """一条待产出的方案：取材意图（名字/理由/集号/母题）+ 成稿时注入的角度块。
    """

    name: str
    reason: str
    episode_numbers: list[int]
    angle_block: str
    arc: str = ""


def _slot_label(variant: _Variant, index: int) -> str:
    """点名用的人读标签：解说类是角度名，规则类没有角度名，退回「第 N 条」。"""
    return variant.name or f"第{index}条"


@dataclass(frozen=True)
class _OverlapHit:
    """与一条已接受兄弟方案的重叠：名字用来点名，比值用来判阈值与落库。"""

    name: str
    ratio: float


def _worst_overlap(
    plan: PlanData, accepted: list[tuple[_Variant, PlanData]]
) -> _OverlapHit | None:
    """与同模式已接受兄弟里最像的那条比；没有兄弟时回 None（不是 0.0）。
    """
    worst: _OverlapHit | None = None
    for index, (variant, other) in enumerate(accepted, start=1):
        ratio = overlap.overlap(plan, other)
        if worst is None or ratio > worst.ratio:
            worst = _OverlapHit(name=_slot_label(variant, index), ratio=ratio)
    return worst


def _reject_same_episode_sibling(
    mode: str, variant: _Variant, accepted: list[tuple[_Variant, PlanData]]
) -> None:
    """成稿**之前**的重叠闸门（R7）：同模式、**同一组取材集**的两条角度，取材必然逐秒相同。
    """
    if mode in _SCRIPT_DRIVEN_MODES:
        return
    wanted = frozenset(variant.episode_numbers)
    for index, (sibling, _plan) in enumerate(accepted, start=1):
        if frozenset(sibling.episode_numbers) == wanted:
            raise ValueError(
                f"取材与「{_slot_label(sibling, index)}」重叠 100%，"
                f"超过 {overlap.OVERLAP_LIMIT:.0%}"
                "——同模式同取材集的两条角度逐秒相同，这条角度不出（规格 §4.3）"
            )


def _deterministic_variants(
    context: AppContext,
    mode: str,
    label: str,
    episode_inputs: list[dict[str, Any]],
    k: int,
    excluded_angles: list[str],
) -> list[_Variant]:
    """零文案模式的兜底取材：按集冲突峰锚定（跨集选线失败时回落，可用性优先）。

    2026-10-20 曾作为主路线，业主否掉——吸引力在跨集因果链，单集锚定出不了。
    现仅当选线 LLM 不可用/不合格时兜底：互异轴=锚定集，天然满足重叠闸门；
    K 封顶于集数；无冲突数据的集排最后（按集号）。
    """
    ranked: list[tuple[int, int]] = []
    for episode in episode_inputs:
        peak = 0
        record = analysis_repo.get(context.conn, str(episode["episode_id"]))
        if record is not None and record.get("conflict_scores"):
            try:
                scores = json.loads(str(record["conflict_scores"]))
                peak = max(
                    (int(s.get("score") or 0) for s in scores if isinstance(s, dict)),
                    default=0,
                )
            except (json.JSONDecodeError, TypeError):
                peak = 0
        ranked.append((peak, int(episode["number"])))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    variants: list[_Variant] = []
    for _peak, number in ranked:
        if len(variants) >= max(1, k):
            break
        name = f"{label}·锚定第{number}集"
        if name in excluded_angles:
            continue
        variants.append(
            _Variant(
                name=name,
                reason=f"以第 {number} 集冲突峰为锚的确定性取材（零文案模式不跑选题模型）",
                episode_numbers=[number],
                angle_block="",
                arc="",
            )
        )
    return variants


def _angle_variants(
    context: AppContext,
    mode: str,
    label: str,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    k: int,
    excluded_angles: list[str],
    zero_copy: bool = False,
) -> list[_Variant]:
    """解说类：一次选题调用 → K 条卖点互异的角度（《定案二》）。

    ``zero_copy``：换零文案选线提示词（只挑跨集冲突链+命名），且不组装
    angle_block——没有旁白槽位，结构卡无人可读。
    """
    briefs = angles.select_angles(
        mode,
        mode_label=label,
        k=k,
        episode_inputs=episode_inputs,
        settings=settings,
        excluded=excluded_angles,
        trace_dir=llm_trace_dir(context),
        zero_copy=zero_copy,
    )
    # 人工显式选了风格：情绪配方让位（两套节拍永不同场，styles.is_manual_style）
    include_style = not styles_lib.is_manual_style(settings)
    return [
        _Variant(
            name=brief.name,
            reason=brief.reason,
            episode_numbers=brief.episode_numbers,
            angle_block=(
                "" if zero_copy
                else angles.prompt_block(brief, include_style=include_style, mode=mode)
            ),
            arc=brief.arc,
        )
        for brief in briefs
    ]


def _card_hint(cards: list[dict[str, str]], position: int) -> str:
    """策略卡 → 注入文案链的一行提示；越界（变体数多于卡数）给空串。"""
    if 0 <= position < len(cards):
        card = cards[position]
        return f"{card['name']}——{card['hint']}"
    return ""
