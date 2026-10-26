"""bgm.* RPC 域：曲库生成（ACE-Step 本地）/重扫/清单。

生成是引擎中心的显式动作（业主钦定的离线批量入库形态）：一次任务生成
N 情绪 × M 首，产物 wav 由 ffmpeg 转 ogg 落曲库情绪子目录，测时长/bpm 后
upsert 进 bgm_tracks——导出选曲链（selector/_pick_bgm_track）零改动消费。
导出侧「空曲库 = 现状逐字节一致」语义不受本域影响（本域只增不改）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from dramaclip.engines.bgm import library as bgm_library
from dramaclip.engines.music import generator as music_generator
from dramaclip.engines.music.engine import AceStepEngine
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg
from dramaclip.infra.paths import resolve_data_dir
from dramaclip.infra.storage.repos import bgm as bgm_repo

_LICENSE = "MIT·本地生成"
_ATTRIBUTION = "ACE-Step v1.5"
_SOURCE_URL = "https://github.com/ace-step/ACE-Step-1.5"
_EMOTIONS = ("default", "anger", "triumph", "suspense", "sadness")


def _bgm_dir(context: Any) -> Path:
    return resolve_data_dir() / "bgm"


def _engine(context: Any) -> AceStepEngine:
    return AceStepEngine(resolve_data_dir() / "models")


def _next_index(directory: Path, emotion: str) -> int:
    """曲库文件自增序号：只认自家产物前缀 acestep_<emotion>_NN.ogg。

    扫描前缀必须与写入文件名同构——早先扫 `{emotion}_` 会看不见自己的
    acestep_ 前缀产物，per_emotion≥2 时序号永远算 1，同路径静默互相覆盖。
    """
    prefix = f"acestep_{emotion}_"
    highest = 0
    if directory.is_dir():
        for f in directory.iterdir():
            stem = f.stem.lower()
            if stem.startswith(prefix) and stem[len(prefix):].isdigit():
                highest = max(highest, int(stem[len(prefix):]))
    return highest + 1


def _transcode_to_library(
    context: Any, wav_path: Path, emotion: str
) -> tuple[Path, float, float | None]:
    """wav → ogg 落曲库情绪子目录，返回 (落位, 时长, bpm)。源 wav 转完即删。"""
    directory = _bgm_dir(context) / emotion
    directory.mkdir(parents=True, exist_ok=True)
    index = _next_index(directory, emotion)
    dest = directory / f"acestep_{emotion}_{index:02d}.ogg"
    result = subprocess_run_ffmpeg(wav_path, dest)
    if not dest.is_file() or dest.stat().st_size == 0:
        # 半截 ogg 不许留在曲库目录：重扫会跳过但试听会 403/静音，当场清掉
        dest.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg 转码失败：{result}")
    wav_path.unlink(missing_ok=True)
    duration, bpm = bgm_library.measure_track(dest)
    return dest, duration, bpm


def subprocess_run_ffmpeg(wav_path: Path, dest: Path) -> str:
    """wav→ogg 转码（q6 质量档，48kHz 单声道降混交给 amix 阶段——床混音只取一路）。"""
    import subprocess

    result = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        [
            resolve_ffmpeg(), "-y", "-i", str(wav_path),
            "-c:a", "libvorbis", "-q:a", "6", str(dest),
        ],
        capture_output=True, text=True, check=False,
    )
    return result.stderr[-300:] if result.returncode != 0 else ""


def _generate_worker(context: Any, job_id: str, payload: dict[str, Any]) -> None:
    """任务线程体：逐首生成→转码→入库。单首失败留痕继续，全失败才判任务失败。"""
    emotions = [str(e) for e in payload.get("emotions") or []]
    per_emotion = max(1, min(int(payload.get("per_emotion") or 1), 5))
    duration_s = float(payload.get("duration_s") or 120)
    caption = str(payload.get("caption") or "").strip() or None
    engine = _engine(context)
    total = len(emotions) * per_emotion
    done = 0
    failures: list[str] = []
    try:
        for emotion in emotions:
            request = music_generator.build_request(emotion, duration_s, caption)
            for _ in range(per_emotion):
                if context.cancel_events.get(job_id, threading.Event()).is_set():
                    context.job_store.mark_failed(job_id, "已取消")
                    context.cancel_events.pop(job_id, None)
                    return
                try:
                    work = context.work_dir / "bgm-gen"
                    work.mkdir(parents=True, exist_ok=True)
                    wav = engine.synthesize(request, work)
                    dest, duration, bpm = _transcode_to_library(context, wav, emotion)
                    bgm_repo.upsert_track(
                        context.conn,
                        file_path=str(dest),
                        emotion=emotion,
                        duration_s=duration,
                        bpm=bpm,
                        license=_LICENSE,
                        attribution=_ATTRIBUTION,
                        source_url=_SOURCE_URL,
                    )
                    context.notifier.log(
                        "info",
                        f"BGM 生成入库：{dest.name}（{emotion}，{duration:.0f}s，"
                        f"bpm {bpm if bpm is not None else '—'}）",
                    )
                except Exception as exc:  # noqa: BLE001 - 单首失败留痕继续
                    failures.append(f"{emotion}: {type(exc).__name__}: {exc}")
                    context.notifier.log("warn", f"BGM 生成失败（{emotion}）：{exc}")
                done += 1
                context.notifier.log(
                    "info", f"BGM 生成进度 {done}/{total}",
                )
        if done and len(failures) == done:
            detail = ""
            job = context.job_store.get(job_id)
            if job is not None:
                detail = str(job.get("error") or "")
            context.job_store.mark_failed(
                job_id, f"全部 {total} 首生成失败" + (f"：{detail}" if detail else "")
            )
        else:
            if failures:
                context.notifier.log("warn", f"BGM 生成部分失败（{len(failures)}/{done}）")
            context.job_store.mark_completed(job_id)
    except Exception as exc:  # noqa: BLE001 - 任务体任何意外都必须落终态，不留 running
        context.job_store.mark_failed(job_id, f"BGM 生成任务失败: {exc}")
        context.notifier.log("error", f"BGM 生成任务失败: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def register(router: Any, context: Any) -> None:
    def bgm_generate(params: dict[str, Any]) -> dict[str, Any]:
        emotions = [str(e) for e in (params.get("emotions") or []) if str(e) in _EMOTIONS]
        if not emotions:
            raise ValueError(f"emotions 必须是 {_EMOTIONS} 的非空子集")
        duration_s = int(params.get("duration_s") or 120)
        if duration_s not in music_generator.DURATION_CHOICES:
            raise ValueError(f"duration_s 只支持 {music_generator.DURATION_CHOICES}")
        engine = _engine(context)
        available, reason = engine.is_available()
        if not available:
            raise ValueError(reason)
        active = [
            j for j in context.job_store.list_recent(limit=50, active_only=True)
            if j.get("type") == "bgm_generate"
        ]
        if active:
            raise ValueError(
                "已有 BGM 生成任务进行中，请等待完成后再发起（并发写同一目录会互相覆盖）"
            )
        job_id = context.job_store.create("bgm_generate", ref_id=",".join(emotions))
        context.job_store.mark_running(job_id)
        context.cancel_events[job_id] = threading.Event()
        context.notifier.log(
            "info",
            f"BGM 生成任务开始：{len(emotions)} 情绪 × "
            f"{max(1, min(int(params.get('per_emotion') or 1), 5))} 首，{duration_s}s 档",
        )
        threading.Thread(
            target=_generate_worker,
            args=(context, job_id, dict(params, emotions=emotions)),
            name="bgm-generate",
            daemon=True,
        ).start()
        return {"job_id": job_id}

    def bgm_rescan(_params: dict[str, Any]) -> dict[str, Any]:
        """全库重扫入库（生成曲之外的素材交接通道：手工投放/业主整理曲一并收编）。"""
        result = bgm_library.scan_library(_bgm_dir(context))
        for track in result.tracks:
            bgm_repo.upsert_track(
                context.conn,
                file_path=str(track.file),
                emotion=track.emotion,
                duration_s=track.duration_s,
                bpm=track.bpm,
                license=track.license,
                attribution=track.attribution,
                source_url=track.source_url,
            )
        return {
            "tracks": len(result.tracks),
            "skipped": [
                {"file": str(path), "reason": reason} for path, reason in result.skipped
            ],
        }

    def bgm_library_list(_params: dict[str, Any]) -> dict[str, Any]:
        rows = bgm_repo.list_all(context.conn)
        groups = [
            {
                "emotion": emotion,
                "count": sum(1 for r in rows if r["emotion"] == emotion),
                "total_s": round(
                    sum(float(r["duration_s"] or 0) for r in rows if r["emotion"] == emotion), 1
                ),
            }
            for emotion in _EMOTIONS
        ]
        return {"groups": groups, "tracks": rows}

    def bgm_runtime_status(_params: dict[str, Any]) -> dict[str, Any]:
        from dramaclip.infra.model_manager import music_runtime

        return music_runtime.status(resolve_data_dir())

    router.register("bgm.generate", bgm_generate)
    router.register("bgm.rescan", bgm_rescan)
    router.register("bgm.library", bgm_library_list)
    router.register("bgm.runtime_status", bgm_runtime_status)
