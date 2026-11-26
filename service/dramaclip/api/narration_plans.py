"""narration 方案产出执行族：角度选题 → 逐条成稿 → 重叠裁决 → 落库评分。

自 api/narration.py 拆出（拆分专项 B）：RPC 受理/查询/标题留在 narration.py，
本模块承载 job 池里真正跑的规划执行体（评分与复述质检块已下沉 flows/narration.py，
工程债 ② 首切）。模式集合常量随执行族走（选题与裁决
都按它分流），narration.py 单向引回 SUPPORTED_MODES/_NO_TTS_MODES；
_effective_settings 留守（RPC 层受理期也要读），执行体惰性导入。
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.narration import (
    casting,
    copywriter,
    diversity,
    overlap,
    script_driver,
    scriptwriter,
    story_arc,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.conversion import grade
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.narration.plan_inputs import (
    audio_of,
    parse_beats,
    parse_conflicts,
    parse_highlights,
    scene_cuts_of,
    scored_windows_of,
    silences_of,
    visual_frames_of,
)
from dramaclip.engines.semantic.llm_client import LlmQuotaExceeded
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.flows.narration import (
    _angle_variants,
    _card_hint,
    _collect_prior_texts,
    _deterministic_variants,
    _reject_same_episode_sibling,
    _retell_gate,
    _rewrite_copy_until_retellable,
    _score_batch,
    _slot_label,
    _Variant,
    _worst_overlap,
)
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo

# 真名映射（v0.2.5 2.2）：project.settings 单键（JSON 串，角色标签→真名）。
# 存放裁决=强项目归属数据挂 projects.settings（migration 028 热词同款先例：
# 全局表是跨剧泄漏源；随 project.duplicate 自动复制）。
SPEAKER_MAPPING_SETTINGS_KEY = "speaker.mapping"

SUPPORTED_MODES = (
    "raw_clip",
    # 高光混剪（highlight_cut）2026-10-27 业主裁决并入纯原片剪辑（raw_clip 单入口，
    # 5 秒均切取消），2026-11-12 完全清除：生成/渲染/消费分支全删，存量方案行由
    # migrations/027 删除，历史推荐缓存由 mode_recommend 读时净化。

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
_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow"})
# 零文案模式（=_NO_TTS_MODES）：没有旁白槽位，母题/钩子/句式约束无处落地——
# 选题换零文案专用提示词（只挑跨集冲突链并命名，_REEL_SYSTEM_PROMPT），失败回落
# 单集锚定（_deterministic_variants）。2026-10-20 业主裁决：单集锚定当主路线不
# 合适——吸引力在跨集因果链。
_ZERO_COPY_MODES = _NO_TTS_MODES

# 会产出旁白槽位、因而读 `settings["_style_directives"]` 的模式（copywriter /
# scriptwriter 两侧都只往解说槽位里塞风格指令）。派生自上面两个集合，绝不另立
# 第四份手抄模式清单——纯剪辑作业连口味层的答案都无人可读，不该为它付选题往返。
_NARRATION_MODES = frozenset(SUPPORTED_MODES) - _NO_TTS_MODES


def expected_copy_source(mode: str) -> str:
    """该模式的方案文案应当来自哪里：``llm_script``（LLM 成稿）或 ``rule``（规则预算）。

    「模式 → 来源」的唯一判定接口：verify_modes 与方案卡徽章都从它取判据，不许
    另立第二份手抄模式表（2026-10-16 规格 §1.1；手抄表漏条目的漂移实证——那次
    漏的是高光混剪，该模式已于 2026-11-12 完全移除，教训照旧成立）。
    """
    return "rule" if mode in _NO_TTS_MODES else "llm_script"

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
                            "error",
                            "不可恢复错误（鉴权/额度/磁盘），规划停批——"
                            "修复配置后重新规划",
                        )
                        raise
                    if consecutive_failures >= 3:
                        context.notifier.log(
                            "error",
                            f"连续 {consecutive_failures} 条方案失败，规划停批"
                            "——检查网络/模型配置后重新规划",
                        )
                        raise
                else:
                    consecutive_failures = 0
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


def _casting_for(
    context: AppContext,
    episodes: list[dict[str, Any]],
    variant: _Variant,
    *,
    speaker_mapping: dict[str, str] | None = None,
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
        conflicts = parse_conflicts(record["conflict_scores"])
        if not conflicts:
            # 分析过但一个冲突场景都没出：这一集对时间轴贡献为零。留痕而不是静默剔除，
            # 否则卡片上的「取材集区间」会列一集实际上一帧都没出现的集（规格 §3.3）。
            context.notifier.log(
                "info", f"第 {number} 集没有冲突场景，本条方案取不到它的画面"
            )
        scenes_by_episode.append((number, episode_id, conflicts))
        highlights.extend(parse_highlights(record["highlights"]))
        audio = audio_of(record.get("audio_features"))
        material[episode_id] = casting.EpisodeMaterial(
            number=number,
            asr=_apply_speaker_mapping(
                narration_pipeline.parse_asr_segments(record["asr_segments"]),
                speaker_mapping,
            ),
            beats=parse_beats(record["audio_features"]),
            # 语义层声画对位：画面轨帧进逐段填词（_slot_block 按取材区间切片消费）；
            # 未跑视觉轨的集空元组，槽位块落到「无画面轨」分档，行为不变。
            frames=tuple(visual_frames_of(record.get("visual_track"))),
            # 声学静音图（T1 质批）：语音区间补集，句界吸附的精修依据
            silences=silences_of(audio),
        )
    return casting.stamp(scenes_by_episode), highlights, material


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
    episode_inputs = _collect_episode_inputs(
        context, episodes, _speaker_mapping_of(settings)
    )
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


def _speaker_mapping_of(settings: dict[str, str]) -> dict[str, str]:
    """settings 里的真名映射（JSON 串）；缺失/坏 JSON/形不对一律空表——映射是
    增强不是义务，不为它付「这条方案出不了片」的代价。"""
    raw = settings.get(SPEAKER_MAPPING_SETTINGS_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in parsed.items()
        if str(key).strip() and str(value).strip()
    }


def _apply_speaker_mapping(
    segments: list[Any], mapping: dict[str, str] | None
) -> list[Any]:
    """真名映射应用（v0.2.5 2.2）：[角色X] → 真名在原料装配时落定——编剧/文案/
    audit 三链的「推断真名」从 LLM 猜变为确定性输入。未映射标签原样保留；
    空映射原列表直通（与 2.2 之前逐字节一致）。"""
    if not mapping:
        return segments
    out: list[Any] = []
    for seg in segments:
        if seg.speaker and seg.speaker in mapping:
            seg = seg.model_copy(update={"speaker": mapping[seg.speaker]})
        out.append(seg)
    return out


def _collect_episode_inputs(
    context: AppContext,
    episodes: list[dict[str, Any]],
    speaker_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """收集全部完成集的转写输入（跨集剧本原料），按集号升序。"""
    inputs: list[dict[str, Any]] = []
    for episode in sorted(episodes, key=lambda ep: int(ep["episode_number"])):
        record = analysis_repo.get(context.conn, str(episode["id"]))
        if record is None:
            continue
        segments = _apply_speaker_mapping(
            narration_pipeline.parse_asr_segments(record["asr_segments"]),
            speaker_mapping,
        )
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
                "scene_cuts": scene_cuts_of(record.get("scene_data")),
                # 画面轨（P2c·文画咬合）：逐帧画面实据；未跑视觉轨的集空表（分档语义）
                "visual_track": visual_frames_of(record.get("visual_track")),
                # 冲突高峰与高光（带评分与理由）：选题模型据此绑集与定母题——
                # 关键拍在哪些集，看档案不看猜。旧库缺列时空表，档案块整体缺席。
                "conflict_scores": scored_windows_of(record.get("conflict_scores")),
                "highlights": scored_windows_of(record.get("highlights")),
            }
        )
    return inputs
