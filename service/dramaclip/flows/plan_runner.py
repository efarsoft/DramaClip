"""规划执行体：逐模式取 K 条意图 → 逐条成稿落库 → 尾部评分。

自 api/narration_plans.py 逐字下沉（2026-11-26 工程债 ② 收尾批，语义零变化）：
job 池里真正跑的规划主流程。`_effective_settings`（全局默认 + 项目级覆盖）随
执行体走——执行开始与 RPC 受理期读的是同一份装配，只有一个定义点。
"""

from __future__ import annotations

import contextlib
import json
import threading
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.api.job_runner import launch_threaded_job
from dramaclip.engines.narration import (
    copywriter,
    diversity,
    overlap,
    script_driver,
    scriptwriter,
    story_arc,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.conversion import grade
from dramaclip.engines.narration.mode_vocab import _ZERO_COPY_MODES
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.llm_client import LlmQuotaExceeded
from dramaclip.flows.narration import (
    _angle_variants,
    _card_hint,
    _casting_for,
    _collect_prior_texts,
    _deterministic_variants,
    _inject_run_settings,
    _reject_same_episode_sibling,
    _retell_gate,
    _rewrite_copy_until_retellable,
    _score_batch,
    _settle_failed,
    _slot_label,
    _speaker_mapping_of,
    _Variant,
    _worst_overlap,
)
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo

#: 每条方案之间的间隔（秒）。2026-09-15 与 429 退避同批引入，防「九模式连发选题」
#: 触发 QPS 上限。单列成常量是为了测试能打桩——规划用例不必各睡几轮 3 秒
#: （2026-11-26 实测占全量套件近四成）；等待可被取消打断。
_VARIANT_GAP_S = 3.0


def _effective_settings(context: AppContext, project_id: str) -> dict[str, str]:
    """全局默认 + 项目级覆盖（规格 §4.3 的「默认 + 覆盖」）。
    """
    settings = dict(context.settings)
    for key, value in projects_repo.get_settings(context.conn, project_id).items():
        if value is not None:
            settings[str(key)] = str(value)
    return settings


# 渲染类前台作业：预合成不与导出/成片自检抢 TTS worker、ffmpeg 与显存。
_FRONT_BUSY_TYPES = frozenset({"export", "export_selfcheck"})


def _front_busy(context: AppContext) -> bool:
    """渲染类前台作业是否在跑（入队守卫与逐段让位共用同一判据）。"""
    types = {row.get("type") for row in context.job_store.list_recent(active_only=True)}
    return bool(types & _FRONT_BUSY_TYPES)


def _presynth_eligible(context: AppContext) -> bool:
    """预合成入队守卫：没有渲染类前台作业在跑、也没有同类预合成在跑。"""
    types = {row.get("type") for row in context.job_store.list_recent(active_only=True)}
    return not _front_busy(context) and "narration_presynth" not in types


def _presynth_work(
    context: AppContext,
    job_id: str,
    plans: list[PlanData],
    settings: dict[str, str],
    cancel_event: threading.Event,
) -> str | None:
    """narration_presynth 作业体：逐方案预热配音缓存，进度上账面。

    与导出同一路径、同一 work_dir（`context.work_dir / "tts"`），产物与缓存键
    完全一致，出片阶段真引擎零调用。预热失败只在日志留痕不拦批（语义见
    `presynthesize_plan_audio`）；取消在方案间生效，已备好的段保留。
    `pause_when` 逐段让位：入队守卫只挡得住入队瞬间，导出可能在预热中途发起
    （本地克隆系单 worker 进程，不让位就把导出关键路径逐段往后顶）。
    """
    slots = sum(len(plan.narration_texts) for plan in plans)
    if slots == 0:
        return None  # 纯台词剪辑批（无旁白）没有可预热的，静默收官
    warmed = 0
    for plan in plans:
        got, _total = narration_pipeline.presynthesize_plan_audio(
            plan,
            settings,
            context.work_dir / "tts",
            context.data_dir / "models",
            data_dir=context.data_dir,
            log=context.notifier.log,
            cancel=cancel_event,
            pause_when=lambda: _front_busy(context),
        )
        warmed += got
        context.job_store.set_progress(job_id, round(warmed / slots * 100, 1), "预合成配音")
        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
            return None
        if _front_busy(context):
            return (
                f"后台预合成为导出让路: {warmed}/{slots} 段已备"
                "（其余出片时照常真合成，导出完可重新规划再预热）"
            )
    if warmed < slots:
        return f"后台预合成部分完成: {warmed}/{slots} 段就绪（失败段出片时照常真合成）"
    return f"后台预合成完成: {warmed} 段配音已备好，出片直接用"


def _settle_plan_batch(
    context: AppContext,
    job_id: str,
    project_id: str,
    settings: dict[str, str],
    presynth_candidates: list[PlanData],
    cancel_event: threading.Event,
    failures: list[str],
) -> None:
    """批收尾三件事按既定次序：终态落账 → 尾部评分 → 预合成入队。

    B10：评分在 job 落终态**之后**跑——job 的成败与时长只由方案生成决定，评分
    慢/炸都不影响已定的终态（业主红线：评分失败不挡方案生成）；取消的作业不评分。
    C1：规划干净收官（无失败、无取消）且批内有落库方案时，入队 narration_presynth
    把配音缓存先热好——出片的 TTS 是耗时大头，规划→选稿→出片之间的人工间隔足以
    备齐缓存，出片阶段直接命中。守卫：渲染类作业在跑不抢资源；已有预合成在跑不
    重复入队；纯台词批（无旁白）进作业体后静默空转；预热失败不反咬规划。
    """
    if cancel_event.is_set():
        context.job_store.mark_cancelled(job_id)
    elif failures:
        detail = "; ".join(failures)
        context.job_store.mark_failed(job_id, detail)
        context.notifier.log("error", f"部分方案失败: {detail}")
    else:
        context.job_store.set_progress(job_id, 100.0)
        context.job_store.mark_completed(job_id)
    if not cancel_event.is_set():
        _score_batch(context, job_id, project_id, settings)
        if not failures and presynth_candidates and _presynth_eligible(context):
            launch_threaded_job(
                context,
                job_type="narration_presynth",
                ref_id=project_id,
                work=lambda _jid, _cancel: _presynth_work(
                    context, _jid, presynth_candidates, settings, _cancel
                ),
                failure_message=lambda exc: f"后台预合成失败: {exc}",
                thread_prefix="presynth",
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
        context.job_store.mark_running(job_id)
        settings = _effective_settings(context, project_id)
        speaker_mapping = _speaker_mapping_of(settings)
        try:
            settings["_prior_texts_json"] = json.dumps(
                _collect_prior_texts(context, project_id), ensure_ascii=False
            )
        except Exception as exc:  # noqa: BLE001 - 既往稿读不了＝跨稿查重退化为同稿内，不挡生成
            context.notifier.log("warning", f"同剧既往稿读取失败，跨稿查重退化为同稿内: {exc}")
        try:
            episode_inputs = _inject_run_settings(context, settings, episodes, modes)
        except Exception as exc:  # noqa: BLE001 - 任务级装配失败必须落进 jobs 表，不能留 running
            _settle_failed(context, job_id, str(exc))
            context.notifier.log("error", f"任务上下文装配失败: {exc}")
            return

        total = len(modes) * k
        done_count = 0
        failures: list[str] = []
        # 规划熔断（第二梯队②）：连续 3 条方案失败 → 停批（费钱的 LLM 调用
        # 不再逐条烧完 K 条变体）；鉴权/额度耗尽/磁盘满类不可恢复 → 第一条
        # 失败就停（重试没有意义）。ASR/TTS 域外错误照旧逐条跳过。
        consecutive_failures = 0
        # C1 预合成的候选：本批成功落库的方案（失败/超重叠的不预热）。
        presynth_candidates: list[PlanData] = []
        for mode in modes:
            if cancel_event.is_set():
                break
            label = narration_pipeline.MODE_LABELS.get(mode, mode)
            # 批量变异三件套（第一梯队①）：策略卡队列随模式重洗（同模式 K 版
            # 表达骨架错开）；past_copies 攒本模式已产文案做避重与闸门基准。
            strategy_cards = diversity.strategy_queue(k)
            past_copies: list[str] = []
            # 跨任务历史预填（W9·跨片避重）：批内三件套只看得到本批——追更场景
            # 「上次那条视频」的表达趋同它看不见。同项目近期成稿预填进基准；
            # 预取失败只少一层保护，不挡生成。
            with contextlib.suppress(Exception):
                past_copies.extend(_collect_prior_texts(context, project_id))
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
                            "warning", f"{label} 跨集选线失败，回落单集锚定：{str(exc)[:80]}"
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
                    # auto+母题配方：清任务级 _style_directives（题材静态映射的
                    # 节拍指令），让母题情绪配方独占文风——两套节拍永不同场；
                    # 人工显式选了风格则保留 directives、配方让位。
                    suppress_directives = (
                        not styles_lib.is_manual_style(settings)
                        and bool(story_arc.card_of(variant.arc))
                    )
                    saved_directives = settings.get("_style_directives")
                    if suppress_directives:
                        settings["_style_directives"] = ""
                    try:
                        plan, used_ids = _plan_one(
                            context, mode, episodes, episode_inputs, settings, variant,
                            variant_hint=_card_hint(strategy_cards, index - 1),
                            next_hint=_card_hint(strategy_cards, index),
                            past_copies=past_copies or None,
                            speaker_mapping=speaker_mapping,
                        )
                    finally:
                        if suppress_directives:
                            if saved_directives is None:
                                settings.pop("_style_directives", None)
                            else:
                                settings["_style_directives"] = saved_directives
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
                    presynth_candidates.append(plan)
                    past_copies.append(
                        "\n".join(item.text for item in plan.narration_texts)
                    )
                except Exception as exc:  # noqa: BLE001 - 单条方案失败不中断兄弟与其他模式
                    failures.append(f"{tag}: {exc}")
                    context.job_store.append_detail(job_id, failures[-1])
                    context.notifier.log("error", f"{tag} 方案失败: {exc}")
                    consecutive_failures += 1
                    _msg = str(exc)
                    _fatal = (
                        isinstance(exc, LlmQuotaExceeded)
                        or "401" in _msg
                        or "403" in _msg
                        or "磁盘" in _msg
                        or "disk" in _msg.lower()
                    )
                    if _fatal:
                        context.notifier.log(
                            "error", "不可恢复错误（鉴权/额度/磁盘），规划停批——修复配置后重新规划"
                        )
                        raise
                    if consecutive_failures >= 3:
                        context.notifier.log(
                            "error", f"连续 {consecutive_failures} 条方案失败，规划停批——"
                            "检查网络/模型配置后重新规划"
                        )
                        raise
                else:
                    consecutive_failures = 0
                done_count += 1
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), tag
                )
                if mode != modes[-1] or index < len(variants):
                    # 变体间隔见 _VARIANT_GAP_S 注释：取消即醒；末条之后无下一条，不再等
                    cancel_event.wait(_VARIANT_GAP_S)

        _settle_plan_batch(
            context, job_id, project_id, settings,
            presynth_candidates, cancel_event, failures,
        )
    except Exception as exc:  # noqa: BLE001 - 逐变体守卫之外的抛出没人接就是一行永停 running
        reason = f"规划任务异常终止: {type(exc).__name__}: {exc}"
        # 落库之外必须上日志面板：只写 jobs 行的异常，用户在日志里翻不到痕迹
        context.notifier.log("error", reason)
        _settle_failed(context, job_id, reason)
    finally:
        context.cancel_events.pop(job_id, None)


def _plan_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    variant: _Variant,
    *,
    variant_hint: str = "",
    next_hint: str = "",
    past_copies: list[str] | None = None,
    speaker_mapping: dict[str, str] | None = None,
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
            scoped,
            settings,
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
            past_copies=past_copies,
        )
        # 复述质检接入（此前只覆盖逐槽族，最重的剧本链反而没有质检）。不达标
        # 只留痕不自动重写：整稿重写＝与首稿同价的 LLM 往返（逐槽族「改写若干槽」
        # 的 economics 在剧本链不成立），是否自动换血等不达标率数据说话（数据反馈
        # harness）——卡点进通知面与 trace，人工裁决「重掷此条」。
        _retell_gate(plan, settings, trace_dir, context.notifier, context=context)
        return plan.model_copy(update={"arc": variant.arc}), used_ids

    scenes, highlights, material = _casting_for(
        context, episodes, variant, speaker_mapping=speaker_mapping
    )
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
        mode_label = narration_pipeline.MODE_LABELS.get(mode, mode)
        plan = copywriter.write_plan_copy(
            plan,
            material,
            settings,
            mode_label=mode_label,
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
            variant_hint=variant_hint,
            past_copies=past_copies,
        )
        # 相似度闸门（第一梯队①）：新稿与同模式已产稿高相似 → 换下一张策略卡
        # 避重重写一次 → 取相似度更低者（不新增时间预算，换血不换故事）。
        if past_copies:
            first_text = "\n".join(item.text for item in plan.narration_texts)
            if diversity.too_similar(first_text, past_copies):
                context.notifier.log(
                    "info",
                    f"{variant.name} 文案与已产稿过似（3-gram 相似度超阈），"
                    "换策略卡避重重写一次",
                )
                try:
                    alt = copywriter.write_plan_copy(
                        plan,
                        material,
                        settings,
                        mode_label=mode_label,
                        angle_block=variant.angle_block,
                        trace_dir=trace_dir,
                        variant_hint=next_hint or variant_hint,
                        past_copies=past_copies,
                        rewrite_notes="与旧稿表达过似：换开头方式与组织结构重写，"
                        "事实与取材不变",
                    )
                    alt_text = "\n".join(item.text for item in alt.narration_texts)
                    picked = diversity.least_similar(first_text, alt_text, past_copies)
                    if picked is alt_text:
                        plan = alt
                except Exception as exc:  # noqa: BLE001 - 避重重写失败保首稿
                    context.notifier.log(
                        "warning", f"避重重写失败保留首稿：{str(exc)[:100]}"
                    )
        plan = _rewrite_copy_until_retellable(
            context,
            plan,
            material,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
            angle_name=variant.name,
        )
    used_ids = sorted({segment.episode_id for segment in plan.timeline})
    return plan.model_copy(update={"arc": variant.arc}), used_ids
