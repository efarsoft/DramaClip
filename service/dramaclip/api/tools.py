"""tools 命名空间：不依赖剧空间的独立小工具（文案提取 / 文字转语音 / 语音转文字 / 文案改写）。

定位（业主 2026-10-08 提案、P1/P2 范围 2026-10-13 确认）：引流/日活利器——
无项目上下文可用，单文件进出；产物落 <data>/tools/<job_id>/。
文案提取 = OCR×ASR 融合转写的单文件精简版（硬字幕金标准逻辑直接复用）；
语音转文字 = 同一链路的纯音频变体（无 OCR）；
文字转语音 = TTS 引擎直用（长文，引擎内部切块；音色取当前引擎默认配置）；
文案改写 = LLM 直用（原文复述 / 按文风卡重写两种风格，STYLE_CARD 单一真相源）。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.analysis import fusion, subtitle_ocr
from dramaclip.engines.analysis.models import OcrSegment
from dramaclip.engines.analysis.pipeline import extract_audio
from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.tts import factory
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_BAD_PARAM = -32002
_TOOL_ROOT = "tools"
_EXTRACT_JOB_TYPE = "tools_extract"
_ASR_JOB_TYPE = "tools_asr"

# 纯音频后缀（命中走纯 ASR、跳过 OCR）；其余按视频处理（OCR + ASR 融合）
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

# 改写产物审查：与 audit 的元叙述/CTA 检查同口径的通用违例（自由文本适用的最小集）
_META_RE = re.compile(r"第[一二三四五六七八九十\d]+集|画面里|镜头|素材")
_CTA_BANNED_RE = re.compile(r"关注|点赞|收藏|二维码")


def register(router: Router, context: AppContext) -> None:
    router.register("tools.extract_start", lambda params: extract_start(context, params))
    router.register("tools.get_result", lambda params: get_result(context, params))
    router.register("tools.asr_start", lambda params: asr_start(context, params))
    router.register("tools.rewrite", lambda params: rewrite(context, params))
    router.register("tools.tts", lambda params: tts(context, params))


def _tool_dir(context: AppContext, job_id: str) -> Path:
    return context.data_dir / _TOOL_ROOT / job_id


def _assert_media(params: dict[str, Any]) -> Path:
    media_path = Path(str(params.get("media_path", "") or params.get("video_path", "")).strip())
    if str(media_path) == "" or not media_path.is_file():
        raise RpcDomainError(_ERR_BAD_PARAM, f"媒体文件不存在: {media_path}")
    return media_path


def _is_audio(media_path: Path) -> bool:
    return media_path.suffix.lower() in _AUDIO_EXTS


def extract_start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """对任意视频文件跑「ASR + 硬字幕 OCR → 融合」提取文案（异步作业）。"""
    media_path = _assert_media(params)
    job_id = context.job_store.create(_EXTRACT_JOB_TYPE, ref_id=str(media_path))
    context.cancel_events[job_id] = threading.Event()
    context.executor.submit(
        context.notifier.tracked(job_id, _run_extract, context, job_id, media_path)
    )
    return {"job_id": job_id}


def asr_start(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """语音文件转文字：纯 ASR（无 OCR），异步作业，产物同 data/tools/<job_id>/。"""
    media_path = _assert_media(params)
    if not _is_audio(media_path):
        raise RpcDomainError(
            _ERR_BAD_PARAM,
            f"不是音频文件（支持 mp3/wav/m4a/aac/flac/ogg）: {media_path}",
        )
    job_id = context.job_store.create(_ASR_JOB_TYPE, ref_id=str(media_path))
    context.cancel_events[job_id] = threading.Event()
    context.executor.submit(
        context.notifier.tracked(job_id, _run_extract, context, job_id, media_path)
    )
    return {"job_id": job_id}


def _run_extract(context: AppContext, job_id: str, media_path: Path) -> None:
    """文案提取/语音转文字共用执行体：视频走 OCR 融合，纯音频走纯 ASR。"""
    context.job_store.mark_running(job_id)
    out_dir = _tool_dir(context, job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    want_ocr = not _is_audio(media_path)
    try:
        context.notifier.progress(job_id, 5, "提取音频")
        wav_path = out_dir / f"{media_path.stem}.wav"
        extract_audio(media_path, wav_path)

        context.notifier.progress(job_id, 20, "ASR 转写")
        transcriber = context.analysis_runtime.transcriber()
        language = str(context.settings.get("asr.language") or "zh")
        asr_segments = transcriber.transcribe(wav_path, language=language)
        duration = _media_duration_s(media_path)

        ocr_segments: list[OcrSegment] = []
        if want_ocr:
            context.notifier.progress(job_id, 50, "识别硬字幕")
            ocr_segments, _band, _lines = subtitle_ocr.extract_subtitles(
                media_path, out_dir / "ocr", duration_s=duration
            )

        context.notifier.progress(job_id, 75, "文本融合（ASR × 硬字幕）")
        lines = fusion.fuse(asr_segments, ocr_segments)

        text = "\n".join(segment.text.strip() for segment in lines if segment.text.strip())
        srt = _format_srt(lines)
        (out_dir / "copy.txt").write_text(text + "\n", encoding="utf-8")
        (out_dir / "copy.srt").write_text(srt, encoding="utf-8")
        meta = {
            "video_path": str(media_path),
            "txt_path": str(out_dir / "copy.txt"),
            "srt_path": str(out_dir / "copy.srt"),
            "text": text,
            "chars": len(text.replace("\n", "")),
            "duration_s": round(duration, 2),
            "lines": len(lines),
        }
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        context.notifier.progress(job_id, 100, "提取完成")
        context.job_store.mark_completed(job_id)
    except Exception as exc:
        context.job_store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
        context.notifier.log("error", f"文案提取失败: {exc}")


def get_result(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_BAD_PARAM, f"未知任务: {job_id}")
    result: dict[str, Any] | None = None
    if job["status"] == "completed":
        meta_path = _tool_dir(context, job_id) / "meta.json"
        if meta_path.is_file():
            result = json.loads(meta_path.read_text(encoding="utf-8"))
    return {"status": job["status"], "error": job.get("error"), "result": result}


_REWRITE_STYLES = ("paraphrase", "card")

_REWRITE_TIMEOUT_S = 180.0  # 整段文案改写：比标题/金句宽一档，比成稿紧一档
_REWRITE_PROMPTS = {
    # 原文复述：换说法不换事实——洗稿场景，忠实优先
    "paraphrase": (
        "把下面这段影视解说文案改写成你自己的说法：事实、顺序、结论一条不改，"
        "换措辞、换句式、换比喻；口语短句，禁书面腔；不得新增文案里没有的信息。\n"
    ),
    # 按文风卡重写：吸收手法重写——按项目沉淀的文风标杆与手法标签来
    "card": (
        "把下面这段影视解说文案按【文风标杆】重写：事实与顺序保持不变，"
        "语感、句式、手法全部对齐标杆（第一句砸具体动作、短句动作链、"
        "却/可/竟/直到转折、具体数字、关键台词直给）；不得新增文案里没有的信息。\n"
        + scriptwriter.STYLE_CARD
    ),
}


def rewrite(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """文案改写：原文复述 / 按文风卡重写两种风格，产出附通用审查标注。"""
    from dramaclip.engines.semantic.llm_client import client_for

    text = str(params.get("text", "")).strip()
    if text == "":
        raise RpcDomainError(_ERR_BAD_PARAM, "要改写的文案不能为空")
    style = str(params.get("style") or "paraphrase")
    if style not in _REWRITE_PROMPTS:
        raise RpcDomainError(_ERR_BAD_PARAM, f"未知改写风格: {style}")
    llm = client_for(context.settings, min_timeout_s=_REWRITE_TIMEOUT_S, site="文案改写")
    system = "你是影视解说文案改写助手。只改写，不创作新剧情；只输出 JSON。"
    user = (
        _REWRITE_PROMPTS[style]
        + f"\n原文：\n{text}\n\n"
        + '只输出 JSON：{"text": "改写后的全文"}'
    )
    raw = llm.chat_json(system, user, temperature=0.75)
    rewritten = str(raw.get("text", "")).strip() if isinstance(raw, dict) else ""
    if rewritten == "":
        raise RpcDomainError(_ERR_BAD_PARAM, "模型未产出改写文本")
    return {"text": rewritten, "style": style, "notes": _generic_notes(rewritten)}


def _generic_notes(text: str) -> list[str]:
    """改写产物的通用审查标注（软提示）：元叙述与违禁引导词，只标注不改写。"""
    notes: list[str] = []
    if _META_RE.search(text):
        notes.append("含「第X集/画面里/镜头/素材」式元叙述，建议改成剧情内说法")
    if _CTA_BANNED_RE.search(text):
        notes.append("含「关注/点赞/收藏/二维码」，导看片转化走挂链接，建议删除")
    return notes


def tts(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """长文文字转语音：当前引擎 + 默认音色，产物落 data/tools/tts/（内容寻址缓存）。"""
    text = str(params.get("text", "")).strip()
    if text == "":
        raise RpcDomainError(_ERR_BAD_PARAM, "文案不能为空")
    engine = str(params.get("engine") or context.settings.get("tts.engine") or "").strip()
    if engine not in factory.supported():
        raise RpcDomainError(_ERR_BAD_PARAM, f"配音引擎「{engine or '未指定'}」未接入合成工厂")
    models_dir = context.data_dir / "models"
    voice = _resolve_voice(context, engine, params, models_dir)
    out_root = context.data_dir / _TOOL_ROOT / "tts"
    out_root.mkdir(parents=True, exist_ok=True)
    api_key = str(context.settings.get("tts.api_key", ""))
    model = str(context.settings.get("tts.model", ""))
    device = str(context.settings.get("tts.device") or "auto")
    key = _content_key(engine, voice, text, device, model)
    path, _report = _synthesize(
        engine,
        voice,
        text,
        models_dir,
        out_root,
        key,
        api_key=api_key,
        model=model,
        device=device,
        data_dir=context.data_dir,
    )
    return {"path": str(path), "engine": engine, "voice": voice, "chars": len(text)}


# —— 音色解析与合成的实现与 api.tts 试听同源（长文工具不复用其 60 字试听上限）——


def _resolve_voice(
    context: AppContext, engine: str, params: dict[str, Any], models_dir: Path
) -> str:
    from dramaclip.api import tts as tts_api

    return tts_api._resolve_voice(context, engine, params, models_dir)


def _synthesize(
    engine: str,
    voice: str,
    text: str,
    models_dir: Path,
    out_dir: Path,
    key: str,
    *,
    api_key: str,
    model: str = "",
    device: str = "auto",
    data_dir: Path | None = None,
) -> tuple[Path, Any]:
    from dramaclip.api import tts as tts_api

    return tts_api._synthesize(
        engine,
        voice,
        text,
        models_dir,
        out_dir,
        key,
        api_key=api_key,
        model=model,
        device=device,
        data_dir=data_dir,
    )


def _content_key(engine: str, voice: str, text: str, device: str, model: str) -> str:
    digest = hashlib.sha1(
        f"{engine}|{voice}|{text}|{device}|{model}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return f"tools-tts-{engine}-{digest}"


def _media_duration_s(path: Path) -> float:
    from dramaclip.engines.tts import base as tts_base

    return tts_base.audio_duration_s(path)


def _format_srt(lines: list[Any]) -> str:
    def _stamp(seconds: float) -> str:
        ms = round(seconds * 1000)
        hour, rem = divmod(ms, 3_600_000)
        minute, rem = divmod(rem, 60_000)
        sec, milli = divmod(rem, 1000)
        return f"{hour:02d}:{minute:02d}:{sec:02d},{milli:03d}"

    blocks = []
    for index, segment in enumerate(lines, 1):
        text = segment.text.strip()
        if not text:
            continue
        blocks.append(f"{index}\n{_stamp(segment.start)} --> {_stamp(segment.end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
