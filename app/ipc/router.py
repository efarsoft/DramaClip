"""
方法路由与分发
P0 收尾：采用显式导入，依赖清晰、可维护性更高
"""

from typing import Any, Callable, Dict, Optional
from loguru import logger

# ==================== 显式导入各个 Handler ====================

# Project
from app.ipc.handlers.project_handler import (
    project_list,
    project_create,
    project_open,
    project_delete,
    project_rename,
    project_import_videos,
    project_get_videos,
    project_update_video_order,
)

# Analyze
from app.ipc.handlers.analyze_handler import (
    analyze_start,
    analyze_get_status,
    analyze_cancel,
)

# Clip
from app.ipc.handlers.clip_handler import (
    clip_recommend,
    clip_execute,
    clip_get_progress,
    clip_preview,
    clip_stop,
    clip_generate_title,
)

# Export
from app.ipc.handlers.export_handler import (
    export_start,
    export_get_progress,
    export_cancel,
)

# Settings
from app.ipc.handlers.settings_handler import (
    settings_get,
    settings_update,
)

# Tools
from app.ipc.handlers.tools_handler import (
    tools_transcribe,
    tools_get_progress,
    tools_rewrite,
)

# System & Model
from app.ipc.handlers.system_handler import (
    system_get_version,
    system_get_ffmpeg_info,
    system_get_storage_info,
    ping,
    shutdown,
    model_list,
    model_download,
    model_cancel,
    model_delete,
    model_status,
)


class Router:
    """
    RPC 方法路由器
    将 namespace.method 路由到对应的处理函数
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    def register(
        self,
        namespace: str,
        method: str,
        handler: Callable
    ):
        """
        注册处理函数

        Args:
            namespace: 命名空间，如 "project", "analyze"
            method: 方法名，如 "list", "create"
            handler: 处理函数
        """
        full_name = f"{namespace}.{method}"
        self._handlers[full_name] = handler
        logger.debug(f"Registered RPC handler: {full_name}")

    def resolve(self, full_name: str) -> Optional[Callable]:
        """解析方法名到处理函数"""
        return self._handlers.get(full_name)

    def list_methods(self) -> list:
        """列出所有已注册的方法"""
        return list(self._handlers.keys())

    def unregister(self, namespace: str, method: str):
        """取消注册"""
        full_name = f"{namespace}.{method}"
        self._handlers.pop(full_name, None)


def create_router() -> Router:
    """创建路由并注册所有处理函数"""
    router = Router()

    # ==================== 项目管理 ====================
    router.register("project", "list", project_list)
    router.register("project", "create", project_create)
    router.register("project", "open", project_open)
    router.register("project", "delete", project_delete)
    router.register("project", "importVideos", project_import_videos)
    router.register("project", "getVideos", project_get_videos)
    router.register("project", "updateVideoOrder", project_update_video_order)
    router.register("project", "rename", project_rename)

    # ==================== 分析 ====================
    router.register("analyze", "start", analyze_start)
    router.register("analyze", "getStatus", analyze_get_status)
    router.register("analyze", "cancel", analyze_cancel)

    # ==================== 剪辑 ====================
    router.register("clip", "recommend", clip_recommend)
    router.register("clip", "execute", clip_execute)
    router.register("clip", "getProgress", clip_get_progress)
    router.register("clip", "preview", clip_preview)
    router.register("clip", "stop", clip_stop)
    router.register("clip", "generateTitle", clip_generate_title)

    # ==================== 导出 ====================
    router.register("export", "start", export_start)
    router.register("export", "getProgress", export_get_progress)
    router.register("export", "cancel", export_cancel)

    # ==================== 设置 ====================
    router.register("settings", "get", settings_get)
    router.register("settings", "update", settings_update)

    # ==================== 小工具 ====================
    router.register("tools", "transcribe", tools_transcribe)
    router.register("tools", "getProgress", tools_get_progress)
    router.register("tools", "rewrite", tools_rewrite)

    # ==================== 系统 ====================
    router.register("system", "getVersion", system_get_version)
    router.register("system", "getFFmpegInfo", system_get_ffmpeg_info)
    router.register("system", "getStorageInfo", system_get_storage_info)

    # 心跳和健康检查（无命名空间）
    router.register("system", "ping", ping)
    router.register("system", "shutdown", shutdown)

    # ==================== 模型管理 ====================
    router.register("model", "list", model_list)
    router.register("model", "download", model_download)
    router.register("model", "cancel", model_cancel)
    router.register("model", "delete", model_delete)
    router.register("model", "status", model_status)

    return router
