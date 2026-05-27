"""
分析任务 Handler
处理视频分析任务的管理
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.project.manager_sqlite import get_manager
from app.services.analyze.manager import get_analysis_manager
from .base import send_progress
from app.ipc.protocol import RPCError


def analyze_start(project_id: str, episode_ids: List[str]) -> Dict:
    """开始分析任务

    Args:
        project_id: 项目ID
        episode_ids: 要分析的剧集ID列表（空列表表示分析所有视频）

    Returns:
        创建的任务ID列表
    """
    logger.info(f"[Analyze] Starting analysis: project={project_id}, episodes={episode_ids}")
    if episode_ids is None:
        raise RPCError(-32602, "episode_ids is required")

    mgr = get_manager()
    analysis_mgr = get_analysis_manager()

    videos = mgr.get_videos(project_id)
    if not videos:
        raise RPCError(-32002, f"No videos found in project {project_id}")

    if episode_ids == []:
        episode_ids = [v.id for v in videos]

    video_map = {v.id: v for v in videos}
    task_ids = []

    def make_callback(tid):
        return lambda progress_data: send_progress(
            task_id=tid,
            progress=progress_data["progress"],
            message=progress_data.get("message", ""),
            phase=progress_data.get("phase", ""),
        )

    for episode_id in episode_ids:
        video = video_map.get(episode_id)
        if not video:
            logger.warning(f"[Analyze] Video {episode_id} not found in project {project_id}, skipping")
            continue
        task = analysis_mgr.create_task(project_id, video.path, video_id=video.id)
        task_ids.append(task.task_id)

        analysis_mgr.start_task_process(
            task.task_id,
            progress_callback=make_callback(task.task_id)
        )

    if not task_ids:
        raise RPCError(-32002, f"No valid videos to analyze in project {project_id}")

    # 更新项目状态为分析中
    mgr.update_project(project_id, {"status": "analyzing"})

    logger.info(f"[Analyze] Queued {len(task_ids)} tasks inside child processes")
    return {"task_ids": task_ids}


def analyze_get_status(task_id: str) -> Dict:
    """获取分析状态

    Args:
        task_id: 任务ID

    Returns:
        任务状态和分析结果
    """
    from app.ipc.json_encoder import json_dumps, json_loads

    logger.info(f"[Analyze] Getting status: task_id={task_id}")
    analysis_mgr = get_analysis_manager()
    task = analysis_mgr.get_task(task_id)

    if not task:
        raise RPCError(-32002, f"Task not found: {task_id}")

    highlights = task.highlight_segments
    if highlights:
        enriched = []
        for h in highlights:
            if isinstance(h, dict):
                h = dict(h)
                if "video_path" not in h or not h["video_path"]:
                    h["video_path"] = task.video_path
                enriched.append(h)
            elif hasattr(h, 'to_dict'):
                d = h.to_dict()
                if not d.get("video_path"):
                    d["video_path"] = task.video_path
                enriched.append(d)
            else:
                enriched.append(h)
        highlights = enriched

    result_dict = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "phase": task.phase,
        "message": task.message,
        "results": {
            "asr": task.asr_result.to_dict() if task.asr_result else None,
            "emotion": (
                task.emotion_result.to_dict()
                if task.emotion_result and hasattr(task.emotion_result, 'to_dict')
                else task.emotion_result
            ),
            "highlights": highlights,
        } if task.status in ("completed",) else None,
        "error": task.error,
    }

    try:
        serialized = json_dumps(result_dict)
        return json_loads(serialized)
    except Exception as e:
        logger.warning(f"[Analyze] JSON serialization failed: {e}")
        return {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "phase": task.phase,
            "message": task.message,
            "results": None,
            "error": f"序列化错误: {str(e)}",
        }


def analyze_cancel(task_id: str) -> Dict:
    """取消分析任务

    Args:
        task_id: 任务ID

    Returns:
        取消结果
    """
    logger.info(f"[Analyze] Cancelling task: {task_id}")
    analysis_mgr = get_analysis_manager()
    success = analysis_mgr.cancel_task(task_id)

    if not success:
        raise RPCError(-32002, f"Task not found: {task_id}")

    logger.info(f"[Analyze] Cancelled task: {task_id}")
    return {"success": True}


def analyze_get_completed_results(project_id: str, video_ids: List[str]) -> Dict[str, Any]:
    """获取视频已完成的分析结果（自适应持久化恢复，避免重复转写计算）

    Args:
        project_id: 项目ID
        video_ids: 视频ID列表

    Returns:
        键为 video_id，值为分析结果（asr, emotion, highlights）的字典
    """
    import json
    from pathlib import Path

    logger.info(f"[Analyze] Querying completed results for {len(video_ids)} videos in project {project_id}")
    results = {}

    for vid in video_ids:
        output_dir = Path.home() / ".dramaclip" / "analysis" / vid
        if not output_dir.exists():
            continue

        asr_file = output_dir / "asr.json"
        highlights_file = output_dir / "highlights.json"

        # 只要存在 ASR 结果，就视作该视频已完成分析
        if asr_file.exists():
            try:
                asr_data = json.loads(asr_file.read_text(encoding="utf-8"))

                # 读取情绪分析（可选）
                emotion_data = None
                emotion_file = output_dir / "emotion.json"
                if emotion_file.exists():
                    emotion_data = json.loads(emotion_file.read_text(encoding="utf-8"))

                # 读取高光（可选）
                highlights_data = []
                if highlights_file.exists():
                    highlights_data = json.loads(highlights_file.read_text(encoding="utf-8"))

                results[vid] = {
                    "asr": asr_data,
                    "emotion": emotion_data,
                    "highlights": highlights_data,
                }
            except Exception as e:
                logger.warning(f"[Analyze] Failed to load cached result for video {vid}: {e}")

    return {"results": results}
