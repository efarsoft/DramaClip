"""narration 方案产出执行族：角度选题 → 逐条成稿 → 重叠裁决 → 落库评分。

自 api/narration.py 拆出（拆分专项 B）：RPC 受理/查询/标题留在 narration.py，
本模块承载 job 池里真正跑的规划执行体。模式集合常量随执行族走（选题与裁决
都按它分流），narration.py 单向引回 SUPPORTED_MODES/_NO_TTS_MODES；
_effective_settings 留守（RPC 层受理期也要读），执行体惰性导入。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.engines.narration import (
    angles,
    casting,
    copywriter,
    overlap,
    script_driver,
    scriptwriter,
    variant_scoring,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.conversion import grade
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.llm_client import is_configured
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo

SUPPORTED_MODES = (
    "raw_clip",
    "highlight_cut",
    "intro_narration",
    "cross_narration",
    "ultra_short_hook",
    "dialogue_narration",
    "full_narration",
    "subtitle_flow",
    "dual_host_chat",
    "inner_monologue",
)

# 与 TTS 合成并行的两组：剧情解说已由 LLM 剧本驱动，每段都要配音，不再属"无 TTS"。
_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow", "highlight_cut"})
# 零文案模式（=_NO_TTS_MODES）：没有旁白槽位，母题/钩子/句式约束无处落地——
# 选题换零文案专用提示词（只挑跨集冲突链并命名，_REEL_SYSTEM_PROMPT），失败回落
# 单集锚定（_deterministic_variants）。2026-10-20 业主裁决：单集锚定当主路线不
# 合适——吸引力在跨集因果链。
_ZERO_COPY_MODES = _NO_TTS_MODES

# 会产出旁白槽位、因而读 `settings["_style_directives"]` 的模式（copywriter /
# scriptwriter 两侧都只往解说槽位里塞风格指令）。派生自上面两个集合，绝不另立
# 第四份手抄模式清单——纯剪辑作业连口味层的答案都无人可读，不该为它付选题往返。
_NARRATION_MODES = frozenset(SUPPORTED_MODES) - _NO_TTS_MODES

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


def _run_plan_variants(
    context: AppContext,
    job_id: str,
    project_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    k: int,
    excluded_angles: list[str],
    rerolled: bool,
    cancel_event: threading.Event,
) -> None:
    """逐模式取 K 条方案意图 → 逐条成稿落库（配音推迟到勾选出片）。"""
    try:
        from dramaclip.api import narration as narration_api

        context.job_store.mark_running(job_id)
        settings = narration_api._effective_settings(context, project_id)
        try:
            episode_inputs = _inject_run_settings(context, settings, episodes, modes)
        except Exception as exc:  # noqa: BLE001 - 任务级装配失败必须落进 jobs 表，不能留 running
            _settle_failed(context, job_id, str(exc))
            context.notifier.log("error", f"任务上下文装配失败: {exc}")
            return

        total = len(modes) * k
        done_count = 0
        failures: list[str] = []
        for mode in modes:
            if cancel_event.is_set():
                break
            label = narration_pipeline.MODE_LABELS.get(mode, mode)
            try:
                if mode in _ZERO_COPY_MODES:
                    try:
                        variants = _angle_variants(
                            context,
                            mode,
                            label,
                            episode_inputs,
                            settings,
                            k,
                            excluded_angles,
                            zero_copy=True,
                        )
                    except Exception as exc:  # noqa: BLE001 - 选线失败回落单集锚定
                        context.notifier.log(
                            "warning",
                            f"{label} 跨集选线失败，回落单集锚定：{str(exc)[:80]}",
                        )
                        variants = _deterministic_variants(
                            context, mode, label, episode_inputs, k, excluded_angles
                        )
                else:
                    variants = _angle_variants(
                        context, mode, label, episode_inputs, settings, k, excluded_angles
                    )
            except Exception as exc:  # noqa: BLE001 - 取意图失败 = 这个模式的 K 条全没了
                # 按 K 条记账：界面才不会把「这个模式一条都没出」显示成「这个模式本来就没有方案」
                for i in range(1, k + 1):
                    line = f"{label}·第{i}条: {exc}"
                    failures.append(line)
                    context.job_store.append_detail(job_id, line)
                context.notifier.log("error", f"{label} 取方案意图失败: {exc}")
                done_count += k
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), f"{label} 选题失败"
                )
                continue

            accepted: list[tuple[_Variant, PlanData]] = []
            for index, variant in enumerate(variants, start=1):
                if cancel_event.is_set():
                    break
                tag = f"{label}·{_slot_label(variant, index)}"
                try:
                    _reject_same_episode_sibling(mode, variant, accepted)
                    plan, used_ids = _plan_one(
                        context, mode, episodes, episode_inputs, settings, variant
                    )
                    worst = _worst_overlap(plan, accepted)
                    if worst is not None and worst.ratio > overlap.OVERLAP_LIMIT:
                        raise ValueError(
                            f"取材与「{worst.name}」重叠 {worst.ratio:.0%}，"
                            f"超过 {overlap.OVERLAP_LIMIT:.0%}——这条角度不出（规格 §4.3）"
                        )
                    plans_repo.create(
                        context.conn,
                        project_id,
                        mode,
                        used_ids,
                        plan.model_dump(),
                        status=grade(plan),
                        angle=variant.name,
                        angle_reason=variant.reason,
                        variant_index=index,
                        overlap_max=None if worst is None else worst.ratio,
                        batch_id=job_id,
                    )
                    accepted.append((variant, plan))
                except Exception as exc:  # noqa: BLE001 - 单条方案失败不中断兄弟与其他模式
                    failures.append(f"{tag}: {exc}")
                    context.job_store.append_detail(job_id, failures[-1])
                    context.notifier.log("error", f"{tag} 方案失败: {exc}")
                done_count += 1
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), tag
                )
                # 模式间间隔：九模式同时发选题会触发 QPS 上限
                time.sleep(3)

        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
        elif failures:
            detail = "; ".join(failures)
            context.job_store.mark_failed(job_id, detail)
            context.notifier.log("error", f"部分方案失败: {detail}")
        else:
            context.job_store.set_progress(job_id, 100.0)
            context.job_store.mark_completed(job_id)
        # B10 尾部评分在 job 落终态**之后**跑：job 的成败与时长只由方案生成决定，
        # 评分慢/炸都不影响已定的终态（业主红线：评分失败不挡方案生成）。
        # 取消的作业不评分：用户已经不要这批的后续动作了。
        if not cancel_event.is_set():
            _score_batch(context, job_id, project_id, settings)
    except Exception as exc:  # noqa: BLE001 - 逐变体守卫之外的抛出没人接就是一行永停 running
        reason = f"规划任务异常终止: {type(exc).__name__}: {exc}"
        # 落库之外必须上日志面板：只写 jobs 行的异常，用户在日志里翻不到痕迹
        context.notifier.log("error", reason)
        _settle_failed(context, job_id, reason)
    finally:
        context.cancel_events.pop(job_id, None)


def _score_batch(
    context: AppContext, job_id: str, project_id: str, settings: dict[str, str]
) -> None:
    """B10 尾部评分：整批一次 LLM 往返，写三列软信号。

    任何失败（未配置/网关坏/产出全废）都只留一句日志：评分是排序信号，
    绝不让规划 job 因它变红——job 的成败只由方案生成本身决定。
    grade/defects 在此零触碰：`set_scores` 只写 score_* 与 suggestion 三列。
    """
    if not is_configured(settings):
        return  # 没配 LLM 的项目：静默跳过，不发请求不留错误
    rows = plans_repo.list_by_batch(context.conn, project_id, job_id)
    if not rows:
        return
    # 纯原片剪辑/字幕金句流/高光混剪设计上就没有旁白文案：拿「文案六维」去评它们，
    # 评分器只能给全 1 分外加一句「补上开场首句口播」——那是把设计当缺陷报。
    # 真机实测：1.0 分把这三个模式永久踩在方案列表底部，建议还劝用户给不该有
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
    return [
        _Variant(
            name=brief.name,
            reason=brief.reason,
            episode_numbers=brief.episode_numbers,
            angle_block="" if zero_copy else angles.prompt_block(brief),
            arc=brief.arc,
        )
        for brief in briefs
    ]
def _plan_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    variant: _Variant,
) -> tuple[PlanData, list[str]]:
    """按取材意图产出一条方案（未配音、未落库）。返回 (方案, **实际用到**的集 id)。
    """
    trace_dir = llm_trace_dir(context)

    if mode == "dialogue_narration":
        wanted = set(variant.episode_numbers)
        scoped = [
            episode for episode in episode_inputs if int(episode["number"]) in wanted
        ]
        if not scoped:
            raise ValueError(f"角度「{variant.name}」的取材集都没有转写")
        context.notifier.log(
            "info",
            f"跨集输入：{len(scoped)} 集 → "
            f"每集约 {scriptwriter.transcript_sampling_quota(len(scoped))} 段摘录",
        )
        plan, used_ids = script_driver.script_dialogue_plan(
            scoped, settings, angle_block=variant.angle_block, trace_dir=trace_dir
        )
        return plan.model_copy(update={"arc": variant.arc}), used_ids

    scenes, highlights, material = _casting_for(context, episodes, variant)
    # 字幕金句流的金句判定交给 LLM（2026-10-08 业主裁决「规则打分不可靠，
    # LLM 提取」）：按集编号回填零幻觉，LLM 不可用时 modes_w9 回退规则打分
    golden = None
    if mode == "subtitle_flow":
        from dramaclip.engines.narration import golden_lines as golden_mod

        dialogue_by_episode = {
            episode_id: [
                (no, seg.start, seg.end, seg.text)
                for no, seg in enumerate(entry.asr, start=1)
            ]
            for episode_id, entry in material.items()
        }
        golden = golden_mod.pick_for_material(settings, dialogue_by_episode)
    plan = narration_pipeline.build_plan(
        mode,
        scenes,
        highlights,
        material,
        settings,
        # 超短钩子的可行性选景要在规划期知道每集有多长（钩子/CTA 预算放不放得下），
        # 不能等 TTS 实测回填才爆——2026-10-06 真机：61 字钩子把 CTA 顶出集尾。
        source_durations={
            str(episode["id"]): float(episode["duration"] or 0.0) for episode in episodes
        },
        golden_lines=golden,
    )
    if not plan.timeline:
        # 空时间轴的方案渲染出来是一部 0 秒的片；规划期就该说清楚，不留到导出
        raise ValueError(
            f"取材集 {sorted(set(variant.episode_numbers))} 没有可用素材，这条角度出不了片"
        )
    if plan.narration_texts:
        # 规则类两个模式走不到这里（它们的编排器不产槽位），故 angle_block 恒为空串
        # 也不会被任何人读到——这不是"悄悄留了个空值"，是两族的会合点本来就用不上它。
        # material 按集分开传：跨集时间轴上每个槽位只能读它自己那一集的台词（Task 4 Step 3b）。
        plan = copywriter.write_plan_copy(
            plan,
            material,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
        )
        plan = _rewrite_copy_until_retellable(
            context,
            plan,
            material,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
        )
    used_ids = sorted({segment.episode_id for segment in plan.timeline})
    return plan.model_copy(update={"arc": variant.arc}), used_ids


def _rewrite_copy_until_retellable(
    context: AppContext,
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None,
) -> PlanData:
    """复述驱动的重写循环：初稿不达标 → 带卡点重写一次 → 择优保留（批 ① 下半）。

    择优判据：重写稿复述达标才换血，否则保原稿（重写是有成本的，不靠新鲜感换血）。
    重写走同一 copywriter 链，feedback 只喂复述卡点与缺失项——让模型知道哪里
    听不懂，而不是让它自由发挥。
    """
    first_report = _retell_gate(plan, settings, trace_dir, context.notifier)
    if first_report is None or first_report.passed:
        return plan
    if settings.get("narration.rewrite_loop", "1") != "1":
        return plan

    notes = [f"复述卡点：{c.get('note', '')}" for c in first_report.confusions[:4]]
    notes.extend(first_report.reasons)
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

    second_report = _retell_gate(rewritten, settings, trace_dir, context.notifier)
    if second_report is not None and second_report.passed:
        context.notifier.log("info", "重写稿复述达标，采用重写稿")
        return rewritten
    context.notifier.log("warning", "重写稿复述仍未达标，保留原稿")
    return plan


def _retell_gate(
    plan: PlanData,
    settings: dict[str, str],
    trace_dir: Path | None,
    notifier: Any,
) -> Any | None:
    """复述测试（软质检）：无上下文观众闭卷复述，结论进 trace 供审计；失败不阻塞出片。

    返回 RetellReport 供重写循环取卡点；关闭/跳过/失败返回 None——retell 走
    真实 LLM 客户端，桩覆盖不到就别让它等（如测试桩环境）。
    """
    from dramaclip.engines.narration.retell import retell_check
    from dramaclip.engines.semantic.llm_client import client_for

    if settings.get("narration.retell_check", "1") != "1":
        return None
    text = "\n".join(item.text for item in plan.narration_texts)
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
        (trace_dir / "retell.json").write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    notifier.log(
        "info" if report.passed else "warning",
        f"复述测试：{report.summary_line()}"
        + (f"（首条卡点：{report.confusions[0]['note']}）" if report.confusions else ""),
    )
    return report


def _casting_for(
    context: AppContext,
    episodes: list[dict[str, Any]],
    variant: _Variant,
) -> tuple[list[EpisodeScene], list[HighlightSegment], MaterialByEpisode]:
    """把意图点名的那几集装配成编排器要吃的三样东西（场景表 / 高光表 / 逐集台词）。
    """
    wanted = sorted(set(variant.episode_numbers))
    by_number = {int(episode["episode_number"]): episode for episode in episodes}
    missing = [number for number in wanted if number not in by_number]
    if missing:
        raise ValueError(f"取材集 {missing} 不在已完成分析的集里")

    scenes_by_episode: list[tuple[int, str, list[ConflictScore]]] = []
    highlights: list[HighlightSegment] = []
    material: MaterialByEpisode = {}
    for number in wanted:
        episode_id = str(by_number[number]["id"])
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            raise ValueError(f"第 {number} 集分析记录缺失（本条方案点名要取它）")
        conflicts = _parse_conflicts(record["conflict_scores"])
        if not conflicts:
            # 分析过但一个冲突场景都没出：这一集对时间轴贡献为零。留痕而不是静默剔除，
            # 否则卡片上的「取材集区间」会列一集实际上一帧都没出现的集（规格 §3.3）。
            context.notifier.log(
                "info", f"第 {number} 集没有冲突场景，本条方案取不到它的画面"
            )
        scenes_by_episode.append((number, episode_id, conflicts))
        highlights.extend(_parse_highlights(record["highlights"]))
        material[episode_id] = casting.EpisodeMaterial(
            number=number,
            asr=narration_pipeline.parse_asr_segments(record["asr_segments"]),
            beats=_parse_beats(record["audio_features"]),
        )
    return casting.stamp(scenes_by_episode), highlights, material


def _parse_beats(raw: str | None) -> tuple[float, ...]:
    """从落库的 audio_features JSON 取拍点表（B9）。

    缺失/坏 JSON 一律返回空元组、**不 raise**：节拍吸附是编排层的意图增强
    （见 engines/narration/beat_align），装配层不为它付「这条方案出不了片」的
    代价；旧库记录没有 beats 字段时同样落到这里，降级为不吸附。
    """
    if not raw:
        return ()
    try:
        return tuple(AudioFeatures.model_validate(json.loads(raw)).beats)
    except (json.JSONDecodeError, ValueError):
        return ()


def _inject_run_settings(
    context: AppContext,
    settings: dict[str, str],
    episodes: list[dict[str, Any]],
    modes: list[str],
) -> list[dict[str, Any]]:
    """任务级一次性注入：项目名、题材、跨集转写、口味层风格。返回跨集输入。
    """
    project_id = str(episodes[0]["project_id"])
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise ValueError(f"项目不存在: {project_id}")
    settings["_project_name"] = str(project["name"])
    record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if record is not None and record["genre"]:
        settings["_genre"] = str(record["genre"])
    episode_inputs = _collect_episode_inputs(context, episodes)
    preferred = settings.get("narration.style_id")
    pinned = bool(preferred) and preferred != styles_lib.AUTO_STYLE_ID
    if any(mode in _NARRATION_MODES for mode in modes) and (episode_inputs or pinned):
        settings["_style_directives"] = str(
            script_driver.resolve_run_style(
                settings,
                episode_inputs,
                log=context.notifier.log,
                trace_dir=llm_trace_dir(context),
            ).get("directives", "")
        )
    return episode_inputs


def _settle_failed(context: AppContext, job_id: str, error: str) -> None:
    """失败落库；行已终态时只记日志，绝不用记账错误顶掉原始异常。
    """
    try:
        context.job_store.mark_failed(job_id, error)
    except Exception as exc:  # 记账失败不该盖掉业务失败：原因一并写进日志
        context.notifier.log(
            "error", f"任务 {job_id} 状态写入失败({exc})；原始原因：{error}"
        )


def _collect_episode_inputs(
    context: AppContext,
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """收集全部完成集的转写输入（跨集剧本原料），按集号升序。"""
    inputs: list[dict[str, Any]] = []
    for episode in sorted(episodes, key=lambda ep: int(ep["episode_number"])):
        record = analysis_repo.get(context.conn, str(episode["id"]))
        if record is None:
            continue
        segments = narration_pipeline.parse_asr_segments(record["asr_segments"])
        if not segments:
            continue
        inputs.append(
            {
                "number": int(episode["episode_number"]),
                "episode_id": str(episode["id"]),
                "duration": float(episode.get("duration") or 0.0),
                "segments": [
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text,
                        "speaker": seg.speaker,
                    }
                    for seg in segments
                ],
                # 镜头切点（PySceneDetect 边界，秒）：编排层把解说窗吸附到切点上，
                # 剪口落在换镜头处=画面不撕裂。切点缺失（旧库/解析失败）时空表，
                # 编排层原值返回。
                "scene_cuts": _scene_cuts_of(record.get("scene_data")),
                # 画面轨（P2c·文画咬合）：逐帧画面实据；未跑视觉轨的集空表（分档语义）
                "visual_track": _visual_frames_of(record.get("visual_track")),
                # 冲突高峰与高光（带评分与理由）：选题模型据此绑集与定母题——
                # 关键拍在哪些集，看档案不看猜。旧库缺列时空表，档案块整体缺席。
                "conflict_scores": _scored_windows_of(record.get("conflict_scores")),
                "highlights": _scored_windows_of(record.get("highlights")),
            }
        )
    return inputs


def _scored_windows_of(raw: Any) -> list[dict[str, Any]]:
    """[{"start","end","score","reason"}] 形状窗口的宽容解析；坏数据逐条跳过。"""
    try:
        items = json.loads(str(raw)) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    windows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            windows.append(
                {
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "score": float(item.get("score") or 0.0),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return windows


def _visual_frames_of(raw: Any) -> list[dict[str, Any]]:
    """visual_track JSON → 紧凑画面轨条目；缺失/坏数据 → 空表（分档，不报错）。"""
    try:
        track = json.loads(str(raw)) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return []
    frames = track.get("frames") if isinstance(track, dict) else None
    if not isinstance(frames, list):
        return []
    return [frame for frame in frames if isinstance(frame, dict) and frame.get("scene")]


def _parse_conflicts(raw: str | None) -> list[ConflictScore]:
    return [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")]


def _scene_cuts_of(raw: Any) -> list[float]:
    """scene_data 落库是 JSON 字符串：解析出镜头切点表，坏形返回空表不 raise。"""
    try:
        scenes = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(scenes, list):
        return []
    cuts: list[float] = []
    for scene in scenes:
        try:
            cut = round(float(scene["start"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        if cut > 0:
            cuts.append(cut)
    return cuts


def _parse_highlights(raw: str | None) -> list[HighlightSegment]:
    return [HighlightSegment.model_validate(item) for item in json.loads(raw or "[]")]
