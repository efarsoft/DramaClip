"""narration 命名空间：规划（plan_variants / list_plans / get_plan）与风格清单。

规划与渲染在此分开（规格 §6 的拆分）：本模块只产出方案行，一条 status='ready' 的行
就是可渲染的成品输入（含配音音频路径），渲染归 export.submit。
任务级上下文（项目名、题材、跨集转写、口味层风格）统一在 `_inject_run_settings` 装配一次。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.narration import (
    angles,
    casting,
    copywriter,
    overlap,
    script_driver,
    scriptwriter,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.models import PlanData
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

SUPPORTED_MODES = (
    "raw_clip",
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


def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """项目方案列表；给了 batch_id 就只取那一组（阶段③ 按组显示）。"""
    project_id = str(params.get("project_id", ""))
    batch_id = params.get("batch_id")
    if batch_id is not None:
        return plans_repo.list_by_batch(context.conn, project_id, str(batch_id))
    return plans_repo.list_by_project(context.conn, project_id)


def get_plan(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条方案详情 + 成本账（规格 §5 #18 阶段③ 详情、#33 成品库跳回方案）。

    list_plans 一次返回项目全部方案连同整份 plan_data；K×模式条数上来之后它不再是
    「看一条」的合理入口，故单条走这里。
    """
    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    return {"plan": row, "cost": plan_cost(row)}


def plan_cost(row: dict[str, Any]) -> dict[str, int]:
    """一条方案的成本账（规格 §4.4 成本预估卡的数据源）。

    两个数都是恒等推导，故不落库：存下来只多一处会漂的副本（docs/04 §5.2）。
    成稿次数是「有旁白槽位即 1」——§3.3.1 之后不存在「零次 LLM 的解说方案」，
    而 raw_clip / subtitle_flow 没有槽位、确实零次。配音段数就是槽位数。
    **选题往返不在此账上**：它是模式级共担，一个 batch 的选题次数
    = 该 batch 里 DISTINCT narration_mode 的数量。

    **这是"落库口径"，不是"花销口径"，两者可以差**：被成稿后那道重叠闸门拦掉的角度
    已经付了一次成稿，却**不留行**，所以把一个 batch 的 plan_cost 逐条相加会得到
    比真实 LLM 花销**小**的数（最多差 K − 已落库条数）。P-2a 把可判定的那一半前置了
    （`_reject_same_episode_sibling`：同模式同集的两条角度，其时间轴是 (mode, episode_id)
    的纯函数，故重叠必然 100%，成稿前即可拦，一次成稿都不付）；剩下的残余只在
    `dialogue_narration` 上——它的剧本由模型按角度现写，成稿前无从判定。
    详见《定案二》的 R7 段。规格 §4.4 的成本卡是**提交前的预估**（渲染成本），
    与本函数的口径不同，两者不要互相顶替。
    """
    plan = PlanData.model_validate(row["plan_data"])
    voiced = len(plan.narration_texts)
    return {"copy_llm_calls": 1 if voiced else 0, "tts_calls": voiced}


def list_styles(context: AppContext, _params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return styles_lib.list_styles()


def _effective_settings(context: AppContext, project_id: str) -> dict[str, str]:
    """全局默认 + 项目级覆盖（规格 §4.3 的「默认 + 覆盖」）。

    覆盖值一律 str() 后叠加：Settings 的值类型是 str，而 projects.settings 是 JSON，
    里面的 K 会是 int——不转就在 config.get_int 的 int() 上侥幸通过、
    在别处的字符串拼接上炸。value 为 None 表示「恢复默认」（P-1 的 update_settings
    语义），故跳过而不是写成字符串 "None"。
    """
    settings = dict(context.settings)
    for key, value in projects_repo.get_settings(context.conn, project_id).items():
        if value is not None:
            settings[str(key)] = str(value)
    return settings


@dataclass(frozen=True)
class _Variant:
    """一条待产出的方案：取材意图（名字/理由/集号）+ 成稿时注入的角度块。

    **两个模式族在这个形状上会合**（《定案四》）：解说类的 name/reason 出自选题模型
    （`angles.AngleBrief`）、angle_block 出自 `angles.prompt_block`；规则类
    （raw_clip / subtitle_flow）的三者一律空串，只有 episode_numbers 有值——
    它来自全剧 top-K 冲突窗的确定性推导，不经任何模型。

    会合的收益是失败粒度、进度记账、重叠闸门、配音、落库这五件事**只写一遍**：
    分流只发生在"这条方案从哪来"，不发生在"这条方案怎么落库"。
    name 为空时点名一律退回「第 N 条」（见 `_slot_label`），不许把空串拼进错误文案。
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

    None 与 0.0 是两件事，落库时必须分得开：前者是「无从比」，后者是「比过、全异」。
    点名走 `_slot_label`：规则类的 name 是空串，直接把空串拼进错误文案会得到
    「取材与「」重叠 …」这种半句话。
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

    这不是启发式，是可证的：`_plan_one` 的非剧本分支里，`variant` 只进 `copywriter` 的
    `angle_block`，**不进 `build_plan`**——Task 3c 之后 `build_plan(mode, scenes,
    highlights, material, settings)` 的五个入参没有一个来自角度名或理由，而 `scenes` 与
    `material` 都由 `_casting_for` 从 `variant.episode_numbers` 确定性装配。故时间轴是
    `(mode, 取材集组合)` 的纯函数：同一组集 ⇒ 同一份场景表 ⇒ 同一条时间轴 ⇒
    Jaccard = 1.0，必然超过 60% 阈值。

    **跨集之后这道闸门不但没失效，覆盖面还大了**：原先它按"同集"判（`episode_id` 相等），
    现在按"同一组集"判（`frozenset` 相等）。两条角度都点 `{3, 7}` 与都点 `{3}` 一样必拦；
    点 `{3, 7}` 与点 `{3, 8}` 则放过去，交给成稿后的 `_worst_overlap` 实量。

    既然成稿前就可判，就不该先付一次 LLM 成稿再拦：被拦的角度不落库，
    那笔钱在 narration_plans 里也无从重算（《定案二》的 R7 段）。

    `dialogue_narration` 走不到这里（它在 `_SCRIPT_DRIVEN_MODES` 里：剧本由模型按角度
    现写，**同一组集**也能写出两条压在几乎同一段画面上的剧本，成稿前无从判定），
    那条残余由成稿后的 `_worst_overlap` 兜住——
    `test_post_copy_overlap_gate_still_guards_cross_episode_modes` 钉住那道兜底没被拆掉。
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

    K 的取值顺序：入参 > 项目级覆盖 > 全局默认。回显实际用的 K，界面不必自己算一遍。
    所有可同步判定的错都在派发作业之前抛——进了作业就只是一条 failed 行，
    界面拿不到错误码（docs/service/01 §4 长任务模式第 1 步）。

    **条数按模式族分别算**（规格 §4.3 ④，用户定案）：解说类 = K 条角度，
    规则类 = 全剧 top-K 冲突窗（按集去重后可少于 K，规格 §1 允许 1..K 条）。
    分流在 runner 里，本入口对两族一视同仁：它只管把 K 与模式收下来、把错抛在派发前。
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
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
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
    return {"job_id": job_id, "k": k, "batch_id": job_id}


def _excluded_angle_names(context: AppContext, exclude_plan_ids: list[str]) -> list[str]:
    """重掷此条：把被替换方案的角度名交给选题，别再提同一个卖点。

    方案不存在在此抛（RPC 边界），不留到作业里——那只会变成一条 failed 行。
    规则类方案的 angle 是空串，故它贡献不出排除项（《定案四》：规则类的重掷是空操作，
    由 runner 如实留痕，不在这里假装排除了什么）。
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
    """逐模式取 K 条方案意图 → 逐条 成稿+配音+落库。

    **两族分流只发生在下面那个 `if mode in _NARRATION_MODES`**（《定案四》）：
    解说类的 K 条来自 `angles.select_angles`（一次 LLM 调用），规则类
    （raw_clip / subtitle_flow）的 K 条来自全剧 top-K 冲突窗（**零 LLM**，
    规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」）。分流之后，
    失败粒度、进度记账、重叠闸门、配音、落库五件事走同一段代码（`_Variant` 是会合点）。

    失败粒度是**单条方案**：try/except 包在变体循环**内**，一条的 LLM/TTS 失败
    既不带走它的 K-1 个兄弟，也不带走别的模式。这是 P-1.5「失败粒度=单条方案」
    从模式级下沉到变体级。
    """
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
                if mode in _NARRATION_MODES:
                    variants = _angle_variants(
                        context, mode, label, episode_inputs, settings, k, excluded_angles
                    )
                else:
                    variants = _rule_variants(
                        context, label, episodes, k, rerolled=rerolled
                    )
            except Exception as exc:  # noqa: BLE001 - 取意图失败 = 这个模式的 K 条全没了
                # 按 K 条记账：界面才不会把「这个模式一条都没出」显示成「这个模式本来就没有方案」
                failures.extend(f"{label}·第{i}条: {exc}" for i in range(1, k + 1))
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
                    plan = _voice(context, plan, settings)
                    plans_repo.create(
                        context.conn,
                        project_id,
                        mode,
                        used_ids,
                        plan.model_dump(),
                        angle=variant.name,
                        angle_reason=variant.reason,
                        variant_index=index,
                        overlap_max=None if worst is None else worst.ratio,
                        batch_id=job_id,
                    )
                    accepted.append((variant, plan))
                except Exception as exc:  # noqa: BLE001 - 单条方案失败不中断兄弟与其他模式
                    failures.append(f"{tag}: {exc}")
                    context.notifier.log("error", f"{tag} 方案失败: {exc}")
                done_count += 1
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), tag
                )

        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
        elif failures:
            detail = "; ".join(failures)
            context.job_store.mark_failed(job_id, detail)
            context.notifier.log("error", f"部分方案失败: {detail}")
        else:
            context.job_store.set_progress(job_id, 100.0)
            context.job_store.mark_completed(job_id)
    except Exception as exc:  # noqa: BLE001 - 逐变体守卫之外的抛出没人接就是一行永停 running
        _settle_failed(context, job_id, f"规划任务异常终止: {type(exc).__name__}: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


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

    选题失败即整个模式失败（按 K 条记账，见 runner）：不许拿残缺的凑数，
    那是 §3.3.1 禁止级「假装有 K 条」。

    **没有 `cross_episode` 这个入参**（2026-09-12 裁决后从 `angles.select_angles` 删掉了）：
    规格 §1 的「跨集方案」是每个模式的定义性属性，不是某几个模式的开关。
    """
    briefs = angles.select_angles(
        mode,
        mode_label=label,
        k=k,
        episode_inputs=episode_inputs,
        settings=settings,
        excluded=excluded_angles,
        trace_dir=context.data_dir / "logs" / "llm",
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


def _rule_variants(
    context: AppContext,
    label: str,
    episodes: list[dict[str, Any]],
    k: int,
    *,
    rerolled: bool,
) -> list[_Variant]:
    """规则类（raw_clip / subtitle_flow）：全剧冲突窗排名 → 轮转发成 K 手，一手一条方案。

    规格 §4.3 ④「规则类 = 全剧 top-K 冲突窗（两者不同源，已由用户定案）」定的是**条数**，
    规格 §1「跨集方案」定的是**每条的形状**；轮转发窗同时满足两者（《定案四》第 2 点、
    `pipeline.deal_windows` 的 docstring）。§4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」
    照旧：**本函数不发任何网络请求**——把它们拖进 `angles.select_angles` 就等于把
    "不依赖 LLM"改成"依赖 LLM"，而 select_angles 对未配置抛 LlmUnavailable，
    纯剪辑作业会整族失败（B2/R1）。`test_rule_modes_never_construct_an_llm_client` 钉住。

    name/reason/angle_block 一律空串（《定案四》第 4 点）：规则类没有模型自选的卖点角度，
    也没有旁白槽位去读钩子；界面卡片靠「取材集区间」+ variant_index 区分。
    窗口出处改走 notifier 逐条留痕——那是 §3.3 要求的可见性通道，也是"为什么是这几集"
    唯一可核对的记录。
    """
    scored: list[tuple[int, list[ConflictScore]]] = []
    for episode in episodes:
        record = analysis_repo.get(context.conn, str(episode["id"]))
        if record is None:
            continue
        scored.append(
            (int(episode["episode_number"]), _parse_conflicts(record["conflict_scores"]))
        )
    # limit 给"全部集数"：榜单在这里的用途是**给全集排名**，条数由下面的发窗决定。
    # max(..., 1) 只为让 scored 为空时落到下面那句"无从取窗"，而不是 limit<1 的抛错——
    # 两条都是失败，但前者说的是产品事实，后者说的是调用方传错了参数。
    windows = narration_pipeline.top_conflict_windows(scored, max(len(scored), 1))
    if not windows:
        raise ValueError(f"{label}：全剧没有任何带冲突分的场景，无从取窗")
    hands = narration_pipeline.deal_windows(windows, k)
    if len(hands) < k:
        # 规格 §1 允许「每模式产出 1..K 条」，但 §3.3 禁止静默：少出必须留痕，
        # 否则界面会把「这个模式只出了 N 条」显示成「这个模式本来就只能出 N 条」。
        context.notifier.log(
            "info",
            f"{label}：全剧只有 {len(windows)} 集带冲突窗，轮转发窗只够 {len(hands)} 手，"
            f"本模式出 {len(hands)} 条（规格 §1 的 1..K 条）",
        )
    thin = sum(1 for hand in hands if len(hand) < 2)
    if thin:
        # 集数 < 2 × K 时必有手退化成一集：互不相交的多集手至少需要 2 × K 集。
        # 这是算术不是缺陷，但界面卡片写着"跨集方案"，实际只取一集时必须说清楚。
        context.notifier.log(
            "info",
            f"{label}：全剧只有 {len(windows)} 集带冲突窗、不足 2×{k} 集，"
            f"其中 {thin} 手只取到一集（跨集需要至少 2×K 集才发得开）",
        )
    if rerolled:
        # 窗口榜是确定性的，且规则类的 angle 是空串（贡献不出排除项）：
        # 「重掷此条」对规则类必然原样再出同一条方案。如实说出来，别让用户以为生效了。
        context.notifier.log(
            "info",
            f"{label}：规则类方案由全剧冲突榜确定性推导，「重掷此条」不会改变结果；"
            "要换方案请改方案数或补素材（《定案四》）",
        )
    for rank, hand in enumerate(hands, start=1):
        context.notifier.log(
            "info",
            f"{label}·第 {rank} 条：取第 {'、'.join(str(number) for number in hand)} 集"
            "（全剧冲突窗轮转发窗，不经选题模型）",
        )
    return [
        _Variant(name="", reason="", episode_numbers=hand, angle_block="")
        for hand in hands
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

    取材集由意图决定、且一条方案可以横跨多集（规格 §1），不再恒取 episodes[0]——
    那是「K 条其实是同一部片切 K 次」的根源之一。

    返回的集 id 从**建好的时间轴**反推，不用意图点名的那份：编排器可能一帧都没用上
    某一集（活库实测 `intro_narration` 一手点了 4 集、时间轴上只出现 2 集，因为
    `_fit_duration` 按播出序填充、预算在第 2 集就用完了），照点名写进
    `narration_plans.episode_ids` 会让卡片的「取材集区间」列一集没出现的集——
    那是 §9.5 的假文案类。`script_driver.script_dialogue_plan` 早就是这么做的
    （它的 used_ids 逐字是 `sorted({seg.episode_id for seg in plan.timeline})`），
    这里沿用同一个口径。

    **不落库**：`plans_repo.create` 只在 runner 里发生一次，那里才有 batch_id /
    variant_index / overlap_max 三个只有 runner 知道的值。

    **两个分支的缺号守卫不对称，是有意的**：非剧本分支经 `_casting_for` 自己校验缺号
    （它从 `episodes`——全部 done 集——装配，那份清单比选题看到的宽）；剧本分支直接过滤
    `episode_inputs`，不再校验一遍，因为 `angles._sanitize` 的 `known_numbers` 逐字就是
    `{int(ep["number"]) for ep in episode_inputs}`——**同一份清单**。在这里再抄一道守卫，
    就是 docs/04 §5.2 禁止的"同一概念双处定义"，而且两处一旦漂移（例如 `_collect_episode_inputs`
    将来放宽成"没有转写也收进来"），先炸的是那条抄来的。
    """
    trace_dir = context.data_dir / "logs" / "llm"

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
    plan = narration_pipeline.build_plan(mode, scenes, highlights, material, settings)
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

    集身份在这里注入（`casting.stamp`）：`episode_analysis.conflict_scores` 是**按集一行**
    的 JSON，集身份就是那一行的主键，所以活库已有的分析结果一行都不用改、
    不需要迁移、也不需要重跑分析（《修订记录》C3）。

    点名集不在已完成集里时**一次点名全部缺号**再抛：逐个抛会让第一条缺号掩盖其余的，
    运维补完一集再跑又炸一集。绝不悄悄换一集顶上，也绝不只用点得到的那几集——被本函数
    取代的老写法是 `_generate_one` 里无条件的一句 `episode_id = str(episodes[0]["id"])`，
    那正是「K 条其实是同一部片切 K 次」的根源之一（每条方案都取第 1 集）。
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
        )
    return casting.stamp(scenes_by_episode), highlights, material


def _inject_run_settings(
    context: AppContext,
    settings: dict[str, str],
    episodes: list[dict[str, Any]],
    modes: list[str],
) -> list[dict[str, Any]]:
    """任务级一次性注入：项目名、题材、跨集转写、口味层风格。返回跨集输入。

    风格指令只有会产出旁白槽位的模式才读得到，故按 `modes` 设闸：纯剪辑作业
    一次选题都不付。转写只是 **AI 自选**风格的原料——用户钉死了风格就没有自选
    这回事，没有转写也照样要把用户选的风格注进去（否则既丢风格又丢那句留痕）。
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
                settings, episode_inputs, log=context.notifier.log
            ).get("directives", "")
        )
    return episode_inputs


def _settle_failed(context: AppContext, job_id: str, error: str) -> None:
    """失败落库；行已终态时只记日志，绝不用记账错误顶掉原始异常。

    `JobStore._transition` 对终态行抛 `ValueError("任务已终态")`。它从兜底 handler 里
    逃出去就落进 executor 的 future——没人 `.result()` 就没人读，原始原因连一行日志都
    不留。兜底路径自己会抛，等于"失败没人接"这条线断在最后一环。
    """
    try:
        context.job_store.mark_failed(job_id, error)
    except Exception as exc:  # 记账失败不该盖掉业务失败：原因一并写进日志
        context.notifier.log(
            "error", f"任务 {job_id} 状态写入失败({exc})；原始原因：{error}"
        )


def _voice(context: AppContext, plan: PlanData, settings: dict[str, str]) -> PlanData:
    """配音：plan_variants 唯一的配音出口，只负责给出 tts 目录与 models 目录。

    **路径隔离不是本函数的事**：文件名由 `pipeline._content_addressed_audio` 按
    `(slot_id, text, voice, engine)` 内容寻址（commit 9b42f24），同名 即同内容，
    所以 K 条同模式变体、并发的两个作业、重规划的两轮都不可能互相覆盖。
    本函数**不得**给这个目录加作业号/变体号/随机数——那会让 pipeline 的缓存优先
    在 api 层失效（`test_tts_audio_isolation.py::test_identical_copy_is_synthesised_once`
    钉的"同文案不二次付费"），而换不来任何正确性收益；`test_voice_keeps_the_cross_call_cache`
    守着这一条。

    **无条件调用，不要包一层 `if plan.narration_texts`**：无槽位时（raw_clip /
    subtitle_flow）`synthesize_narration_texts` 自己早退，但它先跑 `_assert_voiceable`——
    那是"带旁白段却没有文案表"的静音片唯一会被拦下的地方，跳过它等于把 §3.3.1 的
    禁止级降级从后门放回。

    这些音频文件因此是承重存储：《定案一》让配音归规划侧，方案可能在几小时后、
    几次重启后才被 `export.submit` 渲染，届时读的就是这里回填的 `audio_path`。
    全仓没有任何路径清理 work_dir（`shutil.rmtree` 只出现在 `api/models.py:119`，
    删的是模型目录），这个事实就此成为契约。**并且内容寻址意味着文案相同的两条方案
    共用同一个文件**，所以将来的回收站不能按作业或按时间删——见《P-3 交接规格》第 1 条。
    """
    return narration_pipeline.synthesize_narration_texts(
        plan, settings, context.work_dir / "tts", context.data_dir / "models"
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
                    {"start": seg.start, "end": seg.end, "text": seg.text}
                    for seg in segments
                ],
            }
        )
    return inputs


def _parse_conflicts(raw: str | None) -> list[ConflictScore]:
    return [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")]


def _parse_highlights(raw: str | None) -> list[HighlightSegment]:
    return [HighlightSegment.model_validate(item) for item in json.loads(raw or "[]")]
