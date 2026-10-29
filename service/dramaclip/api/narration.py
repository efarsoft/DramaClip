"""narration 命名空间：规划（plan_variants / list_plans / get_plan）与风格清单。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.api.narration_plans import (  # noqa: F401 - _NO_TTS_MODES 供测试经 narration_api 直读
    _NO_TTS_MODES,
    SUPPORTED_MODES,
    _run_plan_variants,
    _scene_cuts_of,
    expected_copy_source,
)
from dramaclip.engines.narration import mode_recommend, variant_scoring
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.llm_client import LlmUnavailable, client_or_none
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
    """给方案卡补上文案来源判据与过不了门禁的原因；不改落库 status。

    「是否降级」是界面拿 copy_source 与 copy_source_expected 拼出来的判读——这里
    只原样陈述两键，不塞布尔结论（2026-10-16 规格 §1.1）。
    """
    annotated = dict(row)
    try:
        plan = PlanData.model_validate(row["plan_data"])
    except (TypeError, ValueError):
        annotated["block_reason"] = "方案数据损坏"
        return annotated
    annotated["copy_source"] = plan.planner
    annotated["copy_source_expected"] = expected_copy_source(plan.mode)
    issues = defects(plan)
    if issues:
        annotated["block_reason"] = issues[0]
    return annotated


def generate_titles(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """LLM 生成候选标题并落库（导出时自动补；也可手动再生成）。"""
    from dramaclip.engines.narration import titles as titles_engine

    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    plan_data = json.loads(row["plan_data"])
    project_row = projects_repo.get(context.conn, str(row["project_id"]))
    drama_name = str(project_row["name"]) if project_row is not None else ""
    episode_span = "、".join(str(e) for e in (row["episode_ids"] or []))
    brief = (
        f"剧名：{drama_name}\n"
        f"取材角度：{row['angle'] or '全剧高光'}\n"
        f"取材集：第 {episode_span} 集"
    )
    try:
        result = titles_engine.generate(
            plan_data,
            context.settings,
            trace_path=llm_trace_dir(context) / f"llm_titles_{plan_id}.json",
            project_brief=brief,
        )
    except LlmUnavailable as exc:
        raise RpcDomainError(_ERR_LLM, str(exc)) from exc
    except ValueError as exc:
        raise RpcDomainError(_ERR_LLM, str(exc)) from exc
    plans_repo.set_titles(context.conn, plan_id, json.dumps(result["titles"], ensure_ascii=False))
    plans_repo.set_publish_meta(
        context.conn,
        plan_id,
        json.dumps(
            {"caption": result["caption"], "tags": result["tags"]}, ensure_ascii=False
        ),
    )
    return {
        "titles": result["titles"],
        "caption": result["caption"],
        "tags": result["tags"],
    }


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


def _scene_cuts_for(context: AppContext, plan: PlanData) -> dict[str, list[float]]:
    """按方案涉及的集收镜头切点表（结构层音画同步：实测重排后段界回吸切点）。

    缺分析记录/坏 scene_data 的集空表——吸附是增强不是义务，与编排层同款分档
    语义（缺切点原值返回），不为它付「出不了片」的代价。
    """
    cuts: dict[str, list[float]] = {}
    for episode_id in sorted({str(seg.episode_id) for seg in plan.timeline}):
        record = analysis_repo.get(context.conn, episode_id)
        if record is not None:
            cuts[episode_id] = _scene_cuts_of(record.get("scene_data"))
    return cuts


def _dialogue_spans_for(
    context: AppContext, plan: PlanData
) -> dict[str, list[tuple[float, float]]]:
    """按方案涉及的集收台词句区间（渲染期挪窗后的句界回吸，与切点吸附同管道）。"""
    spans: dict[str, list[tuple[float, float]]] = {}
    for episode_id in sorted({str(seg.episode_id) for seg in plan.timeline}):
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            continue
        segs = narration_pipeline.parse_asr_segments(str(record.get("asr_segments") or ""))
        spans[episode_id] = [(float(a.start), float(a.end)) for a in segs]
    return spans


def _fit_rewriter(settings: dict[str, str]) -> Callable[[str, int], str | None] | None:
    """装不下画面空隙时的定向收短出口（业主裁决 2026-10-26：重新选取而非判失败）。

    LLM 未配置返回 None——回填侧收到 None 就跳过重写直接走弃段留痕，配音链路
    不因 LLM 缺席而阻断。回调内异常由回填侧逐段兜住（留痕后回退弃段），这里不吞。
    """
    client = client_or_none(settings)
    if client is None:
        return None

    def rewrite(text: str, target_chars: int) -> str | None:
        system = (
            "你是短剧解说编剧。把给定的解说段收短到指定字数以内，"
            '只输出 JSON：{"text": "成稿正文"}。'
            "数字一律写中文；禁元叙述（「画面里」「镜头」「素材」「第X集」一个不许有）。"
        )
        user = (
            f"收短到不超过 {target_chars} 字：保留悬念与主要信息，删形容词、"
            "重复与次要细节，不得新增剧情，不得改口吻。\n"
            f"原文：{text}"
        )
        result = client.chat_json(system, user)
        if not (isinstance(result, dict) and str(result.get("text") or "").strip()):
            # 带格式强化重问一次：收短是保段最后一道闸，格式手滑不该直接升级成弃段。
            result = client.chat_json(
                system + "只输出 JSON 对象，不要任何多余文字、不要代码围栏。", user
            )
        if isinstance(result, dict):
            new_text = str(result.get("text") or "").strip()
            return new_text or None
        return None

    return rewrite


def _voice(
    context: AppContext,
    plan: PlanData,
    settings: dict[str, str],
    source_durations: dict[str, float],
    on_progress: Callable[[int, int], None] | None = None,
) -> PlanData:
    """出片前配音出口：规划阶段不调用。负责给出 tts 目录与 models 目录。

    `source_durations`（{集 id: 源片秒数}）交给回填做越界判定——回填会把段尾改成
    `start + 实测音频时长`，跑出源长的窗口 ffmpeg 不报错、只把旁白截掉（业主立案③的
    另一半，判据见 `pipeline._assert_within_source`）。缺键由 pipeline 判失败，
    这里不兜底：拿不到源长就等于无法证明这条片子不会被截断。
    `on_progress`（已完成段数, 总段数）透传给合成循环——TTS 是导出耗时大头，
    恒 0% 会被当成卡死（业主实测反馈）。
    """
    return narration_pipeline.synthesize_narration_texts(
        plan,
        settings,
        context.work_dir / "tts",
        context.data_dir / "models",
        source_durations=source_durations,
        log=context.notifier.log,
        on_progress=on_progress,
        data_dir=context.data_dir,
        rewrite_for_fit=_fit_rewriter(settings),
        scene_cuts=_scene_cuts_for(context, plan),
        dialogue_spans=_dialogue_spans_for(context, plan),
    )


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
