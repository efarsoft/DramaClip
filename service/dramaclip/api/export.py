"""export 命名空间：submit（按方案排队渲染）/ retry（幂等重跑）/ list / list_works。"""

from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.api.export_audit import (
    _audit_duration,  # noqa: F401 - 测试经 export_api 直呼
    _clock_audit,  # noqa: F401 - 测试经 export_api._clock_audit 直呼
    _declared_duration_s,
    _log_clock_audit,  # noqa: F401 - 测试经 export_api 直呼
    _note_degraded,
    _planned_narration_segments,
    _verify_tts_by_asr,
)
from dramaclip.api.export_covers import (
    _cover_title,  # noqa: F401 - 测试经 export_api 直呼
    _plan_cover_promise,
    crop_dialogue_lines,  # noqa: F401 - 测试经 export_api.crop_dialogue_lines 直呼
    ensure_covers,
    generate_platform_covers,
)
from dramaclip.api.export_covers import _extract_cover as _extract_cover  # noqa: F401 - re-export 供 export_render 延迟导入 + 测试打桩
from dramaclip.api.export_render import (
    _AIGC_MISSING_PRODUCER_MSG,
    _ERR_AIGC_CONFIG,
    _VL_MOOD_TO_BGM,  # noqa: F401 - 测试经 export_api 直呼
    _VOICE_NEEDED_ENGINES,
    ExportRun,
    _cleanup_export_segments,
    _ensure_clone_voice,  # noqa: F401 - 测试经 export_api 直呼
    _ensure_titles,
    _ensure_voiced,
    _episode_paths_of,
    _film_ending_of,
    _load_film_map,
    _needs_voice,
    _pick_bgm_track,  # noqa: F401 - 测试经 export_api 直呼
    render_export,
    tts_audio_by_segment,  # noqa: F401 - 测试经 export_api 直呼
)
from dramaclip.engines.exporter import (
    aigc_metadata,
    encoder,  # noqa: F401 - 测试经 export_api.encoder 打桩 export_plan
    selfcheck,
)
from dramaclip.engines.narration.conversion import defects
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic import llm_budget
from dramaclip.infra.ffmpeg import (
    cover as ffmpeg_cover,  # noqa: F401 - 测试经 export_api.ffmpeg_cover 取模块对象打桩，引用面保留
)
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PLAN_NOT_FOUND = -32401
_LLM_WAIT_BUDGET_S = 30 * 60  # 任务级 LLM 等待预算（只计云端等待，渲染段冻结）
_ERR_NO_PLANS = -32406
_ERR_PLAN_NOT_RENDERABLE = -32407
_ERR_EXPORT_NOT_FOUND = -32404
_ERR_EXPORT_NOT_RETRYABLE = -32405  # 导出域 -32400~-32499（见 common.json x-error-codes）
_ERR_TRASH_FENCE = -32408  # 产物不在数据目录内，拒绝搬移（models.delete 围栏的同款规矩）
_ERR_TRASH_MOVE = -32409  # 移入回收失败（OSError）：宁留记录，不产无法追溯的孤儿文件
_ERR_PUBLISH_DATA = -32410  # 发布数据录入不合法（W8）：宁拒收，不存脏数据污染回流账
_ERR_REPORT_PARAM = -32412  # 报告维度词表外（harness）

_PUBLISH_PLATFORMS = ("抖音", "快手", "视频号", "小红书", "B站", "其他")


def _now_ms() -> int:
    """录入时刻（毫秒）：与 repo 层时间戳同源同单位。"""
    return int(time.time() * 1000)


def register(router: Router, context: AppContext) -> None:
    router.register("export.submit", lambda params: submit(context, params))
    router.register("export.retry", lambda params: retry(context, params))
    router.register("export.list", lambda params: list_exports(context, params))
    router.register("export.list_works", lambda params: list_works(context, params))
    router.register("export.get", lambda params: get_export(context, params))
    router.register("export.ensure_covers", lambda params: ensure_covers(context, params))
    router.register("export.platform_covers", lambda params: platform_covers(context, params))
    router.register("export.delete", lambda params: delete_export(context, params))
    router.register("export.selfcheck", lambda params: selfcheck_batch(context, params))
    router.register("export.set_publish_data", lambda params: set_publish_data(context, params))
    router.register("export.publish_report", lambda params: publish_report(context, params))
    router.register("export.ab_report", lambda params: ab_report(context, params))


def _submit_export(
    context: AppContext,
    *,
    export_id: str,
    project_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
) -> str:
    """建 export 任务 → 注册取消事件 → 投递执行池，返回 job_id。
    """
    job_id = context.job_store.create("export", ref_id=export_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        context.notifier.tracked(
            job_id,
            _run_export,
            context,
            job_id,
            ExportRun(
                export_id=export_id,
                project_id=project_id,
                plan_row=plan_row,
                plan_data=plan_data,
                cancel_event=cancel_event,
            ),
        )
    )
    return job_id


def submit(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段4：把已规划好的方案排队渲染。规划与渲染就此分开。一条方案一个 export job；
    同一次调用里重复的 plan_id 只出一次片；坏的逐条拒绝并给理由，好的一起走。"""
    raw = params.get("plan_ids")
    if not isinstance(raw, list) or not raw:
        raise RpcDomainError(_ERR_NO_PLANS, "plan_ids 必须是非空数组")
    plan_ids = list(dict.fromkeys(str(item) for item in raw))
    # 低盘留痕（稳定收尾批）：剩余 <5GB 记允许型降级——不拦导出（用户自担），
    # 但「盘要满了」必须进任务详情与日志，不能等 sqlite 写炸才发现。
    try:
        import shutil

        free_gb = shutil.disk_usage(context.data_dir).free / 1024**3
        if free_gb < 5.0:
            context.notifier.log(
                "warning",
                f"数据盘剩余仅 {free_gb:.1f}GB（<5GB）：导出可能中途写满失败，"
                "建议清理成品回收站或迁移数据目录（设置 → 存储）",
            )
    except OSError:
        pass  # 探不到不装死：留痕是增强不是义务
    # LLM 额度预检（第二梯队①）：New API 系中转站 3s 探一次余额，
    # 不足留痕警告（fail-open 不拦——充值提示是增强不是义务）。
    try:
        from dramaclip.engines.semantic import llm_quota
        from dramaclip.engines.semantic.llm_client import LlmConfig

        llm_cfg = LlmConfig.from_settings(context.settings)
        if llm_cfg.configured:
            llm_quota.precheck_or_warn(
                llm_cfg,
                lambda msg: context.notifier.log("warning", msg),
            )
    except Exception:  # noqa: BLE001 - 预检自身失败不挡提交
        pass
    if aigc_metadata.missing_producer(context.settings):
        raise RpcDomainError(_ERR_AIGC_CONFIG, _AIGC_MISSING_PRODUCER_MSG)
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for plan_id in plan_ids:
        plan_row = plans_repo.get(context.conn, plan_id)
        if plan_row is None:
            rejected.append({"plan_id": plan_id, "reason": f"编排方案不存在: {plan_id}"})
            continue
        try:
            plan_data = PlanData.model_validate(plan_row["plan_data"])
            _assert_renderable(plan_row, plan_data)
        except RpcDomainError as exc:
            rejected.append({"plan_id": plan_id, "reason": exc.message})
            continue
        project_id = str(plan_row["project_id"])
        voice_issue = _voice_issue_or_none(context, plan_data, project_id)
        if voice_issue is not None:
            rejected.append({"plan_id": plan_id, "reason": voice_issue})
            continue
        export_id = exports_repo.create(
            conn=context.conn,
            project_id=project_id,
            plan_id=plan_id,
            narration_mode=str(plan_row["narration_mode"]),
        )
        job_id = _submit_export(
            context,
            export_id=export_id,
            project_id=project_id,
            plan_row=plan_row,
            plan_data=plan_data,
        )
        accepted.append({"plan_id": plan_id, "export_id": export_id, "job_id": job_id})
    return {"exports": accepted, "rejected": rejected}


def _auto_voice_available(conn: Any, episode_paths: dict[str, str]) -> bool:
    """可行性判定：本剧剧集里是否存在可自动提取的参考段（带说话人的 4~10s 台词）。"""
    from dramaclip.engines.tts import auto_voice

    rows = [{"id": eid, "source_path": src} for eid, src in episode_paths.items()]
    return auto_voice.pick_best_span(conn, rows) is not None


def _voice_issue_or_none(
    context: AppContext, plan_data: PlanData, project_id: str
) -> str | None:
    """出片受理的配音可行性判定：能自动提取就放行，真不行才拒并说清原因。

    克隆引擎 + 未配参考音色时，**自动从剧集提取**（渲染启动时执行，见
    _ensure_clone_voice）——自动化纪律：用户不看素材，音色从哪来不该问用户。
    只有自动提取也不可行（无带说话人的分析）才拒。
    """
    if not plan_data.narration_texts:
        return None  # 纯原片不需要配音
    from dramaclip.api import narration as narration_api
    from dramaclip.engines.tts import auto_voice

    settings = narration_api._effective_settings(context, project_id)
    engine = str(settings.get("tts.engine") or "edge").strip()
    if engine not in _VOICE_NEEDED_ENGINES:
        return None  # edge/kokoro/auto 链首不需要参考音色
    if str(settings.get(f"tts.voice.{engine}") or "").strip():
        return None  # 已有参考音色
    episode_rows = [
        {"id": row["id"], "source_path": row["source_path"]}
        for row in episodes_repo.list_by_project(context.conn, project_id)
    ]
    if auto_voice.pick_best_span(context.conn, episode_rows) is not None:
        return None  # 可自动提取：渲染启动时补齐
    return (
        "无法自动提取参考音色：本剧已完成分析的剧集中没有主角 4 秒以上的连续台词段。"
        "请先完成剧集分析（含说话人），或把配音引擎切到 Edge（云端免费）/ Kokoro（本地）"
    )


def _assert_renderable(plan_row: dict[str, Any], plan_data: PlanData) -> None:
    """提交/重试前的可渲染性守卫：方案行必须是拿去就能渲的成品输入。
    """
    if plan_row["status"] != "ready":
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, f"方案状态为 {plan_row['status']}，不可渲染")
    if not plan_data.timeline:
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, "编排时间轴为空")
    voiced = {text.id: text for text in plan_data.narration_texts}
    for segment in plan_data.timeline:
        if segment.audio not in ("narration", "ducked"):
            continue
        slot = voiced.get(segment.narration_id or "")
        if slot is None or not str(slot.text or "").strip():
            raise RpcDomainError(
                _ERR_PLAN_NOT_RENDERABLE,
                f"旁白段 {segment.episode_id}@{segment.start} 没有解说文案",
            )
    for issue in defects(plan_data):
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, issue)


def retry(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """重试一条失败导出：**复用原 export_id 覆盖写**，不新建记录。"""
    export_id = str(params.get("export_id", ""))
    record = exports_repo.get(context.conn, export_id)
    if record is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    # 可重试判据与 reset_for_retry 的 CAS 条件必须同为一个谓词，否则下面的 Python 检查
    # 与后面的 SQL 复位会各说各话、并发保护失效；故两边都读 exports_repo.STATUS_FAILED。
    if record["status"] != exports_repo.STATUS_FAILED:
        raise RpcDomainError(
            _ERR_EXPORT_NOT_RETRYABLE, f"仅失败记录可重试，当前 {record['status']}"
        )
    plan_id = str(record["narration_plan_id"])
    plan_row = plans_repo.get(context.conn, plan_id)
    if plan_row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    # 守卫排在 CAS 复位之前：注定失败的重试不该把 failed 洗成 pending
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    _assert_renderable(plan_row, plan_data)
    voice_issue = _voice_issue_or_none(context, plan_data, str(record["project_id"]))
    if voice_issue is not None:
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, voice_issue)
    # 复位是 CAS（仅当仍为 failed 才生效）：并发点两次重试时只有一个能复位成功，
    # 另一个在此被判不可重试，避免双双渲染进同一产物路径。
    if not exports_repo.reset_for_retry(context.conn, export_id):
        raise RpcDomainError(_ERR_EXPORT_NOT_RETRYABLE, "该导出已被其他请求抢先重试")
    job_id = _submit_export(
        context,
        export_id=export_id,
        project_id=str(record["project_id"]),
        plan_row=plan_row,
        plan_data=plan_data,
    )
    return {"job_id": job_id, "export_id": export_id}


def list_exports(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = exports_repo.list_by_project(context.conn, str(params.get("project_id", "")))
    return [_decode_json_columns(row, ("selfcheck",)) for row in rows]


def get_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条导出记录（成片详情页数据源）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return _decode_json_columns(row, ("selfcheck",))


def platform_covers(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """逐平台封面重裁：记录不存在拒收；截帧失败进 skipped（增强项不挡发布）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return generate_platform_covers(context, export_id, row)


def set_publish_data(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """发布数据录入（W8·MVP）：观众投票是唯一的外部真相源，代理指标全是猜测。

    低摩擦口径：platform/plays/retention_pct 三项必填（十秒填完），likes/
    shares/retention_3s/video_id/published_at 可选；键白名单收口，多余键丢弃不存。
    retention_pct 用 0-100 的百分数（创作者后台的展示口径，免换算）。data=None 清除录入。
    """
    export_id = str(params.get("export_id", ""))
    if exports_repo.get(context.conn, export_id) is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    raw = params.get("data")
    if raw is None:
        exports_repo.set_publish_data(context.conn, export_id, None)
        return {"ok": True, "publish_data": None}
    if not isinstance(raw, dict):
        raise RpcDomainError(_ERR_PUBLISH_DATA, "data 必须是对象或 null")
    platform = str(raw.get("platform", "")).strip()
    if platform not in _PUBLISH_PLATFORMS:
        raise RpcDomainError(
            _ERR_PUBLISH_DATA, f"platform 必须是 {'/'.join(_PUBLISH_PLATFORMS)} 之一"
        )
    try:
        plays = int(str(raw.get("plays")))
        retention = float(str(raw.get("retention_pct")))
        shares = None if raw.get("shares") in (None, "") else int(str(raw.get("shares")))
        retention_3s = (
            None if raw.get("retention_3s") in (None, "") else float(str(raw.get("retention_3s")))
        )
    except (TypeError, ValueError) as exc:
        raise RpcDomainError(
            _ERR_PUBLISH_DATA,
            f"plays/retention_pct 必填且为数字（shares/retention_3s 选填数字）: {exc}",
        ) from exc
    if plays < 0 or not 0 <= retention <= 100:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "plays ≥ 0 且 retention_pct ∈ [0, 100]")
    likes_raw = raw.get("likes")
    likes = None if likes_raw in (None, "") else int(str(likes_raw))
    if likes is not None and likes < 0:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "likes ≥ 0")
    if shares is not None and shares < 0:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "shares ≥ 0")
    if retention_3s is not None and not 0 <= retention_3s <= 100:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "retention_3s ∈ [0, 100]")
    video_id = str(raw.get("video_id") or "").strip() or None
    if video_id is not None:
        if len(video_id) > 200:
            raise RpcDomainError(_ERR_PUBLISH_DATA, "video_id 过长（≤200 字符）")
        conflict = exports_repo.find_video_id_conflict(
            context.conn, platform, video_id, exclude_id=export_id
        )
        if conflict is not None:
            raise RpcDomainError(
                _ERR_PUBLISH_DATA, f"作品 ID 已绑定另一条成片 {conflict}：宁拒录，不错配"
            )
    published_at = str(raw.get("published_at") or "").strip() or None
    data = {
        "platform": platform,
        "plays": plays,
        "retention_pct": round(retention, 2),
        "likes": likes,
        "shares": shares,
        "retention_3s": None if retention_3s is None else round(retention_3s, 2),
        "video_id": video_id,
        "published_at": published_at,
        "recorded_at": _now_ms(),
    }
    exports_repo.set_publish_data(context.conn, export_id, data)
    return {"ok": True, "publish_data": data}


def publish_report(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """harness 只读报告：聚合事实摆出来，调权永远人拍板（规格 §5）。"""
    from dramaclip.api import export_report

    dimension = str(params.get("dimension") or "mode")
    if dimension not in export_report.DIMENSIONS:
        raise RpcDomainError(
            _ERR_REPORT_PARAM, f"dimension 必须是 {'/'.join(export_report.DIMENSIONS)} 之一"
        )
    entries = exports_repo.list_publish_entries(context.conn)
    return {**export_report.aggregate(entries, dimension), "health": export_report.health(entries)}


def ab_report(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """A/B 对照组四态（批二#6）：同项目同平台/72h/≥500 播放，保守读数。"""
    from dramaclip.api import export_report

    entries = exports_repo.list_publish_entries(context.conn)
    project_id = str(params.get("project_id") or "").strip()
    if project_id:
        entries = [r for r in entries if r["project_id"] == project_id]
    return export_report.ab_pairs(entries, now_ms=_now_ms())


def _decode_json_columns(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """TEXT→JSON 列还原成协议形状（selfcheck/episode_ids）；坏 JSON 按缺失处理成
    None（灰），不让一条脏数据把整页列表打成 500。"""
    out = dict(row)
    for column in columns:
        raw = out.get(column)
        if isinstance(raw, str):
            try:
                out[column] = json.loads(raw)
            except json.JSONDecodeError:
                out[column] = None
    return out


def list_works(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """作品库：跨项目已完成成片（附项目名/角度/取材集/自检），limit 可调。

    state 过滤 = 09-10 #30「筛选·自检通过」：passed/failed/partial/unchecked，
    词表外的值当作不筛（缺席容忍，不报错）。
    """
    limit = int(params.get("limit", 60))
    raw_state = params.get("state")
    state = str(raw_state) if raw_state in exports_repo.WORKS_STATE_FILTERS else None
    rows = exports_repo.list_completed_works(context.conn, limit=limit, state=state)
    return [_decode_json_columns(row, ("selfcheck", "episode_ids")) for row in rows]


def _load_plan_data(context: AppContext, plan_id: Any) -> PlanData | None:
    """按 id 回读方案并校验；方案被删/数据损坏都返回 None（追溯断链不猜）。"""
    if not plan_id:
        return None
    row = plans_repo.get(context.conn, str(plan_id))
    if row is None:
        return None
    try:
        return PlanData.model_validate(row["plan_data"])
    except Exception as exc:  # noqa: BLE001 - 坏数据不该把整页列表打成 500，但断链必须记账
        _note_degraded(context, "编排方案回读", "自检基准（预算/段数/字幕带）按未知处理", exc)
        return None


def _selfcheck_one(context: AppContext, export_id: str) -> bool:
    """单条成片自检并落库；行不在/未完成/产物不在盘上返回 False（保持 NULL，诚实）。

    probe 抛错（文件损坏/无视频轨）也走 False：量不到就不发成绩单，徽章灰「—」。
    """
    row = exports_repo.get(context.conn, export_id)
    if row is None or row["status"] != exports_repo.STATUS_COMPLETED or not row["output_path"]:
        return False
    out_path = Path(str(row["output_path"]))
    if not out_path.is_file():
        return False
    media = probe.probe(out_path)
    plan_data = _load_plan_data(context, row.get("narration_plan_id"))
    film_map = _load_film_map(out_path)
    ending_end_s, ending_lines = _film_ending_of(context, plan_data, film_map)
    avsync_samples = (
        selfcheck.avsync_sample_points(
            plan_data.timeline,
            measured_spans=film_map,
            film_duration_s=media.duration_s,
        )
        if plan_data is not None
        else None
    )
    payload = selfcheck.run(
        out_path,
        measured_s=media.duration_s,
        has_audio=media.has_audio,
        mode=str(row["narration_mode"] or ""),
        budget_s=None if plan_data is None else _declared_duration_s(plan_data),
        planned_segments=None if plan_data is None else _planned_narration_segments(plan_data),
        segment_count=0 if plan_data is None else len(plan_data.timeline),
        caption_band=_plan_cover_promise(context, plan_data),
        work_dir=context.work_dir,
        ending_end_s=ending_end_s,
        ending_lines=ending_lines,
        avsync_samples=avsync_samples,
        episode_paths=_episode_paths_of(context, plan_data),
    )
    exports_repo.set_selfcheck(
        context.conn,
        export_id,
        json.dumps(payload, ensure_ascii=False),
        selfcheck.overall_state(payload),
    )
    return True


def selfcheck_batch(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """历史成片补测四项自检（幂等，job 化）：默认只处理已完成且从未自检的记录。

    与 ensure_covers 的同步形状不同：四项度量要整片解码（合并一遍也是秒到分钟
    级），同步 RPC 会卡住界面，所以走作业池由抽屉呈现进度。显式给 export_ids
    则重测指定条目（已有成绩单也覆盖重跑）。
    """
    raw_ids = params.get("export_ids")
    limit = max(min(int(params.get("limit", 200)), 500), 1)
    if isinstance(raw_ids, list) and raw_ids:
        wanted = list(dict.fromkeys(str(item) for item in raw_ids))
        targets = [
            export_id
            for export_id in wanted
            if _selfcheck_target(context, export_id)
        ]
    else:
        missing_rows = exports_repo.list_missing_selfcheck(context.conn, limit)
        targets = [str(row["id"]) for row in missing_rows]
    if not targets:
        return {"ok": True, "job_id": None, "queued": 0}
    job_id = context.job_store.create("export_selfcheck")
    context.executor.submit(
        context.notifier.tracked(job_id, _run_selfcheck_batch, context, job_id, targets)
    )
    return {"ok": True, "job_id": job_id, "queued": len(targets)}


def _selfcheck_target(context: AppContext, export_id: str) -> bool:
    """指定重测的资格：行在、已完成、有产物路径（盘上文件由 _selfcheck_one 再验）。"""
    row = exports_repo.get(context.conn, export_id)
    return bool(
        row is not None
        and row["status"] == exports_repo.STATUS_COMPLETED
        and row["output_path"]
    )


def _run_selfcheck_batch(context: AppContext, job_id: str, export_ids: list[str]) -> None:
    """作业体：逐条自检，单条失败不断批（那条保持 NULL 灰），进度按条报。"""
    context.job_store.mark_running(job_id)
    total = len(export_ids)
    checked = 0
    try:
        for index, export_id in enumerate(export_ids, start=1):
            context.job_store.set_progress(
                job_id, round((index - 1) / total * 100, 1), f"成片自检 {index}/{total}"
            )
            try:
                if _selfcheck_one(context, export_id):
                    checked += 1
            except Exception as exc:  # noqa: BLE001 - 单条量不了不断整批，但要点名是哪条
                _note_degraded(
                    context, f"成片自检（第 {index}/{total} 条 {export_id}）",
                    "该行成绩单留 NULL（徽章灰）", exc,
                )
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"成片自检完成：{checked}/{total} 条拿到成绩单")
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"成片自检批次失败: {exc}")


def delete_export(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """删除一条成片（09-10 §3.4 危险操作规矩）：文件先移入 <data>/.trash/<日期>/ 再删行。

    可恢复性落在文件层：成片、封面与逐句时间轴旁挂文件都搬（不搬就成孤儿），「关于 →
    本地数据」入口可达 .trash；DB 行硬删（与 project.delete 同先例）。两类失败分开对待：
    文件不在盘上 → 如实报 missing、不挡删行（记录指向的东西本来已经没了）；
    围栏/OSError → 整单拒绝（宁留记录，不产无法追溯的孤儿文件）。
    """
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    root = context.data_dir.resolve()
    trash_dir = root / ".trash" / date.today().isoformat()
    trashed: list[str] = []
    missing: list[str] = []
    targets: list[Path] = []
    for key in ("output_path", "cover_path"):
        raw = row.get(key)
        if raw:
            targets.append(Path(str(raw)))
    sidecar = Path(str(row["output_path"])).with_suffix(".srt") if row.get("output_path") else None
    if sidecar is not None and sidecar.is_file():
        # 逐句时间轴旁挂文件不在 DB 列里（路径由成片名推出），盘上有就得跟着走
        targets.append(sidecar)
    for path in targets:
        if not path.is_file():
            missing.append(str(path))
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise RpcDomainError(_ERR_TRASH_FENCE, f"产物不在数据目录内，拒绝搬移: {path}")
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
            dest = trash_dir / resolved.name
            if dest.exists():
                dest = trash_dir / f"{export_id[:6]}_{resolved.name}"
            shutil.move(str(resolved), str(dest))
        except OSError as exc:
            raise RpcDomainError(_ERR_TRASH_MOVE, f"移入回收失败: {exc}") from exc
        trashed.append(str(dest))
    exports_repo.delete(context.conn, export_id)
    return {"ok": True, "trashed": trashed, "missing": missing}


def _run_export(context: AppContext, job_id: str, run: ExportRun) -> None:
    """执行池入口：把一次 ExportRun 跑成 jobs 表里的一条终态记录。
    """
    context.job_store.mark_running(job_id)
    # 任务级 LLM 等待预算（第一梯队⑤）：30 分钟只计等云端响应的时间（渲染
    # 段在 render_export 内 paused 冻结）——端点慢死时任务在预算内失败并
    # 明说「LLM 等待预算耗尽」，而不是小时级磨完占着执行池。
    budget_saved = llm_budget.open_budget(_LLM_WAIT_BUDGET_S)

    def report(percent: float, message: str) -> None:
        context.job_store.set_progress(job_id, round(percent, 1), message)
        context.notifier.progress(job_id, round(percent, 1), message)
        exports_repo.set_progress(context.conn, run.export_id, round(percent, 1))

    try:
        if run.cancel_event.is_set():
            exports_repo.mark_cancelled(context.conn, run.export_id)
            context.job_store.mark_cancelled(job_id)
            context.notifier.log("info", "导出已取消")
            return
        # 进度波段：需配音时 TTS 占 0~35%、渲染占 35~100；纯剪辑渲染独占 0~100
        tts_needed = _needs_voice(run.plan_data)
        voice_reports: list[dict[str, Any]] = []
        voiced = ExportRun(
            export_id=run.export_id,
            project_id=run.project_id,
            plan_row=run.plan_row,
            plan_data=_ensure_voiced(
                context, run.plan_row, run.plan_data,
                report=report if tts_needed else None,
                voice_reports=voice_reports,
                cancel=run.cancel_event,
            ),
            cancel_event=run.cancel_event,
            voice_reports=voice_reports,
        )
        # 标题先生成再渲染：render_export 尾部的封面字层要用第一条标题，
        # 而 titles 生成不依赖渲染产物（LLM 只吃 plan_data），顺序对调零副作用。
        _ensure_titles(context, run.plan_row)
        # TTS 回环校验（开关 export.tts_verify 默认关）：合成旁白过本地 ASR 比对
        # 文案，错读/漏字留痕点名——渲染前做，账面跟片走；失败不挡导出（函数内兜）。
        _verify_tts_by_asr(context, run.plan_data)
        render_report = (
            (lambda pct, label: report(35 + pct * 0.65, label)) if tts_needed else report
        )
        out_path = render_export(context, voiced, report=render_report, job_id=job_id)
        # 导出成功后收走段文件（长跑稳定性④）：每条导出在 work/export/<id>/
        # 留 seg_*.mp4 + concat.txt，几十条后 GB 级——成功即清（sig 签名保留
        # 供断点续跑判定，只有几百字节）。
        _cleanup_export_segments(context, str(run.export_id))
        context.job_store.mark_completed(job_id)
        context.notifier.log("info", f"导出完成: {out_path.name}")
    except Exception as exc:
        if run.cancel_event.is_set() or bool(getattr(exc, "cancelled", False)):
            exports_repo.mark_cancelled(context.conn, run.export_id)
            context.job_store.mark_cancelled(job_id)
            context.notifier.log("info", "导出已取消")
        else:
            exports_repo.mark_failed(context.conn, run.export_id, str(exc))
            context.job_store.mark_failed(job_id, str(exc))
            context.notifier.log("error", f"导出失败: {exc}")
    finally:
        llm_budget.close_budget(budget_saved)
        # 与 analysis/narration/models 一致：注册的取消事件必须回收，否则字典无界增长
        context.cancel_events.pop(job_id, None)

