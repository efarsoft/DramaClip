"""
剪辑 Handler

业务逻辑已下沉到 app/services/clip/orchestrator.py，
此文件仅做参数解包、调用服务、构造返回值。
"""

from functools import partial
from typing import Any, Dict, List, Optional
from loguru import logger

from .base import update_task as update_clip_task
from app.ipc.protocol import RPCError
from app.services.project.manager_sqlite import get_manager
from app.services.clip.orchestrator import run_clip_pipeline




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
    from app.services.llm.unified_service import UnifiedLLMService
    from app.services.llm.migration_adapter import _run_async_safely
    from pathlib import Path
    import json
    
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

        # 1. 聚合所有已分析视频的 ASR 转写文本
        combined_asr_text = ""
        total_duration = 0.0
        
        for video in videos:
            total_duration += getattr(video, 'duration', 0.0) or 0.0
            output_dir = Path.home() / ".dramaclip" / "analysis" / project_id / video.id
            asr_file = output_dir / "asr.json"
            if asr_file.exists():
                try:
                    asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
                    segments = asr_data.get("segments", [])
                    segments_sorted = sorted(segments, key=lambda x: x.get("start", 0.0))
                    video_text = " ".join([seg.get("text", "").strip() for seg in segments_sorted if seg.get("text", "").strip()])
                    if video_text:
                        combined_asr_text += f"\n【第{video.sort_order + 1}集 {video.name}】:\n{video_text}\n"
                except Exception as e:
                    logger.warning(f"[Clip] Failed to read ASR for video {video.id}: {e}")

        # 2. 如果有识别文本，通过大模型提炼大纲与情节
        llm_summary = None
        if combined_asr_text.strip():
            try:
                # 限制 ASR 长度，防止超 token (取前 6000 字符)
                truncated_asr = combined_asr_text[:6000]
                
                prompt = f"""你是一位专业的视频内容策划专家。请根据以下剧集视频的 ASR 语音识别文本，深度提炼并输出以下结构的 JSON 数据：
{{
  "content_summary": "一句话剧透/吸引人的剧情概要，不超过80字",
  "main_plots": ["主要核心情节1", "主要核心情节2"],
  "characters": ["主要人物/主要主题1", "主要人物/主要主题2"],
  "highlights": ["最具有戏剧冲突的爆点/高潮部分1", "最具有戏剧冲突的爆点/高潮部分2"],
  "video_type": "剧集类型，如 悬疑片/爽剧/情感剧/都市喜剧/家庭伦理剧 等"
}}

要求：
1. 返回结果必须是合法的 JSON 格式。
2. 绝对不要包含 markdown 代码块标记，不要以 ```json 开头或以 ``` 结尾，直接输出裸 JSON 字符串即可。

ASR 识别文本如下：
{truncated_asr}
"""
                logger.info("[Clip] Calling LLM to summarize ASR story context...")
                response = _run_async_safely(
                    UnifiedLLMService.generate_text,
                    prompt=prompt,
                    max_tokens=1000,
                    temperature=0.7,
                )
                
                # 安全解析 JSON
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()
                
                llm_summary = json.loads(cleaned_response)
                logger.info(f"[Clip] Successfully summarized context: {llm_summary}")
            except Exception as e:
                logger.error(f"[Clip] Failed to summarize ASR with LLM: {e}")

        # 3. 组装最终 Content Analysis 信息
        if llm_summary and isinstance(llm_summary, dict):
            content_analysis = {
                "video_type": llm_summary.get("video_type", "短视频"),
                "content_summary": llm_summary.get("content_summary", f"精彩剧集《{project.name}》"),
                "main_plots": llm_summary.get("main_plots", []),
                "characters": llm_summary.get("characters", []),
                "highlights": llm_summary.get("highlights", []),
                "duration": int(total_duration),
                "subtitle_content": combined_asr_text,
                "video_count": len(video_paths),
            }
        else:
            content_analysis = {
                "video_type": "短视频",
                "content_summary": f"精彩剧集《{project.name}》片段",
                "main_plots": [f"《{project.name}》精彩主线情节展开"],
                "characters": ["主人公"],
                "highlights": ["高燃/高虐精彩瞬间"],
                "duration": int(total_duration) or 60,
                "subtitle_content": combined_asr_text,
                "video_count": len(video_paths),
            }

        # 4. 生成爆款标题与简介
        generator = get_title_generator()
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


def clip_execute(project_id: str, params: Dict[str, Any], scheme: Optional[str] = None, **kwargs) -> Dict[str, Any]:
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

        # 更新项目状态为 clipping，并在创建任务时关联项目ID
        manager.update_project(project_id, {"status": "clipping"})
        update_clip_task(task_id, status="running", progress=5, message="正在启动剪辑流水线", project_id=project_id, task_kind="Clip")

        pool = get_worker_pool()
        task_updater = partial(update_clip_task, task_id, task_kind="Clip")
        pool.submit(run_clip_pipeline, task_id, video_paths, params, project_id, task_updater, scheme)
        logger.info(f"[Clip] Submitted pipeline task: {task_id} with scheme {scheme}")

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


# ---------------------------------------------------------------------------
# 业务逻辑已下沉到 app.services.clip.orchestrator
# clip_execute 通过 pool.submit 调用 run_clip_pipeline
# ---------------------------------------------------------------------------


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

        # 轻量预览实现（2026-05）：返回项目基本信息 + 推荐使用第一段做快速预览
        # 完整高质量预览建议后续通过 clip_execute + 小 target_duration + 返回临时文件实现
        from app.config.unified_config import get_config
        from app.utils.path_manager import get_path_manager

        path_mgr = get_path_manager()
        preview_dir = path_mgr.temp_root / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)

        sample_segments = []
        for v in videos[:2]:  # 最多采样前 2 个视频
            sample_segments.append({
                "video_path": v.get("path"),
                "episode": v.get("episode_index"),
                "suggested_start": 0,
                "suggested_end": min(25, v.get("duration", 60)),
                "reason": "轻量预览采样"
            })

        preview_id = f"preview_{project_id}_{int(__import__('time').time())}"
        preview_info = {
            "success": True,
            "preview_id": preview_id,
            "message": "轻量预览（采样前 1-2 个高光点）。完整预览建议使用小 target_duration 调用 clip_execute。",
            "video_count": len(videos),
            "sample_segments": sample_segments,
            "suggested_output": str(preview_dir / f"{preview_id}.mp4"),
            "note": "前端可使用 dramaclip://local/ 协议播放返回的临时预览文件"
        }
        return preview_info

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
    from .base import update_task

    logger.info(f"[Clip] Stopping task: {task_id}")

    try:
        update_task(task_id, status="cancelled", message="任务已取消", task_kind="Clip")
        return {"success": True, "message": "任务已停止"}
    except Exception as e:
        logger.error(f"[Clip] Stop failed: {e}")
        raise RPCError(-32300, f"停止任务失败: {e}")
