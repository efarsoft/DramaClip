"""
IPC Handler 共享基础设施
P1 重构：使用 TaskManager 替代全局 dict + Lock

提供全局状态、工具函数和类型定义
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from loguru import logger

from app.services.task_manager import (
    get_task_manager,
    TaskStatus,
)
from app.services.project.manager_sqlite import get_manager
from app.services.analyze.manager import get_analysis_manager


# Server reference for sending progress notifications
_server = None


# Worker pool for async tasks - 从 UnifiedConfig 读取配置
def _get_worker_count() -> int:
    """从 UnifiedConfig 读取 max_workers 配置，默认值为 5"""
    try:
        from app.config.unified_config import get_config
        config = get_config()
        return config.get("hardware.max_workers", 5)
    except Exception:
        return 5


WORKER_COUNT = _get_worker_count()
_pool = ThreadPoolExecutor(max_workers=WORKER_COUNT, thread_name_prefix="work")
logger.info(f"[Base] Worker pool initialized with {WORKER_COUNT} workers")


def set_server(server) -> None:
    """设置 IPC server 实例（由 backend_main.py 调用）"""
    global _server
    _server = server


def get_server():
    """获取 IPC server 实例"""
    return _server


def get_worker_pool() -> ThreadPoolExecutor:
    """获取 Worker pool 实例"""
    return _pool


def send_progress(
    task_id: str,
    progress: int,
    message: str,
    phase: Optional[str] = None,
    detail: Optional[dict] = None
) -> None:
    """通过 event_bus 发送进度通知（解耦 IPC server 依赖）"""
    from app.core import event_bus
    payload = {"task_id": task_id, "progress": progress, "message": message}
    if phase:
        payload["phase"] = phase
    if detail:
        payload["detail"] = detail
    event_bus.emit("progress", payload)


def update_task(
    task_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    phase: Optional[str] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    output_path: Optional[str] = None,
    project_id: Optional[str] = None,
    task_kind: str = "Task",
    **kwargs
) -> None:
    """
    线程安全地更新任务状态（通用实现）

    合并原 update_clip_task / update_export_task，消除重复代码。
    """
    task_mgr = get_task_manager()

    task_info = task_mgr.get_task(task_id)
    if not task_info:
        task_mgr.create_task(task_id)
        task_info = task_mgr.get_task(task_id)

    if project_id:
        task_info.metadata["project_id"] = project_id

    # 转换状态字符串
    task_status = None
    if status:
        status_map = {
            "pending": TaskStatus.PENDING,
            "running": TaskStatus.RUNNING,
            "completed": TaskStatus.COMPLETED,
            "failed": TaskStatus.FAILED,
            "cancelled": TaskStatus.CANCELLED,
            "timeout": TaskStatus.TIMEOUT,
        }
        task_status = status_map.get(status, TaskStatus.RUNNING)

    task_mgr.update_task(
        task_id,
        status=task_status,
        progress=progress,
        phase=phase,
        message=message,
        error=error,
        output_path=output_path,
    )

    # 任务结束时自动重置项目状态为 ready
    if status in ("completed", "failed", "cancelled", "timeout"):
        pid = project_id or task_info.metadata.get("project_id")
        if pid:
            try:
                from app.services.project.manager_sqlite import get_manager
                mgr = get_manager()
                mgr.update_project(pid, {"status": "ready"})
                logger.info(f"[Base] {task_kind} {task_id} transitioned to {status}. Project {pid} status updated to 'ready'")
            except Exception as e:
                logger.error(f"[Base] Failed to update project status: {e}")

    # 发送 IPC 通知
    if message:
        send_progress(task_id, progress or 0, message, phase)


# 向后兼容别名
update_clip_task = update_task
update_export_task = update_task


def get_task_info(task_id: str) -> Optional[dict]:
    """
    获取任务状态（通用实现，线程安全）
    """
    task_mgr = get_task_manager()
    task_info = task_mgr.get_task(task_id)

    if not task_info:
        return None

    return task_info.to_dict()


# 向后兼容别名
get_clip_task = get_task_info
get_export_task = get_task_info


# 保留旧的常量，保持向后兼容
RESOLUTION_MAP = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

BITRATE_MAP = {
    "480p": "2M",
    "720p": "5M",
    "1080p": "8M",
    "4k": "20M",
}
