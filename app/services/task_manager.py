"""
任务管理器
P1 重构：统一管理所有任务，支持真正的取消机制

改进点：
1. 移除全局 dict + Lock，改用 TaskManager 类
2. 任务生命周期管理（创建 → 运行 → 完成/取消）
3. 真正的进程终止（不仅仅是状态变更）
4. 超时和自动清理
"""

import uuid
import time
import signal
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import threading
import queue
from loguru import logger


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    phase: str = ""
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    output_path: Optional[str] = None
    process: Optional[Any] = None  # subprocess.Popen
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> Optional[float]:
        """运行时长（秒）"""
        if self.started_at:
            end = self.completed_at or time.time()
            return end - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "phase": self.phase,
            "message": self.message,
            "error": self.error,
            "output_path": self.output_path,
            "result": self.result,
            "duration": self.duration,
        }


class TaskManager:
    """
    统一任务管理器

    设计原则：
    1. 线程安全 - 所有操作加锁
    2. 生命周期管理 - 创建 → 运行 → 完成/取消
    3. 资源追踪 - 跟踪进程、文件等资源
    4. 自动清理 - 超时和完成时清理资源
    """

    def __init__(self, max_concurrent: int = 3, default_timeout: int = 3600):
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = threading.RLock()
        self._max_concurrent = max_concurrent
        self._default_timeout = default_timeout
        self._semaphore = threading.Semaphore(max_concurrent)
        self._task_queue: queue.Queue = queue.Queue()
        self._running_count = 0
        self._running_lock = threading.Lock()

    def create_task(
        self,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建任务

        Args:
            task_id: 任务ID（可选，默认自动生成）
            metadata: 任务元数据

        Returns:
            任务ID
        """
        with self._lock:
            if task_id is None:
                task_id = str(uuid.uuid4())

            if task_id in self._tasks:
                logger.warning(f"[TaskManager] Task {task_id} already exists")
                return task_id

            self._tasks[task_id] = TaskInfo(
                task_id=task_id,
                metadata=metadata or {}
            )

            logger.info(f"[TaskManager] Created task: {task_id}")
            return task_id

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        phase: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        output_path: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        process: Any = None,
    ) -> bool:
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度 0-100
            phase: 当前阶段
            message: 状态消息
            error: 错误信息
            output_path: 输出文件路径
            result: 任务结果
            process: 关联的进程对象

        Returns:
            是否更新成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if status is not None:
                task.status = status

                if status == TaskStatus.RUNNING and task.started_at is None:
                    task.started_at = time.time()

                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task.completed_at = time.time()

                    # 任务完成时减少运行计数
                    with self._running_lock:
                        if self._running_count > 0:
                            self._running_count -= 1
                            self._semaphore.release()

            if progress is not None:
                task.progress = max(0, min(100, progress))

            if phase is not None:
                task.phase = phase

            if message is not None:
                task.message = message

            if error is not None:
                task.error = error

            if output_path is not None:
                task.output_path = output_path

            if result is not None:
                task.result = result

            if process is not None:
                task.process = process

            return True

    def start_task(self, task_id: str) -> bool:
        """
        启动任务（获取运行许可）

        Args:
            task_id: 任务ID

        Returns:
            是否成功启动（可能因并发限制而失败）
        """
        # 先尝试获取信号量
        acquired = self._semaphore.acquire(blocking=False)

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                if acquired:
                    self._semaphore.release()
                return False

            if not acquired:
                # 并发数已满
                logger.warning(f"[TaskManager] Concurrent limit reached, task {task_id} queued")
                return False

            # 更新状态
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            with self._running_lock:
                self._running_count += 1

            logger.info(f"[TaskManager] Started task: {task_id}")
            return True

    def cancel_task(self, task_id: str, force: bool = False) -> bool:
        """
        取消任务

        P1 改进：真正的进程终止

        Args:
            task_id: 任务ID
            force: 是否强制终止（发送 SIGKILL）

        Returns:
            是否取消成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            # 如果任务正在运行，终止进程
            if task.process and hasattr(task.process, 'terminate'):
                try:
                    # 先尝试优雅终止
                    task.process.terminate()

                    # 等待最多5秒
                    try:
                        task.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if force:
                            # 强制杀死
                            task.process.kill()
                            task.process.wait()
                            logger.warning(f"[TaskManager] Force killed task: {task_id}")
                        else:
                            logger.warning(f"[TaskManager] Task {task_id} did not terminate gracefully")
                            return False

                except Exception as e:
                    logger.error(f"[TaskManager] Failed to terminate process: {e}")
                    return False

            # 更新状态
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            task.message = "用户取消"

            # 释放信号量
            with self._running_lock:
                if self._running_count > 0:
                    self._running_count -= 1
                    self._semaphore.release()

            logger.info(f"[TaskManager] Cancelled task: {task_id}")
            return True

    def complete_task(
        self,
        task_id: str,
        result: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> bool:
        """
        标记任务完成

        Args:
            task_id: 任务ID
            result: 任务结果
            output_path: 输出文件路径

        Returns:
            是否成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.progress = 100
            task.message = "任务完成"

            if result is not None:
                task.result = result

            if output_path is not None:
                task.output_path = output_path

            # 释放信号量
            with self._running_lock:
                if self._running_count > 0:
                    self._running_count -= 1
                    self._semaphore.release()

            logger.info(f"[TaskManager] Completed task: {task_id}")
            return True

    def fail_task(self, task_id: str, error: str) -> bool:
        """
        标记任务失败

        Args:
            task_id: 任务ID
            error: 错误信息

        Returns:
            是否成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            task.error = error
            task.message = f"任务失败: {error}"

            # 释放信号量
            with self._running_lock:
                if self._running_count > 0:
                    self._running_count -= 1
                    self._semaphore.release()

            logger.error(f"[TaskManager] Failed task: {task_id}, error: {error}")
            return True

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list:
        """
        列出任务

        Args:
            status: 过滤状态
            limit: 返回数量限制

        Returns:
            任务列表
        """
        with self._lock:
            tasks = list(self._tasks.values())

            if status:
                tasks = [t for t in tasks if t.status == status]

            # 按创建时间倒序
            tasks.sort(key=lambda t: t.created_at, reverse=True)

            return [t.to_dict() for t in tasks[:limit]]

    def get_running_count(self) -> int:
        """获取当前运行的任务数"""
        with self._running_lock:
            return self._running_count

    def cleanup_completed(self, max_age_hours: int = 24) -> int:
        """
        清理已完成的任务

        Args:
            max_age_hours: 保留时间（小时）

        Returns:
            清理的任务数量
        """
        with self._lock:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            to_remove = []

            for task_id, task in self._tasks.items():
                if task.completed_at and (current_time - task.completed_at) > max_age_seconds:
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]

            if to_remove:
                logger.info(f"[TaskManager] Cleaned up {len(to_remove)} old tasks")

            return len(to_remove)


# 全局单例
_global_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """获取全局任务管理器"""
    global _global_task_manager
    if _global_task_manager is None:
        _global_task_manager = TaskManager()
    return _global_task_manager
