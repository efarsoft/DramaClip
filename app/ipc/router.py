"""
方法路由与分发
"""

from typing import Any, Callable, Dict, Optional
from loguru import logger


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
    from app.ipc import handlers
    router = Router()

    # 项目管理
    router.register("project", "list", handlers.project_list)
    router.register("project", "create", handlers.project_create)
    router.register("project", "open", handlers.project_open)
    router.register("project", "delete", handlers.project_delete)
    router.register("project", "importVideos", handlers.project_import_videos)
    router.register("project", "getVideos", handlers.project_get_videos)
    router.register("project", "rename", handlers.project_rename)

    # 分析
    router.register("analyze", "start", handlers.analyze_start)
    router.register("analyze", "getStatus", handlers.analyze_get_status)
    router.register("analyze", "cancel", handlers.analyze_cancel)

    # 剪辑
    router.register("clip", "recommend", handlers.clip_recommend)
    router.register("clip", "execute", handlers.clip_execute)
    router.register("clip", "getProgress", handlers.clip_get_progress)
    router.register("clip", "preview", handlers.clip_preview)

    # 导出
    router.register("export", "start", handlers.export_start)
    router.register("export", "getProgress", handlers.export_get_progress)

    # 设置
    router.register("settings", "get", handlers.settings_get)
    router.register("settings", "update", handlers.settings_update)

    # 系统
    router.register("system", "getVersion", handlers.system_get_version)
    router.register("system", "getFFmpegInfo", handlers.system_get_ffmpeg_info)

    # 心跳和健康检查（无命名空间）
    router.register("system", "ping", handlers.ping)
    router.register("system", "shutdown", handlers.shutdown)

    # 模型管理
    router.register("model", "list", handlers.model_list)
    router.register("model", "download", handlers.model_download)
    router.register("model", "cancel", handlers.model_cancel)
    router.register("model", "delete", handlers.model_delete)
    router.register("model", "status", handlers.model_status)

    return router
