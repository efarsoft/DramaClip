"""
系统 Handler
处理系统信息和模型管理
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from loguru import logger

from .base import get_server, get_worker_pool
from app.ipc.protocol import RPCError


def _get_dir_size(path: Path) -> int:
    """递归获取目录大小"""
    if not path.exists():
        return 0
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _get_dir_size(Path(entry.path))
    except (PermissionError, OSError):
        pass
    return total


def system_get_storage_info() -> Dict:
    """获取存储信息
    
    Returns:
        包含输出目录、缓存、临时文件等存储统计信息
    """
    dramaclip_dir = Path.home() / ".dramaclip"
    outputs_dir = dramaclip_dir / "Outputs"
    cache_dir = dramaclip_dir / "cache"
    temp_dir = dramaclip_dir / "temp"
    
    outputs_size = _get_dir_size(outputs_dir)
    cache_size = _get_dir_size(cache_dir)
    temp_size = _get_dir_size(temp_dir)
    
    outputs_count = 0
    if outputs_dir.exists():
        try:
            outputs_count = len(list(outputs_dir.glob("*.mp4"))) + \
                           len(list(outputs_dir.glob("*.mkv"))) + \
                           len(list(outputs_dir.glob("*.mov")))
        except (PermissionError, OSError):
            pass
    
    return {
        "outputsDir": str(outputs_dir),
        "outputsCount": outputs_count,
        "outputsSize": outputs_size,
        "cacheSize": cache_size,
        "tempSize": temp_size,
        "totalSize": outputs_size + cache_size + temp_size,
    }


def system_get_version() -> Dict:
    """获取版本信息"""
    return {
        "version": "1.0.0",
        "name": "DramaClip",
        "build": "desktop",
    }


def system_get_ffmpeg_info() -> Dict:
    """获取 FFmpeg 信息"""
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
        logger.warning(f"[System] Failed to get FFmpeg info: {e}")
        return {"available": True, "version": "unknown", "hwaccel": ""}


def ping(timestamp: int) -> Dict:
    """心跳响应"""
    return {
        "pong": True,
        "server_time": timestamp,
        "uptime": 0
    }


def shutdown(reason: str = "requested") -> Dict:
    """优雅关闭"""
    logger.info(f"[System] Shutdown requested: {reason}")
    get_worker_pool().shutdown(wait=True)
    if get_server():
        get_server().stop()
    try:
        sys.stdin.close()
    except Exception:
        pass
    return {"shutdown": True, "reason": reason}


def model_list() -> List[Dict]:
    """列出所有可管理模型及其下载状态"""
    from app.services.model_manager import list_models
    return list_models()


def model_download(model_id: str) -> Dict:
    """开始下载模型（后台执行，进度通过通知推送）"""
    from app.services.model_manager import download_model
    from .base import get_server

    def _progress(pct: int, msg: str):
        if get_server():
            get_server().send_progress(model_id, pct, msg, phase="download")

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
