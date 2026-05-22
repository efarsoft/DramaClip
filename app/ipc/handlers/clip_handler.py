"""
剪辑 Handler（最终版）
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.utils.path_manager import get_path_manager
from .base import update_clip_task
from app.ipc.protocol import RPCError




def clip_recommend(project_id: str) -> Dict[str, Any]:
    """
    智能推荐剪辑模式

    Args:
        project_id: 项目ID

    Returns:
        推荐结果
    """
    from app.services.mode_recommender import get_smart_recommender, ModeRecommendation
    from app.services.project.manager_sqlite import get_manager

    logger.info(f"[Clip] Getting recommendation for project: {project_id}")

    try:
        manager = get_manager()
        project = manager.get_project(project_id)

        if not project:
            raise RPCError(-32101, f"项目不存在: {project_id}")

        videos = manager.get_videos(project_id)
        video_paths = [v.path for v in videos]

        if not video_paths:
            raise RPCError(-32002, "项目中没有视频")

        recommender = get_smart_recommender()

        def progress_cb(progress: int, message: str):
            logger.debug(f"[Recommender] {progress}% - {message}")

        recommendation = recommender.analyze_and_recommend(
            video_paths=video_paths,
            video_info=[{"duration": getattr(v, 'duration', 0)} for v in videos],
            progress_callback=progress_cb,
        )

        return {
            "episode_count": len(video_paths),
            "episode_type": "multi" if len(video_paths) > 1 else "single",
            "recommended_scheme": recommendation.recommended_mode.value,
            "confidence": recommendation.confidence,
            "reasons": recommendation.reasons,
            "alternatives": [alt.value for alt in recommendation.alternatives],
            "suggested_ratio": recommendation.suggested_ratio,
            "target_duration": recommendation.target_duration,
            "auto_title_enabled": recommendation.auto_title_enabled,
        }

    except RPCError:
        raise
    except Exception as e:
        logger.error(f"[Clip] Recommendation failed: {e}")
        raise RPCError(-32300, f"推荐失败: {e}")


def clip_generate_title(project_id: str, count: int = 5) -> Dict[str, Any]:
    """
    生成AI标题和简介

    Args:
        project_id: 项目ID
        count: 生成标题数量，默认5个

    Returns:
        标题生成结果
    """
    from app.services.title_generator import get_title_generator, TitleGenerationResult, TitleStyle
    
    logger.info(f"[Clip] Generating titles for project: {project_id}, count: {count}")

    try:
        from app.services.project.manager_sqlite import get_manager
        manager = get_manager()
        project = manager.get_project(project_id)

        if not project:
            raise RPCError(-32101, f"项目不存在: {project_id}")

        videos = manager.get_videos(project_id)
        video_paths = [v.path for v in videos]

        if not video_paths:
            raise RPCError(-32002, "项目中没有视频")

        generator = get_title_generator()
        
        content_analysis = {
            "video_type": "drama",
            "content_summary": "精彩的剧集内容",
            "highlights": [],
            "video_count": len(video_paths),
        }

        result: TitleGenerationResult = generator.generate(
            content_analysis=content_analysis,
            title_count=count,
        )

        style_map = {
            TitleStyle.SHOCKING: "shocking",
            TitleStyle.SUSPENSE: "suspense",
            TitleStyle.EMOTIONAL: "emotional",
            TitleStyle.HUMOROUS: "humorous",
            TitleStyle.CURIOSITY: "curiosity",
            TitleStyle.CONTROVERSIAL: "controversial",
        }

        style_label_map = {
            TitleStyle.SHOCKING: "震惊型",
            TitleStyle.SUSPENSE: "悬念型",
            TitleStyle.EMOTIONAL: "情感型",
            TitleStyle.HUMOROUS: "幽默型",
            TitleStyle.CURIOSITY: "好奇型",
            TitleStyle.CONTROVERSIAL: "争议型",
        }

        titles = []
        for title in result.titles:
            titles.append({
                "title": title.title,
                "style": style_map.get(title.style, "emotional"),
                "style_label": style_label_map.get(title.style, "情感型"),
                "description": title.description,
                "score": title.score,
            })

        intro = {
            "short": result.intro.short_intro,
            "medium": result.intro.medium_intro,
            "long": result.intro.long_intro,
            "hashtags": result.intro.hashtags,
        }

        return {
            "success": True,
            "titles": titles,
            "intro": intro,
            "platform_suggestions": ["抖音", "快手", "B站", "小红书"],
        }

    except RPCError:
        raise
    except Exception as e:
        logger.error(f"[Clip] Title generation failed: {e}")
        raise RPCError(-32300, f"标题生成失败: {e}")


def clip_execute(project_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行剪辑任务（异步）

    Args:
        project_id: 项目ID
        params: 剪辑参数

    Returns:
        任务ID和状态
    """
    import uuid
    from .base import get_worker_pool
    logger.info(f"[Clip] Executing clip for project: {project_id}")

    try:
        manager = get_manager()
        project = manager.get_project(project_id)

        if not project:
            raise RPCError(-32101, f"项目不存在: {project_id}")

        videos = manager.get_videos(project_id)
        if not videos:
            raise RPCError(-32002, "项目中没有视频")

        task_id = str(uuid.uuid4())
        video_paths = [v.path for v in videos]

        # 先登记任务状态，再异步提交到线程池
        update_clip_task(task_id, status="running", progress=5, message="正在启动剪辑流水线")

        pool = get_worker_pool()
        pool.submit(_run_clip_pipeline, task_id, video_paths, params, project.name)
        logger.info(f"[Clip] Submitted pipeline task: {task_id}")

        return {
            "task_id": task_id,
            "status": "running",
            "message": "剪辑流水线已启动"
        }

    except RPCError:
        raise
    except Exception as e:
        logger.error(f"[Clip] Execute failed: {e}")
        raise RPCError(-32300, f"执行剪辑失败: {e}")


def _run_clip_pipeline(task_id: str, video_paths: List[str], params: Dict[str, Any], project_name: str):
    """
    执行剪辑流水线（后台调用）
    """
    try:
        output_path = params.get("output_path")
        target_duration = params.get("target_duration")
        segments = params.get("segments")
        mode = params.get("mode", "direct")
        crop_mode = params.get("crop_mode", "smart")

        _run_direct_mode_task(
            task_id, video_paths, output_path,
            target_duration, project_name, segments, crop_mode
        )

    except Exception as e:
        logger.error(f"[Clip] Pipeline execution failed: {e}")
        update_clip_task(task_id, status="failed", message=str(e))
        raise


def _run_direct_mode_task(
    task_id: str,
    video_paths: List[str],
    output_path: Optional[str],
    target_duration: Optional[int],
    project_name: str,
    segments: Optional[List[Dict[str, Any]]],
    crop_mode: str = "smart",
) -> Dict:
    """执行原片直剪任务（含进度更新）"""
    path_mgr = get_path_manager()
    if output_path is None:
        output_path = str(
            path_mgr.get_output_path(
                project_name=project_name,
                filename=f"clip_{task_id[:8]}_direct.mp4"
            )
        )

    logger.info(f"[Clip] Direct mode output: {output_path}")

    def progress_cb(stage: str, progress: int, message: str):
        update_clip_task(task_id, progress=progress, phase=stage, message=message)

    try:
        pipeline = ModularDirectCutPipeline()
        final_path = pipeline.run(
            video_paths=video_paths,
            output_path=output_path,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=progress_cb,
            crop_mode=crop_mode,
        )

        update_clip_task(
            task_id,
            progress=100,
            phase="completed",
            message="原片直剪完成",
            status="completed",
            output_path=final_path
        )

        logger.info(f"[Clip] Direct mode completed: {final_path}")
        return {"output_path": final_path, "mode": "original"}

    except Exception as e:
        logger.error(f"[Clip] Direct mode failed: {e}")
        update_clip_task(task_id, status="failed", message=str(e))
        raise


def clip_get_progress(task_id: str) -> Dict[str, Any]:
    """
    获取剪辑任务进度

    Args:
        task_id: 任务ID

    Returns:
        任务进度信息
    """
    from .base import get_clip_task

    task = get_clip_task(task_id)
    if not task:
        raise RPCError(-32002, f"任务不存在: {task_id}")

    return task


def clip_preview(project_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    预览剪辑效果

    Args:
        project_id: 项目ID
        params: 预览参数

    Returns:
        预览信息
    """
    logger.info(f"[Clip] Preview for project: {project_id}")

    try:
        manager = get_manager()
        project = manager.get_project(project_id)

        if not project:
            raise RPCError(-32101, f"项目不存在: {project_id}")

        videos = manager.get_videos(project_id)
        if not videos:
            raise RPCError(-32002, "项目中没有视频")

        # TODO: 实现预览逻辑
        return {
            "success": True,
            "message": "预览功能开发中",
            "video_count": len(videos)
        }

    except RPCError:
        raise
    except Exception as e:
        logger.error(f"[Clip] Preview failed: {e}")
        raise RPCError(-32300, f"预览失败: {e}")


def clip_stop(task_id: str) -> Dict[str, Any]:
    """
    停止剪辑任务

    Args:
        task_id: 任务ID

    Returns:
        停止结果
    """
    from .base import update_clip_task

    logger.info(f"[Clip] Stopping task: {task_id}")

    try:
        update_clip_task(task_id, status="cancelled", message="任务已取消")
        return {"success": True, "message": "任务已停止"}
    except Exception as e:
        logger.error(f"[Clip] Stop failed: {e}")
        raise RPCError(-32300, f"停止任务失败: {e}")
