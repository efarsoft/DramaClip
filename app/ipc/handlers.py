"""
IPC 处理函数实现
使用 app/services/ 下的服务实现核心逻辑
"""

import asyncio
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from app.services.project.manager import get_manager, ProjectManager
from app.services.analyze.manager import get_analysis_manager
from .protocol import RPCError

# Server reference for sending progress notifications
_server = None  # type: ignore


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
    """列出所有项目"""
    manager = get_manager()
    projects = manager.list_projects()
    logger.debug(f"Listed {len(projects)} projects")
    return [p.to_dict() for p in projects]


def project_create(name: str, path: str) -> Dict:
    """创建新项目"""
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
    """打开项目"""
    manager = get_manager()
    project = manager.open_project(project_id)

    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"Opened project: {project_id}")
    return project.to_dict()


def project_delete(project_id: str, keep_files: bool = False) -> Dict:
    """删除项目"""
    manager = get_manager()
    success = manager.delete_project(project_id, keep_files)

    if not success:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"Deleted project: {project_id}")
    return {"success": True}


def project_rename(project_id: str, new_name: str) -> Dict:
    """重命名项目"""
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
    if not paths:
        return []

    manager = get_manager()
    videos = manager.import_videos(project_id, paths)
    logger.info(f"Imported {len(videos)} videos to project {project_id}")
    return [v.to_dict() for v in videos]


def project_get_videos(project_id: str) -> List[Dict]:
    """获取项目的视频列表"""
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
    """开始视频分析（支持多集）"""
    if not episode_ids:
        raise RPCError(-32602, "episode_ids is required")

    mgr = get_manager()
    analysis_mgr = get_analysis_manager()

    task_ids = []
    for idx, episode_id in enumerate(episode_ids):
        # 获取视频路径
        videos = mgr.get_videos(project_id)
        video = next((v for v in videos if v.id == episode_id), None)
        if not video:
            raise RPCError(-32002, f"Episode not found: {episode_id}")

        # 创建分析任务
        task = analysis_mgr.create_task(project_id, video.path)
        task_ids.append(task.task_id)

        # 在后台线程中运行分析
        thread = threading.Thread(
            target=_run_async_analysis,
            args=(analysis_mgr, task.task_id),
            daemon=True,
        )
        thread.start()

    logger.info(f"Started {len(task_ids)} analysis tasks for project {project_id}")
    return {
        "task_id": task_ids[0],  # 返回第一个任务的 task_id，保持前端兼容
        "task_ids": task_ids,     # 附带所有任务 ID
        "status": "started",
        "count": len(task_ids),
        "message": f"Started {len(task_ids)} analysis tasks",
    }


def analyze_get_status(task_id: str) -> Dict:
    """获取分析状态"""
    analysis_mgr = get_analysis_manager()
    task = analysis_mgr.get_task(task_id)
    if not task:
        raise RPCError(-32002, f"Task not found: {task_id}")

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "phase": task.phase,
        "message": task.message,
        "results": {
            "asr": task.asr_result,
            "emotion": task.emotion_result,
            "highlights": task.highlight_segments,
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

def clip_recommend(project_id: str) -> Dict:
    """获取剪辑方案推荐"""
    return {
        "recommended_scheme": "original_narration",
        "confidence": 0.92,
        "reasons": ["多集视频", "对话丰富", "情绪波动大"],
        "alternatives": ["hybrid_narration", "full_narration"]
    }


def clip_execute(project_id: str, scheme: str, params: Dict[str, Any]) -> Dict:
    """执行剪辑"""
    import uuid
    task_id = str(uuid.uuid4())

    # 提取可选的目标时长参数（来自前端滑块）
    target_duration = params.get("output_duration") or params.get("target_duration")
    if target_duration is not None:
        logger.info(f"Clip task {task_id}: scheme={scheme}, target_duration={target_duration}s")
    else:
        logger.info(f"Clip task {task_id}: scheme={scheme}, no duration limit")

    # TODO: 启动后台线程运行实际 pipeline，传入 target_duration
    return {
        "task_id": task_id,
        "status": "running",
        "target_duration": target_duration,
    }


def clip_get_progress(task_id: str) -> Dict:
    """获取剪辑进度"""
    return {
        "task_id": task_id,
        "status": "running",
        "progress": 0,
        "message": "Preparing clips..."
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
        "translator": {
            "enabled": True,
            "provider": "openai_protocol",
            "source_lang": "zh",
            "target_lang": "en",
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
    return {"shutdown": True, "reason": reason}
