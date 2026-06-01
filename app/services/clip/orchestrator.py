"""
剪辑编排服务
从 clip_handler.py (IPC层) 下沉的业务逻辑。
Handler 仅做参数解包和 IPC 通信，实际剪辑流水线在此编排。
"""

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.utils.path_manager import get_path_manager


def select_segments_to_duration(
    segments: List[Dict[str, Any]],
    sort_key: Any,
    target_duration: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """根据分数指标排序并截取片段，使其符合目标时长限制"""
    sorted_segs = sorted(segments, key=sort_key, reverse=True)

    if not target_duration or target_duration <= 0:
        # 不硬性限制时长，取前 ~28 个高质量片段 + 轻量去重
        top = sorted_segs[:28]
        deduped = []
        used_ranges: list = []
        for seg in sorted(top, key=lambda x: (x.get("video_path", ""), x.get("start_time") or x.get("start") or 0)):
            start = seg.get("start_time") or seg.get("start") or 0.0
            end = seg.get("end_time") or seg.get("end") or (start + 3.0)
            overlap = False
            for us, ue in used_ranges:
                inter = max(0, min(end, ue) - max(start, us))
                if inter > 0.6 * (end - start):
                    overlap = True
                    break
            if not overlap:
                deduped.append(seg)
                used_ranges.append((start, end))
        return sorted(deduped, key=lambda x: (x.get("video_path", ""), x.get("start_time") or x.get("start") or 0.0))

    selected = []
    current_duration = 0.0
    for seg in sorted_segs:
        start = seg.get("start_time") or seg.get("start") or 0.0
        end = seg.get("end_time") or seg.get("end") or 0.0
        dur = max(end - start, 1.0)
        selected.append(seg)
        current_duration += dur
        if current_duration >= target_duration:
            break

    return sorted(selected, key=lambda x: (x.get("video_path", ""), x.get("start_time") or x.get("start") or 0.0))


# ---------------------------------------------------------------------------
# 排序 Key 函数（消除 triple/direct 之间的重复定义）
# ---------------------------------------------------------------------------

def _orig_sort_key(x: dict) -> float:
    """原片解说排序：高燃 + 稳定性奖励 - 极端运动惩罚"""
    audio = float(x.get("audio_score", 0) or 0)
    visual = float(x.get("visual_score", 0) or 0)
    rhythm = float(x.get("rhythm_score", 0) or 0)
    score = float(x.get("score", 0) or x.get("total_score", 0) or 0)
    stability = float(x.get("stability_score", 0.6) or 0.6)
    motion = float(x.get("motion_score", 0) or x.get("avg_motion", 0) or 0)
    motion_penalty = max(0, (motion - 0.72) * 0.35)
    stability_bonus = (stability - 0.5) * 0.25
    return (audio * 0.28 + visual * 0.22 + rhythm * 0.18 + score * 0.22) + stability_bonus - motion_penalty


def _hybrid_sort_key(x: dict) -> float:
    """交叉解说排序：优先情绪强 + 有原声台词的片段"""
    emotion = float(x.get("emotion_score", 0) or 0)
    audio = float(x.get("audio_score", 0) or 0)
    dialogue_imp = float(x.get("dialogue_importance", 0) or 0)
    stability = float(x.get("stability_score", 0.6) or 0.6)
    motion = float(x.get("motion_score", 0) or x.get("avg_motion", 0) or 0)
    motion_penalty = max(0, (motion - 0.68) * 0.28)
    stability_bonus = (stability - 0.5) * 0.22
    return emotion * 0.38 + audio * 0.22 + dialogue_imp * 0.32 + stability_bonus - motion_penalty


def _full_sort_key(x: dict) -> float:
    """全片解说排序：优先节奏感和画面表现力"""
    rhythm = float(x.get("rhythm_score", 0) or 0)
    visual = float(x.get("visual_score", 0) or 0)
    emotion = float(x.get("emotion_score", 0) or 0) * 0.25
    stability = float(x.get("stability_score", 0.6) or 0.6)
    motion = float(x.get("motion_score", 0) or x.get("avg_motion", 0) or 0)
    motion_penalty = max(0, (motion - 0.70) * 0.22)
    stability_bonus = (stability - 0.5) * 0.20
    return rhythm * 0.42 + visual * 0.28 + emotion + stability_bonus - motion_penalty


# ---------------------------------------------------------------------------
# 流水线执行
# ---------------------------------------------------------------------------

def run_clip_pipeline(
    task_id: str,
    video_paths: List[str],
    params: Dict[str, Any],
    project_name: str,
    update_task: Callable,
    scheme: Optional[str] = None,
):
    """
    执行剪辑流水线（后台调用入口）

    Args:
        update_task: 进度更新回调，签名 update_task(status=, progress=, phase=, message=, ...)
    """
    try:
        output_path = params.get("output_path")
        target_duration = params.get("target_duration")
        segments = params.get("segments")
        crop_mode = params.get("crop_mode", "smart")

        if scheme == "all_narrations":
            run_triple_mode_task(
                task_id, video_paths, output_path,
                target_duration, project_name, segments, crop_mode,
                update_task=update_task,
            )
        else:
            run_direct_mode_task(
                task_id, video_paths, output_path,
                target_duration, project_name, segments, crop_mode,
                scheme=scheme, update_task=update_task,
            )

    except Exception as e:
        logger.error(f"[ClipOrch] Pipeline execution failed: {e}")
        update_task(status="failed", message=str(e))
        raise


def run_triple_mode_task(
    task_id: str,
    video_paths: List[str],
    output_path: Optional[str],
    target_duration: Optional[int],
    project_name: str,
    segments: Optional[List[Dict[str, Any]]],
    crop_mode: str = "smart",
    *,
    update_task: Callable,
) -> Dict:
    """一键三连：生成三个不同风格的高光剪辑视频"""
    path_mgr = get_path_manager()

    output_original = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_original.mp4"))
    output_hybrid = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_hybrid.mp4"))
    output_full = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_full.mp4"))

    logger.info(f"[ClipOrch] 一键三连输出: {output_original}, {output_hybrid}, {output_full}")

    def progress_cb(version: str, start_pct: int, end_pct: int):
        def cb(stage: str, progress: int, message: str):
            mapped = start_pct + int((progress / 100.0) * (end_pct - start_pct))
            update_task(progress=mapped, phase=stage, message=f"[{version}] {message}")
        return cb

    try:
        pipeline = ModularDirectCutPipeline()

        # 1. 原片解说
        update_task(progress=10, phase="clipping", message="正在生成第一版：原片解说...")
        orig_segs = (
            select_segments_to_duration(segments, _orig_sort_key, target_duration)
            if segments else None
        )
        pipeline.run(
            video_paths=video_paths, output_path=output_original,
            target_duration=target_duration, project_name=project_name,
            progress_callback=progress_cb("原片解说", 10, 40),
            crop_mode=crop_mode, segments=orig_segs, narration_mode="original",
        )

        # 2. 交叉解说
        update_task(progress=40, phase="clipping", message="正在生成第二版：交叉解说...")
        hybrid_segs = (
            select_segments_to_duration(segments, _hybrid_sort_key, target_duration)
            if segments else None
        )
        from app.services.narration.pipeline import NarrationPipeline
        hybrid_pipeline = NarrationPipeline()
        hybrid_pipeline.run(
            video_paths=video_paths, output_path=output_hybrid,
            target_duration=target_duration, project_name=project_name,
            progress_callback=lambda s, p, m: progress_cb("交叉解说", 40, 70)(s, p, m),
            crop_mode=crop_mode, segments=hybrid_segs,
            mix_mode="overlay", task_id=task_id, narration_mode="hybrid",
        )

        # 3. 全片解说
        update_task(progress=70, phase="clipping", message="正在生成第三版：全片解说...")
        full_segs = (
            select_segments_to_duration(segments, _full_sort_key, target_duration)
            if segments else None
        )
        full_pipeline = NarrationPipeline()
        full_pipeline.run(
            video_paths=video_paths, output_path=output_full,
            target_duration=target_duration, project_name=project_name,
            progress_callback=lambda s, p, m: progress_cb("全片解说", 70, 95)(s, p, m),
            crop_mode=crop_mode, segments=full_segs,
            mix_mode="replace", task_id=task_id, narration_mode="full",
        )

        # 保存结果
        from app.services.task_manager import get_task_manager
        task = get_task_manager().get_task(task_id)
        if task:
            task.result = {"all_outputs": [output_original, output_hybrid, output_full]}

        update_task(progress=100, phase="completed", message="一键三连剪辑全部完成！", status="completed", output_path=output_original)
        logger.info(f"[ClipOrch] 一键三连成功: {output_original}, {output_hybrid}, {output_full}")
        return {"output_path": output_original, "mode": "all_narrations"}

    except Exception as e:
        logger.error(f"[ClipOrch] 一键三连失败: {e}")
        update_task(status="failed", message=str(e))
        raise


def run_direct_mode_task(
    task_id: str,
    video_paths: List[str],
    output_path: Optional[str],
    target_duration: Optional[int],
    project_name: str,
    segments: Optional[List[Dict[str, Any]]],
    crop_mode: str = "smart",
    scheme: Optional[str] = None,
    *,
    update_task: Callable,
) -> Dict:
    """执行单个精彩高光模式剪辑任务"""
    path_mgr = get_path_manager()
    if output_path is None:
        output_path = str(
            path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_direct.mp4")
        )

    logger.info(f"[ClipOrch] Direct mode output: {output_path} scheme={scheme}")

    def progress_cb(stage: str, progress: int, message: str):
        update_task(progress=progress, phase=stage, message=message)

    try:
        final_path = output_path

        if scheme == "hybrid_narration":
            if segments:
                segments = select_segments_to_duration(segments, _hybrid_sort_key, target_duration)
            from app.services.narration.pipeline import NarrationPipeline
            pipeline = NarrationPipeline()
            final_path = pipeline.run(
                video_paths=video_paths, output_path=output_path,
                target_duration=target_duration, project_name=project_name,
                progress_callback=progress_cb, crop_mode=crop_mode,
                segments=segments, mix_mode="overlay",
                task_id=task_id, narration_mode="hybrid",
            )

        elif scheme == "full_narration":
            if segments:
                segments = select_segments_to_duration(segments, _full_sort_key, target_duration)
            from app.services.narration.pipeline import NarrationPipeline
            pipeline = NarrationPipeline()
            final_path = pipeline.run(
                video_paths=video_paths, output_path=output_path,
                target_duration=target_duration, project_name=project_name,
                progress_callback=progress_cb, crop_mode=crop_mode,
                segments=segments, mix_mode="replace",
                task_id=task_id, narration_mode="full",
            )

        else:
            # original_narration 或其他
            if segments:
                segments = select_segments_to_duration(segments, _orig_sort_key, target_duration)
            pipeline = ModularDirectCutPipeline()
            final_path = pipeline.run(
                video_paths=video_paths, output_path=output_path,
                target_duration=target_duration, project_name=project_name,
                progress_callback=progress_cb, crop_mode=crop_mode,
                segments=segments,
            )

        update_task(progress=100, phase="completed", message="智能高光剪辑完成", status="completed", output_path=final_path)
        logger.info(f"[ClipOrch] Direct mode completed: {final_path}")
        return {"output_path": final_path, "mode": scheme or "original"}

    except Exception as e:
        logger.error(f"[ClipOrch] Direct mode failed: {e}")
        update_task(status="failed", message=str(e))
        raise
