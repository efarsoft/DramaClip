"""
IPC 处理函数实现
使用 app/services/ 下的服务实现核心逻辑
"""

import asyncio
import json
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from app.services.project.manager import get_manager, ProjectManager
from app.services.analyze.manager import get_analysis_manager
from .protocol import RPCError

# Server reference for sending progress notifications
_server = None  # type: ignore

# ── 全局线程池 ──
_WORKER_COUNT = 5  # 默认5个并发工作线程
_pool = ThreadPoolExecutor(max_workers=_WORKER_COUNT, thread_name_prefix="work")


def set_server(server):
    """Set the IPC server instance (called by backend_main.py)"""
    global _server
    _server = server


def _send_progress(task_id: str, progress: int, message: str, phase: str = None):
    """Send progress notification via IPC server"""
    if _server:
        _server.send_progress(task_id, progress, message, phase)


# ============================================================================
# 项目管理
# ============================================================================

def project_list() -> List[Dict]:
    """获取所有项目列表"""
    logger.info("project_list: entry")
    manager = get_manager()
    projects = manager.list_projects()
    # 直接使用 to_dict()，与 ProjectMeta.model_dump() 保持一致
    # 前端 Project 接口需要: id, name, path, created_at, updated_at, episode_count, status
    result = [p.to_dict() for p in projects]
    logger.info(f"project_list: returning {len(result)} projects")
    return result


def project_create(name: str, path: str) -> Dict:
    """创建新项目"""
    logger.info(f"project_create: entry (name={name!r}, path={path!r})")
    if not name:
        raise RPCError(-32602, "Name is required")

    # 路径为空时使用默认路径
    if not path:
        import os
        path = os.path.expanduser("~/DramaClipProjects")

    manager = get_manager()
    project = manager.create_project(name, path)
    logger.info(f"Created project: {name}")
    return project.to_dict()


def project_open(project_id: str) -> Dict:
    """打开项目，自动扫描视频目录"""
    logger.info(f"project_open: entry (project_id={project_id!r})")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    manager = get_manager()
    project = manager.open_project(project_id)

    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"Opened project: {project_id}")
    
    # 返回视频列表
    videos = manager.get_videos(project_id)
    result = project.to_dict()
    result["videos"] = [v.to_dict() for v in videos]
    return result


def project_delete(project_id: str, keep_files: bool = False) -> Dict:
    """删除项目"""
    logger.info(f"project_delete: entry (project_id={project_id!r}, keep_files={keep_files})")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    manager = get_manager()
    success = manager.delete_project(project_id, keep_files)

    if not success:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"Deleted project: {project_id}")
    return {"success": True}


def project_rename(project_id: str, new_name: str) -> Dict:
    """重命名项目"""
    logger.info(f"project_rename: entry (project_id={project_id!r}, new_name={new_name!r})")
    if not project_id:
        raise RPCError(-32602, "project_id is required")
    if not new_name:
        raise RPCError(-32602, "Name is required")

    manager = get_manager()
    project = manager.rename_project(project_id, new_name)

    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"Renamed project: {project_id} -> {new_name}")
    return project.to_dict()


def project_import_videos(project_id: str, paths: List[str]) -> List[Dict]:
    """导入视频文件到项目"""
    logger.info(f"project_import_videos: entry (project_id={project_id!r}, paths_count={len(paths)})")
    if not project_id:
        raise RPCError(-32602, "project_id is required")
    if not paths:
        return []

    manager = get_manager()
    videos = manager.import_videos(project_id, paths)
    logger.info(f"Imported {len(videos)} videos to project {project_id}")
    return [v.to_dict() for v in videos]


def project_get_videos(project_id: str) -> List[Dict]:
    """获取项目的视频列表"""
    logger.info(f"project_get_videos: entry (project_id={project_id!r})")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    manager = get_manager()
    videos = manager.get_videos(project_id)
    return [v.to_dict() for v in videos]


# ============================================================================
# 分析
# ============================================================================


def _run_async_analysis(analysis_mgr, task_id: str):
    """在后台线程中运行异步分析，通过 _server 发送进度通知"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def send_progress_via_ipc(progress_data: dict):
            _send_progress(
                task_id=progress_data["task_id"],
                progress=progress_data["progress"],
                message=progress_data.get("message", ""),
                phase=progress_data.get("phase", ""),
            )

        loop.run_until_complete(
            analysis_mgr.run_analysis(task_id, progress_callback=send_progress_via_ipc)
        )
    except Exception as e:
        logger.exception(f"Analysis task {task_id} failed: {e}")
        _send_progress(task_id, 100, f"分析失败: {e}", "error")
    finally:
        loop.close()


def analyze_start(project_id: str, episode_ids: List[str]) -> Dict:
    if episode_ids is None:
        raise RPCError(-32602, "episode_ids is required")

    mgr = get_manager()
    analysis_mgr = get_analysis_manager()

    # 获取项目所有视频
    videos = mgr.get_videos(project_id)
    if not videos:
        raise RPCError(-32002, f"No videos found in project {project_id}")

    # 空列表 = 分析该项目所有视频
    if episode_ids == []:
        episode_ids = [v.id for v in videos]

    # 建立 id -> video 映射
    video_map = {v.id: v for v in videos}

    task_ids = []
    for episode_id in episode_ids:
        video = video_map.get(episode_id)
        if not video:
            logger.warning(f"Video {episode_id} not found in project {project_id}, skipping")
            continue
        task = analysis_mgr.create_task(project_id, video.path)
        task_ids.append(task.task_id)

        # 用线程池提交分析任务（自动限流为 max_workers 个并发）
        _pool.submit(_run_async_analysis, analysis_mgr, task.task_id)

    if not task_ids:
        raise RPCError(-32002, f"No valid videos to analyze in project {project_id}")

    logger.info(f"Queued {len(task_ids)} analysis tasks for project {project_id} (max concurrent: {_WORKER_COUNT})")
    return {"task_ids": task_ids}


def analyze_get_status(task_id: str) -> Dict:
    """获取分析状态"""
    analysis_mgr = get_analysis_manager()
    task = analysis_mgr.get_task(task_id)
    if not task:
        raise RPCError(-32002, f"Task not found: {task_id}")

    # 为每个高光片段添加 video_path，并确保为可序列化的 dict
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
                # HighlightSegment 对象 → 转为 dict
                d = h.to_dict()
                if not d.get("video_path"):
                    d["video_path"] = task.video_path
                enriched.append(d)
            else:
                enriched.append(h)
        highlights = enriched

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "phase": task.phase,
        "message": task.message,
        "results": {
            "asr": task.asr_result,
            "emotion": task.emotion_result,
            "highlights": highlights,
        } if task.status in ("completed",) else None,
        "error": task.error,
    }


def analyze_cancel(task_id: str) -> Dict:
    """取消分析任务"""
    analysis_mgr = get_analysis_manager()
    success = analysis_mgr.cancel_task(task_id)
    if not success:
        raise RPCError(-32002, f"Task not found: {task_id}")
    logger.info(f"Cancelled analysis task: {task_id}")
    return {"success": True}


# ============================================================================
# 剪辑
# ============================================================================

# 剪辑任务跟踪：task_id -> { status, progress, phase, message, output_path }
_clip_tasks: Dict[str, Dict] = {}
_clip_tasks_lock = threading.Lock()


def _update_clip_task(task_id: str, **kwargs):
    """线程安全地更新剪辑任务状态"""
    with _clip_tasks_lock:
        if task_id not in _clip_tasks:
            _clip_tasks[task_id] = {
                "task_id": task_id,
                "status": "running",
                "progress": 0,
                "phase": "",
                "message": "",
                "output_path": None,
            }
        _clip_tasks[task_id].update(kwargs)


def _run_single_clip_mode(
    task_id: str,
    mode_name: str,
    pipeline_type: str,
    video_paths: List[str],
    output_path: str,
    message_start: str,
    message_done: str,
    target_duration: Optional[int] = None,
    num_versions: int = 1,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> Dict:
    """线程安全地运行单个剪辑模式，返回结果字典"""
    try:
        _update_clip_task(task_id, progress=5, phase=mode_name, message=message_start)

        if pipeline_type == "direct":
            from app.services.direct_cut.pipeline import DirectCutPipeline
            from app.services.highlight.selector import HighlightSegment
            pipeline = DirectCutPipeline()

            # 如果提供了预选片段，跳过场景检测/打分/选择
            if segments:
                _update_clip_task(task_id, progress=10, phase=mode_name, message=f"使用 {len(segments)} 个预选片段...")
                selected = [
                    HighlightSegment(
                        video_path=s.get("video_path", video_paths[0]),
                        start_time=s["start_time"],
                        end_time=s["end_time"],
                        score=s.get("score", 1.0),
                        segment_id=s.get("id", f"seg-{i}"),
                    )
                    for i, s in enumerate(segments)
                ]
            else:
                _update_clip_task(task_id, progress=10, phase=mode_name, message="场景检测...")
                scenes = pipeline._detect_scenes(video_paths)
                _update_clip_task(task_id, progress=20, phase=mode_name, message=f"检测到 {len(scenes)} 个场景")

                _update_clip_task(task_id, progress=25, phase=mode_name, message="高光打分...")
                scored = pipeline._score_scenes(scenes)
                _update_clip_task(task_id, progress=35, phase=mode_name, message=f"完成 {len(scored)} 个片段打分")

                _update_clip_task(task_id, progress=40, phase=mode_name, message="选择高光片段...")
                selected = pipeline._select_highlights(scored, target_duration)
                _update_clip_task(task_id, progress=50, phase=mode_name, message=f"选中 {len(selected)} 个高光片段")

            _update_clip_task(task_id, progress=55, phase=mode_name, message="智能排序...")
            sorted_segments = pipeline._sort_segments(selected)
            _update_clip_task(task_id, progress=60, phase=mode_name, message="排序完成")

            _update_clip_task(task_id, progress=65, phase=mode_name, message="正在剪辑拼接...")
            final_path = pipeline._cut_and_concat(sorted_segments, output_path)
            _update_clip_task(task_id, progress=100, phase="completed", message=message_done)
            logger.info(f"Mode {mode_name} ({task_id}): {final_path}")
            return {"output_path": final_path, "mode": mode_name}

        elif pipeline_type in ("hybrid", "full"):
            from app.services.narration.pipeline import NarrationPipeline

            pipeline = NarrationPipeline()
            _update_clip_task(task_id, progress=10, phase=mode_name, message="解析剧情...")
            _update_clip_task(task_id, progress=25, phase=mode_name, message="生成解说文案...")
            _update_clip_task(task_id, progress=40, phase=mode_name, message="语音合成...")
            _update_clip_task(task_id, progress=55, phase=mode_name, message="剪辑原片...")

            mix_mode = "overlay" if pipeline_type == "hybrid" else "replace"
            _update_clip_task(task_id, progress=60, phase=mode_name, message="音画合成...")
            final_path = pipeline.run(
                video_paths, output_path=output_path, target_duration=target_duration, mix_mode=mix_mode,
            )
            _update_clip_task(task_id, progress=100, phase="completed", message=message_done)
            logger.info(f"Mode {mode_name} ({task_id}): {final_path}")
            return {"output_path": final_path, "mode": mode_name}

        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")

    except Exception as e:
        logger.exception(f"Mode {mode_name} ({task_id}) failed: {e}")
        return {"error": str(e), "mode": mode_name}

# ============================================================================
# _run_clip_pipeline — 根据 scheme 调度不同的剪辑流水线
# ============================================================================
def _run_clip_pipeline(
    task_id: str,
    scheme: str,
    video_paths: List[str],
    output_path: str,
    target_duration: Optional[int] = None,
    num_versions: int = 1,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """根据 scheme 执行不同的剪辑流水线"""
    try:
        if scheme == "hybrid_narration":
            # 混合解说：保留原声 + 叠加解说
            from app.services.narration.pipeline import NarrationPipeline

            pipeline = NarrationPipeline()
            _update_clip_task(task_id, progress=5, phase="plot_parse", message="解析剧情...")
            _update_clip_task(task_id, progress=30, phase="narration_gen", message="生成解说文案...")
            _update_clip_task(task_id, progress=50, phase="tts", message="语音合成...")
            _update_clip_task(task_id, progress=70, phase="cutting", message="剪辑原片...")
            _update_clip_task(task_id, progress=85, phase="mixing", message="音画合成（保留原声）...")
            if output_path is None:
                output_path = pipeline.direct_cut_pipeline._generate_output_path(video_paths[0])
            final_path = pipeline.run(video_paths, output_path=output_path, target_duration=target_duration, mix_mode="overlay")
            _update_clip_task(task_id, progress=100, phase="completed", message="混合解说完成", status="completed", output_path=final_path)
            logger.info(f"Clip task {task_id} (hybrid_narration) completed: {final_path}")

        elif scheme == "full_narration":
            # 全解说：替换原声为解说
            from app.services.narration.pipeline import NarrationPipeline

            pipeline = NarrationPipeline()
            _update_clip_task(task_id, progress=5, phase="plot_parse", message="解析剧情...")
            _update_clip_task(task_id, progress=30, phase="narration_gen", message="生成解说文案...")
            _update_clip_task(task_id, progress=50, phase="tts", message="语音合成...")
            _update_clip_task(task_id, progress=70, phase="cutting", message="剪辑原片...")
            _update_clip_task(task_id, progress=85, phase="mixing", message="音画合成（替换原声）...")
            if output_path is None:
                output_path = pipeline.direct_cut_pipeline._generate_output_path(video_paths[0])
            final_path = pipeline.run(video_paths, output_path=output_path, target_duration=target_duration, mix_mode="replace")
            _update_clip_task(task_id, progress=100, phase="completed", message="全解说完成", status="completed", output_path=final_path)
            logger.info(f"Clip task {task_id} (full_narration) completed: {final_path}")

        elif scheme == "all_narrations":
            # 全模式：3种模式并行执行（线程池调度，默认5线程可同时处理3个模式+其他任务）
            from app.services.direct_cut.pipeline import DirectCutPipeline
            from app.services.narration.pipeline import NarrationPipeline
            from concurrent.futures import wait, FIRST_COMPLETED
            from pathlib import Path

            base_dir = Path(output_path).parent if output_path else Path(tempfile.gettempdir())

            # 定义3个并行任务的输出路径
            mode_configs = {
                "direct": {
                    "output": str(base_dir / f"dramaclip_{task_id[:8]}_direct.mp4"),
                    "message_start": "原片直剪...",
                    "message_done": "原片直剪完成",
                    "pipeline_type": "direct",
                },
                "hybrid": {
                    "output": str(base_dir / f"dramaclip_{task_id[:8]}_hybrid.mp4"),
                    "message_start": "混合解说...",
                    "message_done": "混合解说完成",
                    "pipeline_type": "hybrid",
                },
                "full": {
                    "output": str(base_dir / f"dramaclip_{task_id[:8]}_full.mp4"),
                    "message_start": "全解说...",
                    "message_done": "全解说完成",
                    "pipeline_type": "full",
                },
            }

            # 提交3个并行任务，用 future -> mode_name 映射来跟踪结果
            future_to_mode: Dict["concurrent.futures.Future", str] = {}
            _pool.submit(_update_clip_task, task_id, progress=5, phase="preparing", message="启动三种模式...")

            for mode_name, cfg in mode_configs.items():
                future = _pool.submit(
                    _run_single_clip_mode,
                    task_id, mode_name, cfg["pipeline_type"], video_paths,
                    cfg["output"], cfg["message_start"], cfg["message_done"],
                    target_duration, num_versions, segments,
                )
                future_to_mode[future] = mode_name

            # 等待所有模式完成，实时聚合进度
            all_paths: Dict[str, Optional[str]] = {}
            errors: Dict[str, str] = {}

            from concurrent.futures import as_completed
            for future in as_completed(future_to_mode):
                mode_name = future_to_mode[future]
                try:
                    result = future.result()
                    if result and "output_path" in result:
                        all_paths[mode_name] = result["output_path"]
                except Exception as e:
                    errors[mode_name] = str(e)
                    logger.warning(f"Mode {mode_name} failed: {e}")

            # 汇总进度
            final_path = all_paths.get("direct", "")
            _update_clip_task(
                task_id, progress=100, phase="completed",
                message="三种模式全部完成" + (f"，{len(errors)} 个失败" if errors else ""),
                status="completed",
                output_path=final_path,
                extra_outputs={
                    "hybrid": all_paths.get("hybrid"),
                    "full": all_paths.get("full"),
                },
            )
            logger.info(f"Clip task {task_id} (all_narrations) completed: direct={all_paths.get('direct')}, hybrid={all_paths.get('hybrid')}, full={all_paths.get('full')}, errors={list(errors.keys())}")

        elif scheme == "original_narration":
            # 原片解说：DirectCutPipeline（同 direct 模式）
            from app.services.direct_cut.pipeline import DirectCutPipeline
            from app.services.highlight.selector import HighlightSegment

            pipeline = DirectCutPipeline()
            _update_clip_task(task_id, progress=5, phase="original_narration", message="原片直剪...")

            if segments:
                _update_clip_task(task_id, progress=10, phase="original_narration", message=f"使用 {len(segments)} 个预选片段...")
                selected = [
                    HighlightSegment(
                        video_path=s.get("video_path", video_paths[0]),
                        start_time=s["start_time"],
                        end_time=s["end_time"],
                        score=s.get("score", 1.0),
                        segment_id=s.get("id", f"seg-{i}"),
                    )
                    for i, s in enumerate(segments)
                ]
            else:
                _update_clip_task(task_id, progress=10, phase="original_narration", message="场景检测...")
                scenes = pipeline._detect_scenes(video_paths)
                _update_clip_task(task_id, progress=20, phase="original_narration", message=f"检测到 {len(scenes)} 个场景")

                _update_clip_task(task_id, progress=25, phase="original_narration", message="高光打分...")
                scored = pipeline._score_scenes(scenes)
                _update_clip_task(task_id, progress=35, phase="original_narration", message=f"完成 {len(scored)} 个片段打分")

                _update_clip_task(task_id, progress=40, phase="original_narration", message="选择高光片段...")
                selected = pipeline._select_highlights(scored, target_duration)
                _update_clip_task(task_id, progress=50, phase="original_narration", message=f"选中 {len(selected)} 个高光片段")

            _update_clip_task(task_id, progress=55, phase="original_narration", message="智能排序...")
            sorted_segments = pipeline._sort_segments(selected)
            _update_clip_task(task_id, progress=60, phase="original_narration", message="排序完成")

            _update_clip_task(task_id, progress=65, phase="original_narration", message="正在剪辑拼接...")
            final_path = pipeline._cut_and_concat(sorted_segments, output_path)
            _update_clip_task(task_id, progress=100, phase="completed", message="原片直剪完成", status="completed", output_path=final_path)
            logger.info(f"Clip task {task_id} (original_narration) completed: {final_path}")

        else:
            raise ValueError(f"Unknown clip scheme: {scheme}")

    except Exception as e:
        logger.exception(f"Clip task {task_id} failed: {e}")
        _update_clip_task(task_id, status="failed", progress=-1, phase="error", message=str(e))


def clip_recommend(project_id: str) -> Dict:
    """获取剪辑方案推荐，根据项目视频数量智能推荐"""
    from app.services.project.manager import get_manager

    manager = get_manager()
    videos = manager.get_videos(project_id)
    episode_count = len(videos) if videos else 0

    # 判断剧集类型
    if episode_count == 0:
        episode_type = "unknown"
    elif episode_count == 1:
        episode_type = "single"
    else:
        episode_type = "multi"

    if episode_type == "multi":
        # 多集：优先推荐「全部生成」（三种模式一键三连）和「原片解说」
        recommended_scheme = "all_narrations"
        recommended_modes = ["all_narrations", "original_narration", "hybrid_narration", "full_narration"]
        reasons = [
            f"共 {episode_count} 集视频",
            "对话丰富、情节完整",
            "AI 推荐：一键三连批量输出三种模式对比",
        ]
        alternatives = ["original_narration", "hybrid_narration", "full_narration"]
    elif episode_type == "single":
        # 单集：优先推荐「原片解说」和「全片解说」
        recommended_scheme = "original_narration"
        recommended_modes = ["original_narration", "full_narration", "hybrid_narration"]
        reasons = [
            "单集视频",
            "建议保留原声剪辑或尝试全片 AI 解说",
        ]
        alternatives = ["full_narration", "hybrid_narration"]
    else:
        recommended_scheme = "original_narration"
        recommended_modes = ["original_narration", "hybrid_narration", "full_narration", "all_narrations"]
        reasons = ["请先导入视频"]
        alternatives = []

    return {
        "episode_count": episode_count,
        "episode_type": episode_type,
        "recommended_scheme": recommended_scheme,
        "confidence": 0.92,
        "reasons": reasons,
        "alternatives": alternatives,
        "recommended_modes": recommended_modes,  # 按推荐顺序排列的完整模式列表
    }


def clip_execute(project_id: str, scheme: str, params: Dict[str, Any]) -> Dict:
    """执行剪辑（支持多版本、多尺寸、多模式）"""
    import uuid
    task_id = str(uuid.uuid4())

    # 提取可选的目标时长参数（来自前端滑块）
    target_duration = params.get("output_duration") or params.get("target_duration")
    if target_duration is not None:
        logger.info(f"Clip task {task_id}: scheme={scheme}, target_duration={target_duration}s")
    else:
        logger.info(f"Clip task {task_id}: scheme={scheme}, no duration limit")

    # 提取剪辑模式和输出配置
    clip_mode = params.get("clip_mode", "highlight")       # highlight/transition/narration
    output_size = params.get("output_size", "16:9")        # 16:9/9:16/1:1
    output_quality = params.get("output_quality", "1080p") # 720p/1080p/2K/4K
    num_versions = params.get("num_versions", 1)           # 生成版本数

    # 获取项目的视频路径列表
    mgr = get_manager()
    videos = mgr.get_videos(project_id)
    if not videos:
        raise RPCError(-32002, f"No videos found in project {project_id}")

    video_paths = [v.path for v in videos]
    logger.info(f"Clip task {task_id}: {len(video_paths)} videos, mode={clip_mode}, scheme={scheme}, size={output_size}, quality={output_quality}, versions={num_versions}")

    # 创建输出路径
    from pathlib import Path
    project = mgr.get_project(project_id)
    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")
    output_dir = Path(project.path) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"dramaclip_{task_id[:8]}.mp4")

    # 更新任务状态
    _update_clip_task(
        task_id,
        status="running",
        progress=0,
        phase="preparing",
        message="准备开始...",
        output_config={
            "clip_mode": clip_mode,
            "output_size": output_size,
            "output_quality": output_quality,
            "num_versions": num_versions,
        }
    )

    # 提取预选片段（从编辑面板传入的 segment_ids → 高光片段）
    segments = params.get("segments") or params.get("selected_segments")

    # 用线程池调度剪辑流水线（自动限流为 max_workers 个并发）
    _pool.submit(
        _run_clip_pipeline,
        task_id, scheme, video_paths, target_duration, output_path, num_versions, segments,
    )

    return {
        "task_id": task_id,
        "status": "running",
        "target_duration": target_duration,
    }


def clip_get_progress(task_id: str) -> Dict:
    """获取剪辑进度"""
    with _clip_tasks_lock:
        task = _clip_tasks.get(task_id)
    if not task:
        return {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "phase": "",
            "message": "任务已创建，等待启动...",
        }
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task["progress"],
        "phase": task.get("phase", ""),
        "message": task.get("message", ""),
        "output_path": task.get("output_path"),
    }


def clip_preview(project_id: str, scheme: str) -> Dict:
    """预览剪辑结果"""
    return {"preview_url": "", "ready": False}

# ============================================================================
# 导出
# ============================================================================

def export_start(project_id: str, output_config: Dict[str, Any]) -> Dict:
    """开始导出"""
    import uuid
    task_id = str(uuid.uuid4())
    logger.info(f"Started export task: {task_id}")
    return {
        "task_id": task_id,
        "status": "running"
    }


def export_get_progress(task_id: str) -> Dict:
    """获取导出进度"""
    return {
        "task_id": task_id,
        "status": "running",
        "progress": 0,
        "message": "Exporting..."
    }


# ============================================================================
# 设置
# ============================================================================


def _merge_config_into_settings(settings: Dict) -> None:
    """从 config.toml 的 [app] 段读取 LLM 配置并合并到 settings"""
    try:
        from app.config import config as cfg

        api_key = (
            cfg.app.get("vision_openai_api_key", "")
            or cfg.app.get("text_openai_api_key", "")
        )
        base_url = (
            cfg.app.get("vision_openai_base_url", "")
            or cfg.app.get("text_openai_base_url", "")
        )
        vision_model = cfg.app.get("vision_openai_model_name", "")
        text_model = cfg.app.get("text_openai_model_name", "")

        openai_cfg = settings.setdefault("openai_protocol", {})
        if api_key and not openai_cfg.get("api_key"):
            openai_cfg["api_key"] = api_key
        if base_url and not openai_cfg.get("base_url"):
            openai_cfg["base_url"] = base_url
        if text_model and not openai_cfg.get("model"):
            openai_cfg["model"] = text_model
        openai_cfg.setdefault("max_tokens", 4096)
        openai_cfg.setdefault("temperature", 0.7)
    except Exception:
        logger.warning("Failed to merge config.toml into settings", exc_info=True)


def _sync_settings_to_config(settings: Dict) -> None:
    """将设置中的 LLM API 配置写回 config.toml"""
    try:
        from app.config import config as cfg

        openai_cfg = settings.get("openai_protocol", {})
        api_key = openai_cfg.get("api_key", "")
        base_url = openai_cfg.get("base_url", "")
        model = openai_cfg.get("model", "")

        changed = False
        if api_key:
            cfg.app["vision_openai_api_key"] = api_key
            cfg.app["text_openai_api_key"] = api_key
            changed = True
        if base_url:
            cfg.app["vision_openai_base_url"] = base_url
            cfg.app["text_openai_base_url"] = base_url
            changed = True
        if model:
            cfg.app["vision_openai_model_name"] = model
            cfg.app["text_openai_model_name"] = model
            changed = True

        if changed:
            cfg.save_config()
            logger.info("LLM settings synced to config.toml")
    except Exception:
        logger.warning("Failed to sync settings to config.toml", exc_info=True)


def settings_get() -> Dict:
    """获取设置（从 config.toml 和 settings.json 联合读取）"""
    import json
    from pathlib import Path

    settings_file = Path.home() / ".dramaclip" / "settings.json"
    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding="utf-8"))
            if "openai_protocol" in raw and "output" in raw and "tts" in raw:
                # 从 config.toml 覆盖 LLM key/base_url
                _merge_config_into_settings(raw)
                return raw
            return _upgrade_settings(raw)
        except Exception:
            pass

    settings = _default_settings()
    _merge_config_into_settings(settings)
    return settings


def _default_settings() -> Dict:
    """新版嵌套结构的默认设置"""
    import os
    return {
        "openai_protocol": {
            "api_key": "",
            "base_url": "",
            "model": "gpt-4o",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enabled": True,
        },
        "anthropic_protocol": {
            "api_key": "",
            "base_url": "",
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enabled": False,
        },
        "tts": {
            "enabled": True,
            "engine": "openai",
            "voice": "nova",
            "speed": 1.0,
            "pitch": 1.0,
        },
        "asr": {
            "enabled": True,
            "engine": "whisper",
            "model": "large-v3",
            "language": "auto",
            "translate": False,
        },
        "vit": {
            "enabled": True,
            "provider": "openai_protocol",
            "model": "qwen-vl-max",
            "batch_size": 4,
        },
        "output": {
            "path": str(Path.home() / "DramaClip" / "Outputs"),
            "quality": "1080p",
            "format": "mp4",
            "fps": 30,
            "codec": "h264",
        },
        "hardware": {
            "enabled": True,
            "ffmpeg_hwaccel": "auto",
            "gpu_device": "0",
            "threads": 4,
            "max_workers": 5,
        },
    }


def _upgrade_settings(flat: Dict) -> Dict:
    """将旧版扁平设置升级到新版嵌套结构"""
    defaults = _default_settings()
    result = dict(defaults)

    # 旧版 → 新版字段映射
    MAPPING = {
        "openai_api_key": ("openai_protocol", "api_key"),
        "gemini_api_key": ("anthropic_protocol", "api_key"),  # 旧版 gemini → 新版 anthropic
        "default_output_path": ("output", "path"),
        "default_quality": ("output", "quality"),
        "tts_engine": ("tts", "engine"),
        "voice_name": ("tts", "voice"),
    }

    for old_key, (section, field) in MAPPING.items():
        if old_key in flat and flat[old_key]:
            result[section][field] = flat[old_key]

    # 保存升级后的设置
    try:
        settings_file = Path.home() / ".dramaclip" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass

    return result


def settings_update(settings: Dict[str, Any]) -> Dict:
    """更新设置（同步 LLM 配置到 config.toml）"""
    import json
    from pathlib import Path

    # 同步 LLM API 配置到 config.toml
    _sync_settings_to_config(settings)

    settings_file = Path.home() / ".dramaclip" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info("Settings updated and synced to config.toml")
    return {"success": True}


# ============================================================================
# 系统
# ============================================================================

def system_get_version() -> Dict:
    """获取版本信息"""
    return {
        "version": "1.0.0",
        "name": "DramaClip",
        "build": "desktop",
    }


def system_get_ffmpeg_info() -> Dict:
    """获取 FFmpeg 信息"""
    import shutil
    import subprocess

    # 查找 FFmpeg
    ffmpeg_path = None
    for name in ["ffmpeg", "ffmpeg.exe"]:
        path = shutil.which(name)
        if path:
            ffmpeg_path = path
            break

    if not ffmpeg_path:
        return {"available": False, "version": "", "hwaccel": ""}

    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_line = result.stdout.split("\n")[0]
        return {
            "available": True,
            "version": version_line,
            "hwaccel": "N/A",
        }
    except Exception as e:
        logger.warning(f"Failed to get FFmpeg info: {e}")
        return {"available": True, "version": "unknown", "hwaccel": ""}


# ============================================================================
# 心跳和健康检查
# ============================================================================

def ping(timestamp: int) -> Dict:
    """心跳响应"""
    return {
        "pong": True,
        "server_time": timestamp,
        "uptime": 0
    }


def shutdown(reason: str = "requested") -> Dict:
    """优雅关闭"""
    logger.info(f"Shutdown requested: {reason}")
    _pool.shutdown(wait=True)
    if _server:
        _server.stop()
    # 关闭 stdin 以退出 server.run() 的 for line in sys.stdin 循环
    import sys as _sys
    try:
        _sys.stdin.close()
    except Exception:
        pass
    return {"shutdown": True, "reason": reason}


# ============================================================================
# 模型管理
# ============================================================================

def model_list() -> List[Dict]:
    """列出所有可管理模型及其下载状态"""
    from app.services.model_manager import list_models
    return list_models()


def model_download(model_id: str) -> Dict:
    """开始下载模型（后台执行，进度通过通知推送）"""
    from app.services.model_manager import download_model

    def _progress(pct: int, msg: str):
        if _server:
            _server.send_progress(model_id, pct, msg, phase="download")

    success = download_model(model_id, progress_callback=_progress)
    return {
        "success": success,
        "model_id": model_id,
        "status": "started" if success else "already_downloading",
    }


def model_cancel(model_id: str) -> Dict:
    """取消正在进行的模型下载"""
    from app.services.model_manager import cancel_download
    cancelled = cancel_download(model_id)
    return {"success": cancelled, "model_id": model_id}


def model_delete(model_id: str) -> Dict:
    """删除已下载的模型"""
    from app.services.model_manager import delete_model
    deleted = delete_model(model_id)
    return {"success": deleted, "model_id": model_id}


def model_status(model_id: str) -> Dict:
    """获取模型下载状态"""
    from app.services.model_manager import get_download_status
    return get_download_status(model_id)
