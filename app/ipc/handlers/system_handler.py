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
    try:
        from app.utils.ffmpeg_utils import get_ffmpeg_path
        ffmpeg_path = get_ffmpeg_path()
    except Exception as e:
        logger.warning(f"[System] Failed to import/call get_ffmpeg_path: {e}")
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
    """列出所有可管理模型及其下载状态（包含中央 catalog）"""
    from app.services.model_manager import list_models, list_central_catalog_models
    legacy = list_models()
    central = list_central_catalog_models()
    return {
        "legacy": legacy,
        "central_catalog": central,   # 新增：中央目录 + 统一安装状态（参考项目风格）
    }


def tts_backends_list() -> List[Dict]:
    """列出所有可用的 TTS 引擎及其状态（新插件化系统）"""
    try:
        from app.services.tts.registry import list_available_backends
        return list_available_backends()
    except Exception as e:
        logger.warning(f"Failed to list TTS backends from new system: {e}")
        # Fallback
        return [
            {"id": "edge_tts", "display_name": "Edge TTS (免费稳定备用)", "available": True},
            {"id": "openai_tts", "display_name": "OpenAI Compatible (云端)", "available": True},
            {"id": "cosyvoice", "display_name": "CosyVoice 3 (Fun-CosyVoice3-0.5B)", "available": False, "reason": "使用中央模型目录下载后可用"},
        ]


def model_download(model_id: str) -> Dict:
    """开始下载模型（后台执行，进度通过通知推送）
    
    中央 catalog 条目（repo_id）会走统一的 download_hf_model + hf_progress 结构化进度。
    旧 ID 保持兼容。
    """
    from app.services.model_manager import download_model, get_model_by_repo_id
    from .base import get_server
    from app.utils import hf_progress

    is_central = bool(get_model_by_repo_id(model_id))

    def _progress(pct: int, msg: str):
        if get_server():
            get_server().send_progress(model_id, pct, msg, phase="download")

    # 对于中央 catalog 模型，额外注册富结构化进度监听器（repo_id / phase / bytes）
    listener_id = None
    if is_central:
        hf_progress.ensure_installed()

        def _rich_listener(ev: dict):
            repo = ev.get("repo_id") or model_id
            task = f"model:{repo}"
            pct2 = int(ev.get("pct", 0) * 100) if ev.get("pct") is not None else (pct if 'pct' in locals() else 0)
            phase = ev.get("phase", "download")
            filename = ev.get("filename", "")
            msg2 = filename or ev.get("message") or msg or f"Downloading {repo}"
            if phase == "done":
                msg2 = f"{repo} 下载完成"

            if get_server():
                get_server().send_progress(
                    task,
                    pct2,
                    msg2,
                    phase=phase,
                    detail={
                        "repo_id": repo,
                        "filename": filename,
                        "downloaded": ev.get("downloaded"),
                        "total": ev.get("total"),
                    },
                )

        listener_id = hf_progress.register_listener(_rich_listener)

    try:
        success = download_model(model_id, progress_callback=_progress)
        if not success:
            # 给前端更明确的失败反馈
            if get_server():
                get_server().send_progress(model_id, 0, f"下载启动失败: {model_id}", phase="error")
    finally:
        if listener_id is not None:
            import threading
            def _delayed_unregister():
                import time
                time.sleep(2)
                hf_progress.unregister_listener(listener_id)
            threading.Thread(target=_delayed_unregister, daemon=True).start()

    return {
        "success": success,
        "model_id": model_id,
        "status": "started" if success else "failed",
        "is_central_catalog": is_central,
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


# ── Phase 3.1: CosyVoice 隔离运行时安装（一键让高质量本地 TTS 真正可用） ─────

def cosyvoice_install_runtime() -> Dict:
    """
    一键安装 CosyVoice 隔离运行时。
    会在后台创建专属 venv、clone 源码、安装依赖，并通过进度通知反馈。
    """
    from app.services.tts.engines.cosyvoice.backend import install_cosyvoice_isolated_runtime
    from .base import get_server

    task_id = "cosyvoice:install_runtime"

    def _progress(pct: int, msg: str):
        if get_server():
            get_server().send_progress(task_id, pct, msg, phase="install")

    try:
        success = install_cosyvoice_isolated_runtime(progress_callback=_progress)
        if success:
            # 强制让 registry 重新评估可用性
            from app.services.tts.registry import _LAST_ERRORS
            _LAST_ERRORS.pop("cosyvoice_subprocess", None)
        return {
            "success": success,
            "message": "安装成功" if success else "安装失败，请查看进度日志或手动安装"
        }
    except Exception as e:
        logger.error(f"CosyVoice runtime install failed: {e}")
        return {"success": False, "message": str(e)}


# ── Phase 4: Onboarding & Quality Packs ─────────────────────────────────────

def get_onboarding_recommendations() -> Dict:
    """获取首次使用推荐套装 + 硬件建议"""
    from app.services.onboarding import (
        get_recommended_packs,
        get_hardware_recommendation,
        is_first_run,
    )
    return {
        "is_first_run": is_first_run(),
        "recommended_pack_id": get_hardware_recommendation(),
        "packs": get_recommended_packs(),
    }


def apply_onboarding_pack(pack_id: str) -> Dict:
    """应用推荐套装（切换默认引擎等）"""
    from app.services.onboarding import apply_recommended_pack
    success = apply_recommended_pack(pack_id)
    return {"success": success}
