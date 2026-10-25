"""analysis 执行族：全剧任务体 + 单集分析 + OCR/热词挖掘 + B8 源签名判据。

自 api/analysis.py 拆出（拆分专项 B）：RPC/队列/结果装配留在 analysis.py，本模块
承载任务池里真正跑的部分——start() 建单后的一切。签名/失效判据（B8）随执行族走：
两侧调用方（analysis 的 _run_prescreen 与本模块 _analyze_one）读同一份实现，
测试打桩统一打 analysis_job 侧。
"""

from __future__ import annotations

import importlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext, llm_trace_dir
from dramaclip.engines.analysis import (
    contact_sheet,
    fusion,
    llm_refine,
    pipeline,
    runtime,
    subtitle_ocr,
)
from dramaclip.engines.analysis import hotwords as hotwords_engine
from dramaclip.engines.analysis.models import (
    AsrSegment,
    AudioFeatures,
    EpisodeRawAnalysis,
    OcrSegment,
    SceneInfo,
)
from dramaclip.engines.semantic import pipeline as semantic_pipeline
from dramaclip.engines.vision import runtime as vision_engine
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo

# ── B8 源失效判据：签名 = md5(path|size|mtime_ns|ocr_channel)，见 pipeline.source_signature ──


def _jsonable(value: Any) -> Any:
    """json.dumps(default=…) 的 numpy 兜底：标量 .item() 转 python 原生类型。

    分析链路里混进 numpy 值的口子不止一个（rapidocr 框坐标、funasr 时间戳、
    librosa 特征……且随引擎版本漂移）——任何一层漏转，落库 json.dumps 就是
    「Object of type float32 is not JSON serializable」（真机 2026-10-20 十集连挂）。
    鸭子类型取 .item()，不 import numpy（非 ml 环境也能导入本模块）。
    """
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes)):
        try:
            return item()
        except Exception:  # noqa: BLE001 - .item() 语义不合就按不可序列化报
            pass
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _dumps(payload: Any) -> str:
    return json.dumps(payload, default=_jsonable)


def _ocr_channel_available(context: AppContext) -> bool:
    """OCR 字幕通道是否可用：设置开关开启 + rapidocr（ml extras）已安装。

    可用性参与源签名：通道缺失时产物是纯 ASR 降级版，依赖装好后签名失配即强制重算，
    降级结果不会在「条件已修复」后永久滞留。
    """
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return False
    try:
        importlib.import_module("rapidocr")
    except ImportError:
        return False
    return True


def _current_signature(context: AppContext, episode: dict[str, Any]) -> str | None:
    return pipeline.source_signature(
        Path(str(episode["source_path"])),
        ocr_channel=_ocr_channel_available(context),
    )


def _source_stale(context: AppContext, episode: dict[str, Any]) -> bool:
    """库里签名 ≠ 当前源签名（含旧库 NULL 首次）→ 既有分析/预筛产物不可信，需重算。

    源文件不可读时返回 False：缺文件的失败交给分析引擎自己报错留痕，不做签名失效。
    """
    current = _current_signature(context, episode)
    if current is None:
        return False
    return episode.get("source_signature") != current


def _project_name_of(context: AppContext, episode: dict[str, Any]) -> str:
    """项目名（精炼提示词的语境）；取不到用占位。"""
    from dramaclip.infra.storage.repos import projects as projects_repo

    project = projects_repo.get(context.conn, str(episode["project_id"]))
    return str(project["name"]) if project else "这部剧"


def _contact_sheet(context: AppContext, episode: dict[str, Any]) -> str | None:
    """生成逐集 contact sheet（视觉轨输入与预览资产），返回落库路径；失败仅留痕。

    分档语义：拼图是增强品不是必需品——ffmpeg 失败/时长缺失只记 warn 落 NULL，
    分析照常完成，消费端对 NULL 回退纯台词行为（同 subtitle_band 的 NULL 口径）。
    """
    try:
        out = context.data_dir / "contact_sheets" / f"{episode['id']}.png"
        contact_sheet.build_contact_sheet(
            Path(str(episode["source_path"])),
            out,
            duration_s=float(episode["duration"] or 0.0),
        )
        return str(out)
    except Exception as exc:
        context.notifier.log(
            "warn",
            f"第{episode['episode_number']}集 拼图生成失败（不影响分析）: {exc}",
        )
        return None


def _describe_frames(
    context: AppContext,
    vision: vision_engine.VisionSession | vision_engine.CloudVisionSession | None,
    episode: dict[str, Any],
    episode_id: str,
    report: Callable[[float, str], None],
) -> list[dict[str, Any]]:
    """视觉轨逐图描述（P2b）：采样 16 帧 → 4 张一组多图请求 → 编号回填解析。

    会话由任务级持有（模型跨集复用）；任何失败按分档落 []——分析照常完成，
    消费端对空 frames 回退纯台词行为，重跑单集可补。
    """
    if vision is None:
        return []
    try:
        return vision.describe_episode(
            Path(str(episode["source_path"])),
            float(episode["duration"] or 0.0),
            context.work_dir / episode_id / "vl",
            on_progress=lambda frac, text: report(round(frac, 3), text),
        )
    except Exception as exc:
        context.notifier.log(
            "warn",
            f"第{episode['episode_number']}集 画面理解失败（不影响分析）: {exc}",
        )
        return []


def _resumable_raw(
    context: AppContext, episode: dict[str, Any], signature: str | None
) -> EpisodeRawAnalysis | None:
    """上轮死在语义层的残留可续跑时，从库里重建第一层产物；不可续返回 None。

    判据三条同时成立：源签名相同（转写产物属于这份源）、语义列为空（语义层没
    完成）、第一层产物能完整解析（半截/损坏的记录按不可续走全量重算）。
    """
    if signature is None or episode.get("source_signature") != signature:
        return None
    record = analysis_repo.get(context.conn, str(episode["id"]))
    if record is None or not record["asr_segments"] or record["conflict_scores"]:
        return None
    try:
        return EpisodeRawAnalysis(
            asr_segments=[
                AsrSegment.model_validate(item) for item in json.loads(record["asr_segments"])
            ],
            scenes=[
                SceneInfo.model_validate(item) for item in json.loads(record["scene_data"] or "[]")
            ],
            audio=AudioFeatures.model_validate(json.loads(record["audio_features"] or "{}")),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _extract_bars(
    context: AppContext, episode: dict[str, Any]
) -> tuple[
    list[OcrSegment] | None,
    tuple[float, float] | None,
    list[tuple[float, float]] | None,
]:
    """单集 OCR 抽取，返回 (字幕条, 源带, 行框)；失败返回 None 并留痕（不阻塞分析主链路）。

    字幕带与逐行框随字幕条一起回传（覆盖数据链）：调用方落库
    episode_analysis.subtitle_band，编码端 delogo 逐行擦除、烧录字幕带内压位。
    """
    duration = float(episode["duration"] or 0)
    if duration <= 0:
        return None, None, None
    try:
        return subtitle_ocr.extract_subtitles(
            Path(str(episode["source_path"])),
            context.work_dir / f"ocr_{episode['id']}",
            duration_s=duration,
        )
    except ImportError:
        return None, None, None  # rapidocr 未安装：ml extras 约定的纯 ASR 路径
    except Exception as exc:  # noqa: BLE001 - OCR 失败不影响分析主链路
        context.notifier.log("warn", f"OCR 字幕通道失败（不影响分析）: {exc}")
        return None, None, None


def _cached_mining(
    context: AppContext, episode: dict[str, Any], *, ocr_enabled: bool
) -> tuple[list[OcrSegment], tuple[float, float], list[tuple[float, float]] | None] | None:
    """跨轮复用：源视频在分析后未变 + 已有字幕条产物 → 直接复用，不重挖。

    判据：视频 mtime ≤ analyzed_at（分析晚于素材改动）。ocr_channel 不参与——
    缓存的是 OCR 输出本身，通道开关只影响新鲜度与下次签名，不影响已有产物。
    引擎代际也参与：存量条目缺 engine 标记或代际不符（引擎升级过）一律不复用，
    否则换代后新引擎永远跑不起来、读数质量提升被缓存吞掉（真机 EP1 实证）。
    """
    if not ocr_enabled:
        return None
    row = analysis_repo.get(context.conn, str(episode["id"]))
    if row is None or not row["ocr_segments"] or not row["subtitle_band"]:
        return None
    try:
        stat = Path(str(episode["source_path"])).stat()
    except OSError:
        return None
    if stat.st_mtime_ns > int(row["analyzed_at"]) * 1_000_000:
        return None
    try:
        bars = [OcrSegment.model_validate(b) for b in json.loads(row["ocr_segments"])]
        if not bars or any(bar.engine != subtitle_ocr.ENGINE_TAG for bar in bars):
            return None
        parsed = json.loads(row["subtitle_band"])
        # 两种落库格式都认：新 = {"band": [...], "lines": [[t,b],...]}；旧 = [t, b]
        if isinstance(parsed, dict):
            band = (float(parsed["band"][0]), float(parsed["band"][1]))
            lines = [(float(t), float(b)) for t, b in parsed.get("lines") or []]
        else:
            band = (float(parsed[0]), float(parsed[1]))
            lines = None
        return bars, band, lines or None
    except (ValueError, TypeError, KeyError):
        return None


def _fuse_ocr(
    context: AppContext,
    episode: dict[str, Any],
    asr: list[AsrSegment],
    ocr_bars: list[OcrSegment] | None = None,
    ocr_band: tuple[float, float] | None = None,
    ocr_lines: list[tuple[float, float]] | None = None,
) -> tuple[
    list[AsrSegment],
    list[OcrSegment] | None,
    tuple[float, float] | None,
    list[tuple[float, float]] | None,
]:
    """硬字幕 OCR 通道 + 融合（analysis.ocr_enabled 默认开）。

    第三元是探测到的源字幕带、第四元是逐行框（覆盖数据链）：即便没融合出字幕条
    也要回传落库——带的位置是源片属性，与本轮台词抽取成败无关。
    """
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return asr, None, ocr_band, ocr_lines
    if ocr_bars is None:
        extracted = _extract_bars(context, episode)
        if extracted is None:
            return asr, None, ocr_band, ocr_lines
        ocr_bars, ocr_band, ocr_lines = extracted
    if not ocr_bars:
        return asr, None, ocr_band, ocr_lines
    return fusion.fuse(asr, ocr_bars), ocr_bars, ocr_band, ocr_lines


def _mine_hotwords(
    context: AppContext,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
    on_episode: Callable[[int, int], None] | None = None,
    *,
    ocr_enabled: bool = True,
) -> tuple[
    dict[str, list[OcrSegment]],
    dict[str, tuple[float, float]],
    dict[str, list[tuple[float, float]]],
    str,
]:
    """阶段 A：全剧 OCR 抽取（落库）→ 挖掘全剧热词表；字幕带与逐行框按集回传。"""
    bars_by_episode: dict[str, list[OcrSegment]] = {}
    bands_by_episode: dict[str, tuple[float, float]] = {}
    lines_by_episode: dict[str, list[tuple[float, float]]] = {}
    if context.settings.get("analysis.ocr_enabled", "1") != "1":
        return (
            bars_by_episode,
            bands_by_episode,
            lines_by_episode,
            hotwords_engine.merge_extra("", str(context.settings.get("asr.hotwords_extra") or "")),
        )
    for index, episode in enumerate(targets):
        if cancel_event.is_set():
            break
        episode_id = str(episode["id"])
        cached = _cached_mining(context, episode, ocr_enabled=ocr_enabled)
        bars, band, lines = cached if cached is not None else _extract_bars(context, episode)
        if on_episode is not None:
            on_episode(index + 1, len(targets))
        if band is not None:
            # 带是源片属性：即使本集没抽出字幕条（bars 为空）也记下来，逐集分析时落库
            bands_by_episode[episode_id] = band
            if lines:
                lines_by_episode[episode_id] = lines
        if not bars:
            continue
        bars_by_episode[episode_id] = bars
        analysis_repo.update_ocr_segments(
            context.conn, episode_id, _dumps([b.model_dump() for b in bars])
        )
    # 人工热词在最前：挖掘表是 OCR 派生的，会漏生僻人名也会把 OCR 错字当热词——
    # 业主点名（asr.hotwords_extra）是最强信号。
    hotwords = hotwords_engine.merge_extra(
        hotwords_engine.mine([b for bars in bars_by_episode.values() for b in bars]),
        str(context.settings.get("asr.hotwords_extra") or ""),
    )
    if hotwords:
        context.notifier.log("info", f"全剧热词表：{hotwords}")
    return bars_by_episode, bands_by_episode, lines_by_episode, hotwords


def _restore_unprocessed(context: AppContext, targets: list[dict[str, Any]]) -> None:
    """把没真正处理到的目标集从 analyzing 回滚为入队前状态。

    start() 建单时整批标了 analyzing；取消/致命失败后没轮到的集不能滞留在
    analyzing（界面会误示仍在处理）。处理过的集已被置为 done/failed，不受影响；
    进程崩溃没走到这里的残留，由下次启动的 reset_stale_analyzing 清扫。
    """
    for episode in targets:
        episode_id = str(episode["id"])
        row = episodes_repo.get(context.conn, episode_id)
        if row is not None and row["status"] == "analyzing":
            episodes_repo.set_status(context.conn, episode_id, str(episode["status"]))


def _run_job(
    context: AppContext,
    job_id: str,
    project_id: str,
    targets: list[dict[str, Any]],
    cancel_event: threading.Event,
) -> None:
    """执行池任务：全剧 OCR→热词→逐集分析，单集失败不中断其余。"""
    vision = None
    total = len(targets)
    failures = 0
    try:
        # mark_running 之后的每一步都在 try 内：任务体里任何异常都必须落进
        # mark_failed——pre-try 窗口的异常曾让任务永久停在 running（项目卡
        # analyzing、集卡 analyzing，只能重启服务清扫）。
        context.job_store.mark_running(job_id)
        projects_repo.set_status(context.conn, project_id, "analyzing")
        vision = vision_engine.open_session(
            context.data_dir, context.data_dir / "models", context.settings
        )
        if vision is not None:
            context.notifier.log(
                "info", f"视觉轨启用（{vision.model_id}）：逐集画面理解将随分析进行", job_id=job_id
            )
        language = runtime.language(context.settings)
        if context.settings.get("analysis.ocr_enabled", "1") == "1" and not _ocr_channel_available(
            context
        ):
            # 降级打标：OCR 通道缺失 → 本轮产物是纯 ASR 降级版（无硬字幕融合）。
            # ocr_channel 参与源签名，装好 rapidocr 后签名失配自动强制重算。
            context.notifier.log(
                "warn",
                "OCR 字幕通道不可用（rapidocr 未安装），分析产物为纯 ASR 降级版；"
                "依赖就绪后相关集将自动重新分析",
                job_id=job_id,
            )
        # 挖掘阶段逐集播报：任务标签/进度通知可见（此前整批分析前几分钟毫无动静）
        # 挖掘阶段计入总进度前 30%：OCR 逐集要数分钟，恒 0% 会被当成卡死（业主实测反馈）
        def mining_report(done: int, count: int) -> None:
            percent = round(done / count * 30, 1) if count else 0.0
            message = f"全剧字幕热词挖掘 {done}/{count} 集"
            context.job_store.set_progress(job_id, percent, message)
            context.notifier.progress(job_id, percent, message)

        bars_by_episode, bands_by_episode, lines_by_episode, hotwords = _mine_hotwords(
            context, targets, cancel_event, on_episode=mining_report
        )
        for index, episode in enumerate(targets):
            if cancel_event.is_set():
                context.job_store.mark_cancelled(job_id)
                return
            episode_id = str(episode["id"])
            bars = bars_by_episode.get(episode_id)
            if not _analyze_one(
                context,
                job_id,
                episode,
                index,
                total,
                language,
                cancel_event,
                vision=vision,
                ocr_bars=bars,
                ocr_lines=lines_by_episode.get(episode_id),
                ocr_band=bands_by_episode.get(episode_id),
                hotwords=hotwords,
            ):
                failures += 1
        if failures == total:
            # 全军覆没不是「完成」：错误码级配置错（未知引擎/缺 Key/运行环境缺）
            # 会让每集以同样的方式倒下，逐集明细已由 append_detail 聚在 error 列。
            detail = ""
            job = context.job_store.get(job_id)
            if job is not None:
                detail = str(job.get("error") or "")
            context.job_store.mark_failed(
                job_id,
                f"全部 {total} 集分析失败" + (f"：{detail}" if detail else ""),
            )
        else:
            context.job_store.mark_completed(job_id)
    except Exception as exc:  # 引擎级致命错误（如模型加载失败）
        context.job_store.mark_failed(job_id, f"分析任务失败: {exc}")
        context.notifier.log("error", f"分析任务失败: {exc}")
    finally:
        if vision is not None:
            vision.close()
        _restore_unprocessed(context, targets)
        context.cancel_events.pop(job_id, None)
        projects_repo.set_status(context.conn, project_id, "ready")
        if failures:
            context.notifier.log("warn", f"分析完成，{failures}/{total} 集失败")


def _analyze_one(
    context: AppContext,
    job_id: str,
    episode: dict[str, Any],
    index: int,
    total: int,
    language: str,
    cancel_event: threading.Event,
    *,
    vision: vision_engine.VisionSession | vision_engine.CloudVisionSession | None = None,
    ocr_bars: list[OcrSegment] | None = None,
    ocr_band: tuple[float, float] | None = None,
    ocr_lines: list[tuple[float, float]] | None = None,
    hotwords: str = "",
) -> bool:
    """分析单集；返回是否成功（失败标记后继续其余集）。

    两段写入：第一层（转写/场景/音频/OCR）跑完立即落库、语义列显式清空，语义层
    完成**才**标 done——链路里最贵的是转写、最易挂的是 LLM，语义抖动不再连坐
    转写白跑。重入判据：签名相同 + 语义列为空 = 上轮死在语义层，跳过转写直补。
    """
    episode_id = str(episode["id"])
    label = f"第{episode['episode_number']}集"

    # 单调钳制：转写管线报完「分析完成 100%」后视觉轨还会续报——不钳会 100%→48% 回跳
    peak = [float("-inf")]

    def report(percent: float, message: str) -> None:
        overall = max(30 + (index + percent) / total * 70, peak[0])
        peak[0] = overall
        context.job_store.set_progress(job_id, round(overall, 1), f"{label} {message}")
        context.notifier.progress(job_id, round(overall, 1), f"{label} {message}")

    # 分析开始前取签名：产物对应的是这份源；分析中途源被换则存的是旧签名，
    # 下轮判定必然失配重算——宁多算一轮，不把新签名盖在旧源产物上。
    signature = _current_signature(context, episode)
    if (
        episode["status"] == "done"
        and signature is not None
        and episode.get("source_signature") != signature
    ):
        # B8 失效重算（源被换或旧库 NULL 签名）：留痕，防「源换了还静默用旧 ASR」
        context.notifier.log("warn", f"{label} 源已变更，重新分析", job_id=job_id)
    episodes_repo.set_status(context.conn, episode_id, "analyzing")
    try:
        stored = _resumable_raw(context, episode, signature)
        if stored is not None:
            context.notifier.log(
                "info", f"{label} 上轮语义层未完成：沿用转写结果，直接补语义", job_id=job_id
            )
            raw = stored
        else:
            transcriber = context.analysis_runtime.transcriber()
            raw = pipeline.analyze_episode(
                video_path=Path(str(episode["source_path"])),
                work_dir=context.work_dir / episode_id,
                transcriber=transcriber,
                language=language,
                cancel=cancel_event,
                report=report,
                hotwords=hotwords,
            )
            # 算力账落任务行：通知流会滚走，任务详情才是可复核的真相源。
            compute_report = getattr(transcriber, "compute", lambda: None)()
            if compute_report is not None:
                context.job_store.set_compute(job_id, [compute_report.to_dict()])
            # 转写质量预警（时间轴坍缩特征等）：如实转达不拦流程——分析层没有更好的
            # 时间轴可换，能做的是把「这份转写不可信」告诉用户，建议切云端重析。
            for warning in raw.warnings:
                context.notifier.log("warn", f"{label} {warning}", job_id=job_id)
            asr_segments, ocr_segments, band, band_lines = _fuse_ocr(
                context, episode, raw.asr_segments, ocr_bars, ocr_band, ocr_lines
            )  # noqa: F841 - band_lines 落库见下方 subtitle_band
            ocr_json = (
                _dumps([o.model_dump() for o in ocr_segments]) if ocr_segments else None
            )
            sheet = _contact_sheet(context, episode)
            frames = _describe_frames(context, vision, episode, episode_id, report)
            track: dict[str, Any] = {}
            if sheet is not None:
                track["contact_sheet"] = sheet
            if frames:
                track["frames"] = frames
                track["engine"] = vision.model_id if vision is not None else ""
            analysis_repo.upsert(
                context.conn,
                episode_id,
                asr_segments=_dumps([seg.model_dump() for seg in asr_segments]),
                scene_data=_dumps([scene.model_dump() for scene in raw.scenes]),
                audio_features=raw.audio.model_dump_json(),
                ocr_segments=ocr_json,
                visual_track=_dumps(track) if track else None,
                # 覆盖数据链落库：{"band": [t,b], "lines": [[t,b],...]}（旧库为纯 list，
                # 读取端两种都认）。NULL=无硬字幕带/未探测/OCR 未装，消费端回退现状
                subtitle_band=(
                    _dumps(
                        {"band": [band[0], band[1]], "lines": band_lines or []}
                        if band is not None
                        else None
                    )
                    if band is not None
                    else None
                ),
                # 语义列显式清空（upsert 传 None 即置 NULL）：此后任何时刻挂掉，
                # 重入判据都能识别「这份源的第一层已就绪，只欠语义」。
            )
            if signature is not None:
                episodes_repo.set_source_signature(context.conn, episode_id, signature)
            # 转写精炼（LLM 断句+语境校对）：本地 ASR 完成后、语义前——下游全线吃到干净文本。
            # 分档：LLM 未配置/护栏拒绝/调用失败都回退融合产物，不挡分析。
            refine_outcome = llm_refine.refine_segments(
                asr_segments,
                ocr_segments=ocr_segments,
                project_name=_project_name_of(context, episode),
                hotwords=hotwords,
                settings=context.settings,
            )
            if refine_outcome.applied:
                asr_segments = refine_outcome.segments
                # 回写这一列：上面的 upsert 存的是融合分段，只改内存变量的话
                # narration/auto_voice 读到的仍是精炼前文本，本层等于白跑。
                # 崩在两次写之间不丢数据：重入判据看的是语义列，补跑吃库里这份融合段。
                analysis_repo.update_asr_segments(
                    context.conn,
                    episode_id,
                    _dumps([seg.model_dump() for seg in asr_segments]),
                )
                context.notifier.log(
                    "info",
                    f"{label} 转写精炼：{len(asr_segments)} 句（{refine_outcome.detail}）",
                    job_id=job_id,
                )
            elif refine_outcome.detail not in ("LLM 未配置",):
                context.notifier.log(
                    "warn",
                    f"{label} 转写精炼未生效（{refine_outcome.detail}）；产物为融合分段",
                    job_id=job_id,
                )
            # 语义层必须吃库里那一份：`raw` 携带的是融合前的原生分段，而重入路径
            # `_resumable_raw` 从库里重建——两份并存时，同一集会因「上轮有没有死在
            # 语义层」跑出不同的高光/冲突打分。
            raw = raw.model_copy(update={"asr_segments": asr_segments})
        semantic_result = semantic_pipeline.enhance(
            raw,
            context.settings,
            trace_dir=llm_trace_dir(context),
            trace_tag=episode_id,
        )
        analysis_repo.update_semantic(
            context.conn,
            episode_id,
            conflict_scores=_dumps([s.model_dump() for s in semantic_result.conflict_scores]),
            highlights=_dumps([h.model_dump() for h in semantic_result.highlights]),
            genre=semantic_result.genre or None,
        )
        episodes_repo.mark_done(context.conn, episode_id)
        return True
    except Exception as exc:
        if cancel_event.is_set():
            # 用户取消（ffmpeg/管线抛出的取消异常也走这里）：集恢复进任务前的
            # 状态，job 由循环头的 mark_cancelled 收口——把取消记成「分析失败」
            # 是对用户的误报。
            episodes_repo.set_status(context.conn, episode_id, str(episode["status"]))
            context.notifier.log("info", f"{label} 已取消", job_id=job_id)
        else:
            episodes_repo.set_status(context.conn, episode_id, "failed")
            # 失败原因落任务行（append_detail 聚合）：状态轮询与日志流都会滚走，
            # 任务详情是事后唯一的可查账面——否则就是客户看到的「分析失败」三个字。
            context.job_store.append_detail(job_id, f"{label}: {exc}")
            context.notifier.log("error", f"{label} 分析失败: {exc}")
        return False
