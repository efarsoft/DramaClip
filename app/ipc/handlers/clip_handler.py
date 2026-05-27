"""
剪辑 Handler（最终版）
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.utils.path_manager import get_path_manager
from .base import update_clip_task
from app.ipc.protocol import RPCError
from app.services.project.manager_sqlite import get_manager




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
            output_dir = Path.home() / ".dramaclip" / "analysis" / video.id
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
        update_clip_task(task_id, status="running", progress=5, message="正在启动剪辑流水线", project_id=project_id)

        pool = get_worker_pool()
        pool.submit(_run_clip_pipeline, task_id, video_paths, params, project_id, scheme)
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


def _select_segments_to_duration(
    segments: List[Dict[str, Any]],
    sort_key: Any,
    target_duration: Optional[int] = None
) -> List[Dict[str, Any]]:
    """根据分数指标排序并截取片段，使其符合目标时长限制"""
    # 按照特定分数指标倒序排列（得分最高的最先加入）
    sorted_segs = sorted(segments, key=sort_key, reverse=True)
    if not target_duration or target_duration <= 0:
        # 如果未指定时长，默认选择前 15 个精彩高光，避免视频无限拉长
        return sorted(sorted_segs[:15], key=lambda x: (x.get("video_path", ""), x.get("start_time") or x.get("start") or 0.0))
    
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
            
    # 最终必须按照时间轴的物理顺序重新进行升序排序，保证故事叙事和视频拼接流畅
    return sorted(selected, key=lambda x: (x.get("video_path", ""), x.get("start_time") or x.get("start") or 0.0))


def _run_clip_pipeline(task_id: str, video_paths: List[str], params: Dict[str, Any], project_name: str, scheme: Optional[str] = None):
    """
    执行剪辑流水线（后台调用）
    """
    try:
        output_path = params.get("output_path")
        target_duration = params.get("target_duration")
        segments = params.get("segments")
        mode = params.get("mode", "direct")
        crop_mode = params.get("crop_mode", "smart")

        if scheme == 'all_narrations':
            _run_triple_mode_task(
                task_id, video_paths, output_path,
                target_duration, project_name, segments, crop_mode
            )
        else:
            _run_direct_mode_task(
                task_id, video_paths, output_path,
                target_duration, project_name, segments, crop_mode, scheme=scheme
            )

    except Exception as e:
        logger.error(f"[Clip] Pipeline execution failed: {e}")
        update_clip_task(task_id, status="failed", message=str(e))
        raise


def _run_triple_mode_task(
    task_id: str,
    video_paths: List[str],
    output_path: Optional[str],
    target_duration: Optional[int],
    project_name: str,
    segments: Optional[List[Dict[str, Any]]],
    crop_mode: str = "smart",
) -> Dict:
    """一键三连：生成三个不同风格的高光剪辑视频"""
    path_mgr = get_path_manager()
    
    # 放到全局统一的输出根目录下的项目子目录中，彻底解决污染项目源码目录的问题
    output_original = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_original.mp4"))
    output_hybrid = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_hybrid.mp4"))
    output_full = str(path_mgr.get_output_path(project_name=project_name, filename=f"clip_{task_id[:8]}_full.mp4"))
    
    logger.info(f"[Clip] 一键三连输出目标: {output_original}, {output_hybrid}, {output_full}")

    def progress_cb(version: str, start_pct: int, end_pct: int):
        def cb(stage: str, progress: int, message: str):
            mapped_progress = start_pct + int((progress / 100.0) * (end_pct - start_pct))
            update_clip_task(task_id, progress=mapped_progress, phase=stage, message=f"[{version}] {message}")
        return cb

    try:
        pipeline = ModularDirectCutPipeline()
        
        # 1. 剪辑【原片解说】视频
        update_clip_task(task_id, progress=10, phase="clipping", message="正在生成第一版：原片解说...")
        orig_segs = None
        if segments:
            orig_segs = _select_segments_to_duration(
                segments, 
                lambda x: float(x.get("score") or x.get("total_score") or 0.0), 
                target_duration
            )
        pipeline.run(
            video_paths=video_paths,
            output_path=output_original,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=progress_cb("原片解说", 10, 40),
            crop_mode=crop_mode,
            segments=orig_segs
        )

        # 2. 剪辑【交叉解说】视频
        update_clip_task(task_id, progress=40, phase="clipping", message="正在生成第二版：交叉解说...")
        hybrid_segs = None
        if segments:
            hybrid_segs = _select_segments_to_duration(
                segments, 
                lambda x: float(x.get("emotion_score") or x.get("audio_score") or 0.0), 
                target_duration
            )
        pipeline.run(
            video_paths=video_paths,
            output_path=output_hybrid,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=progress_cb("交叉解说", 40, 70),
            crop_mode=crop_mode,
            segments=hybrid_segs
        )

        # 3. 剪辑【全片解说】视频
        update_clip_task(task_id, progress=70, phase="clipping", message="正在生成第三版：全片解说...")
        full_segs = None
        if segments:
            full_segs = _select_segments_to_duration(
                segments, 
                lambda x: float(x.get("rhythm_score") or x.get("visual_score") or 0.0), 
                target_duration
            )
        pipeline.run(
            video_paths=video_paths,
            output_path=output_full,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=progress_cb("全片解说", 70, 95),
            crop_mode=crop_mode,
            segments=full_segs
        )

        # 保存所有生成版本到 task.result 并更新任务状态
        from app.services.task_manager import get_task_manager
        task = get_task_manager().get_task(task_id)
        if task:
            task.result = {"all_outputs": [output_original, output_hybrid, output_full]}

        update_clip_task(
            task_id,
            progress=100,
            phase="completed",
            message="一键三连剪辑全部完成！",
            status="completed",
            output_path=output_original
        )

        logger.info(f"[Clip] 一键三连全部生成成功: {output_original}, {output_hybrid}, {output_full}")
        return {"output_path": output_original, "mode": "all_narrations"}

    except Exception as e:
        logger.error(f"[Clip] 一键三连剪辑失败: {e}")
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
    scheme: Optional[str] = None,
) -> Dict:
    """执行单个精彩高光模式剪辑任务（含进度更新）"""
    path_mgr = get_path_manager()
    if output_path is None:
        output_path = str(
            path_mgr.get_output_path(
                project_name=project_name,
                filename=f"clip_{task_id[:8]}_direct.mp4"
            )
        )

    logger.info(f"[Clip] Direct mode output: {output_path} with scheme {scheme}")

    def progress_cb(stage: str, progress: int, message: str):
        update_clip_task(task_id, progress=progress, phase=stage, message=message)

    try:
        pipeline = ModularDirectCutPipeline()
        
        # 根据剪辑风格，过滤并重新选择排序
        if segments:
            if scheme == "hybrid_narration":
                segments = _select_segments_to_duration(
                    segments, 
                    lambda x: float(x.get("emotion_score") or x.get("audio_score") or 0.0), 
                    target_duration
                )
            elif scheme == "full_narration":
                segments = _select_segments_to_duration(
                    segments, 
                    lambda x: float(x.get("rhythm_score") or x.get("visual_score") or 0.0), 
                    target_duration
                )
            else: # original_narration 或其他
                segments = _select_segments_to_duration(
                    segments, 
                    lambda x: float(x.get("score") or x.get("total_score") or 0.0), 
                    target_duration
                )

        final_path = pipeline.run(
            video_paths=video_paths,
            output_path=output_path,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=progress_cb,
            crop_mode=crop_mode,
            segments=segments,
        )

        update_clip_task(
            task_id,
            progress=100,
            phase="completed",
            message="智能高光剪辑完成",
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
