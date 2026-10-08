"""narration 命名空间：规划（plan_variants / list_plans / get_plan）与风格清单。
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
    mode_recommend,
    overlap,
    script_driver,
    scriptwriter,
    variant_scoring,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.conversion import defects, grade
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.llm_client import LlmConfig, LlmUnavailable
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra import config
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PROJECT_NOT_FOUND = -32101
_ERR_NO_ANALYSIS = -32301
_ERR_MODE_UNSUPPORTED = -32302
_ERR_VARIANTS_OUT_OF_RANGE = -32303
_ERR_PLAN_NOT_FOUND = -32304
_ERR_LLM = -32305
_ERR_PLAN_NOT_RENDERABLE = -32407

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

# 界面 K 选择器的上限。再往上选题 prompt 会退化成让模型凑数，
# 而凑出来的角度正是重叠度量要拦的东西——不如在这里就拦掉。
_MAX_VARIANTS = 8


def register(router: Router, context: AppContext) -> None:
    router.register("narration.plan_variants", lambda params: plan_variants(context, params))
    router.register("narration.list_plans", lambda params: list_plans(context, params))
    router.register("narration.get_plan", lambda params: get_plan(context, params))
    router.register("narration.list_styles", lambda _params: list_styles(context))
    router.register("narration.recommend_modes", lambda params: recommend_modes(context, params))
    router.register("narration.llm_traces", lambda params: llm_traces(context, params))
    router.register("narration.plan_trace", lambda params: plan_trace(context, params))
    router.register("narration.generate_titles", lambda params: generate_titles(context, params))
    router.register("narration.update_titles", lambda params: update_titles(context, params))


def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """项目方案列表；给了 batch_id 就只取那一组（阶段③ 按组显示）。

    B10 软排序：有分数的方案按 score_total 降序（平局按 variant_index 确定性），
    全无分数时 `rank_variants` 原样返回——顺序与评分上线前逐字节一致。
    排序只动列表顺序，不动任何行的字段，更不动 grade。
    """
    project_id = str(params.get("project_id", ""))
    batch_id = params.get("batch_id")
    if batch_id is not None:
        rows = plans_repo.list_by_batch(context.conn, project_id, str(batch_id))
    else:
        rows = plans_repo.list_by_project(context.conn, project_id)
    return variant_scoring.rank_variants([_annotate_gate(row) for row in rows])


def _annotate_gate(row: dict[str, Any]) -> dict[str, Any]:
    """给方案卡补上过不了门禁的原因；不改落库 status。"""
    try:
        issues = defects(PlanData.model_validate(row["plan_data"]))
    except (TypeError, ValueError):
        issues = ["方案数据损坏"]
    if not issues:
        return row
    annotated = dict(row)
    annotated["block_reason"] = issues[0]
    return annotated


def generate_titles(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """LLM 生成候选标题并落库（导出时自动补；也可手动再生成）。"""
    from dramaclip.engines.narration import titles as titles_engine

    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    try:
        titles = titles_engine.generate(
            row["plan_data"],
            context.settings,
            trace_path=llm_trace_dir(context) / f"llm_titles_{plan_id}.json",
        )
    except LlmUnavailable as exc:
        raise RpcDomainError(_ERR_LLM, str(exc)) from exc
    except ValueError as exc:
        raise RpcDomainError(_ERR_LLM, str(exc)) from exc
    plans_repo.set_titles(context.conn, plan_id, json.dumps(titles, ensure_ascii=False))
    return {"titles": titles}


def update_titles(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """保存候选标题（整表替换：文本/采用标记由详情页编辑后提交）。"""
    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    titles = params.get("titles")
    if not isinstance(titles, list) or not all(
        isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip()
        for t in titles
    ):
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, "titles 格式无效")
    cleaned = [
        {"text": str(t["text"]).strip(), "selected": bool(t.get("selected"))}
        for t in titles
    ]
    plans_repo.set_titles(context.conn, plan_id, json.dumps(cleaned, ensure_ascii=False))
    return {"titles": cleaned}



def get_plan(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条方案详情 + 成本账（规格 §5 #18 阶段③ 详情、#33 成品库跳回方案）。
    """
    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    return {"plan": _annotate_gate(row), "cost": plan_cost(row)}


def plan_cost(row: dict[str, Any]) -> dict[str, int]:
    """一条方案的成本账（规格 §4.4 成本预估卡的数据源）。
    """
    plan = PlanData.model_validate(row["plan_data"])
    voiced = len(plan.narration_texts)
    return {"copy_llm_calls": 1 if voiced else 0, "tts_calls": voiced}


def list_styles(context: AppContext, _params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return styles_lib.list_styles()


def _effective_settings(context: AppContext, project_id: str) -> dict[str, str]:
    """全局默认 + 项目级覆盖（规格 §4.3 的「默认 + 覆盖」）。
    """
    settings = dict(context.settings)
    for key, value in projects_repo.get_settings(context.conn, project_id).items():
        if value is not None:
            settings[str(key)] = str(value)
    return settings


@dataclass(frozen=True)
class _Variant:
    """一条待产出的方案：取材意图（名字/理由/集号）+ 成稿时注入的角度块。
    """

    name: str
    reason: str
    episode_numbers: list[int]
    angle_block: str


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


def plan_variants(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段③：为选中模式各产出 K 条方案，只规划不渲染（规格 §6 的拆分）。
    """
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    modes = [str(mode) for mode in params.get("modes", [])]
    invalid = [mode for mode in modes if mode not in SUPPORTED_MODES]
    if invalid:
        raise RpcDomainError(_ERR_MODE_UNSUPPORTED, f"模式暂未支持: {', '.join(invalid)}")
    if not modes:
        raise RpcDomainError(_ERR_MODE_UNSUPPORTED, "至少选择一个模式")
    done_episodes = [
        episode
        for episode in episodes_repo.list_by_project(context.conn, project_id)
        if episode["status"] == "done"
    ]
    if not done_episodes:
        raise RpcDomainError(_ERR_NO_ANALYSIS, "没有已完成分析的集，请先运行智能分析")

    settings = _effective_settings(context, project_id)
    raw_k = params.get("k")
    k = (
        config.get_int(settings, "narration.variants_per_mode")
        if raw_k is None
        else int(raw_k)
    )
    if not 1 <= k <= _MAX_VARIANTS:
        raise RpcDomainError(
            _ERR_VARIANTS_OUT_OF_RANGE,
            f"方案数 K 必须在 1~{_MAX_VARIANTS} 之间，实得 {k}",
        )
    exclude_plan_ids = [str(item) for item in params.get("exclude_plan_ids", [])]
    excluded_angles = _excluded_angle_names(context, exclude_plan_ids)

    job_id = context.job_store.create("narration", ref_id=project_id)
    # 提交规格随项目设置持久化：页面重进/重启后，规划队列据此还原「模式×条数」骨架
    projects_repo.update_settings(
        context.conn,
        project_id,
        {"last_plan_batch": {"batch_id": job_id, "modes": list(modes), "k": int(k)}},
    )
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        context.notifier.tracked(
            job_id,
            _run_plan_variants,
            context,
            job_id,
            project_id,
            done_episodes,
            modes,
            k,
            excluded_angles,
            bool(exclude_plan_ids),
            cancel_event,
        )
    )
    return {"job_id": job_id, "k": k, "batch_id": job_id}


def _excluded_angle_names(context: AppContext, exclude_plan_ids: list[str]) -> list[str]:
    """重掷此条：把被替换方案的角度名交给选题，别再提同一个卖点。
    """
    names: list[str] = []
    for plan_id in exclude_plan_ids:
        row = plans_repo.get(context.conn, plan_id)
        if row is None:
            raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
        if row["angle"]:
            names.append(str(row["angle"]))
    return names


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
        context.job_store.mark_running(job_id)
        settings = _effective_settings(context, project_id)
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
        _settle_failed(context, job_id, f"规划任务异常终止: {type(exc).__name__}: {exc}")
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
    if not LlmConfig.from_settings(settings).configured:
        return  # 没配 LLM 的项目：静默跳过，不发请求不留错误
    rows = plans_repo.list_by_batch(context.conn, project_id, job_id)
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


def _angle_variants(
    context: AppContext,
    mode: str,
    label: str,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    k: int,
    excluded_angles: list[str],
) -> list[_Variant]:
    """解说类：一次选题调用 → K 条卖点互异的角度（《定案二》）。
    """
    briefs = angles.select_angles(
        mode,
        mode_label=label,
        k=k,
        episode_inputs=episode_inputs,
        settings=settings,
        excluded=excluded_angles,
        trace_dir=llm_trace_dir(context),
    )
    return [
        _Variant(
            name=brief.name,
            reason=brief.reason,
            episode_numbers=brief.episode_numbers,
            angle_block=angles.prompt_block(brief),
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
        return script_driver.script_dialogue_plan(
            scoped, settings, angle_block=variant.angle_block, trace_dir=trace_dir
        )

    scenes, highlights, material = _casting_for(context, episodes, variant)
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
    used_ids = sorted({segment.episode_id for segment in plan.timeline})
    return plan, used_ids


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


def _voice(
    context: AppContext,
    plan: PlanData,
    settings: dict[str, str],
    source_durations: dict[str, float],
) -> PlanData:
    """出片前配音出口：规划阶段不调用。负责给出 tts 目录与 models 目录。

    `source_durations`（{集 id: 源片秒数}）交给回填做越界判定——回填会把段尾改成
    `start + 实测音频时长`，跑出源长的窗口 ffmpeg 不报错、只把旁白截掉（业主立案③的
    另一半，判据见 `pipeline._assert_within_source`）。缺键由 pipeline 判失败，
    这里不兜底：拿不到源长就等于无法证明这条片子不会被截断。
    """
    return narration_pipeline.synthesize_narration_texts(
        plan,
        settings,
        context.work_dir / "tts",
        context.data_dir / "models",
        source_durations=source_durations,
        log=context.notifier.log,
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
            }
        )
    return inputs


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


def recommend_modes(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """AI 模式推荐（阶段①）：按题材与高光推 3 个模式，随项目缓存可重算。"""
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    refresh = bool(params.get("refresh"))
    result = mode_recommend.recommend(context.conn, project_id, context.settings, refresh=refresh)
    return {"modes": result["modes"]}


def llm_traces(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """最近的 LLM 往返留痕清单（规划队列的「LLM 往返」入口数据源）。"""
    trace_dir = llm_trace_dir(context)
    if trace_dir is None or not trace_dir.is_dir():
        return {"traces": []}
    limit = min(int(params.get("limit") or 30), 100)
    files = sorted(trace_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return {
        "traces": [
            {"name": f.name, "size": f.stat().st_size, "mtime": int(f.stat().st_mtime * 1000)}
            for f in files
        ]
    }


def plan_trace(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """读一份 LLM 往返留痕原文（system/user/attempts 全量）。"""
    name = Path(str(params.get("name", ""))).name  # basename 化：路径穿越在此终结
    trace_dir = llm_trace_dir(context)
    path = trace_dir / name if trace_dir is not None else None
    if path is None or path.suffix != ".json" or not path.is_file():
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"往返记录不存在：{name}")
    return {"name": name, "content": path.read_text(encoding="utf-8", errors="replace")}
