"""
DramaClip 任务状态管理（SQLite 持久化 + 内存缓存）

参考 OmniVoice-Studio 的 TaskManager + job_store 模式：
- 每次状态变更同时写入内存缓存和 SQLite
- 进程崩溃后可从 SQLite 恢复
- 启动时自动清扫孤儿任务
"""

import ast
from typing import Any, Dict, Optional
from loguru import logger

from app.models import const
from app.core.job_store import get_job_store
from app.core import event_bus


class PersistentState:
    """
    SQLite 持久化 + 内存缓存的任务状态管理

    - 写入时：先写 SQLite，再更新内存缓存
    - 读取时：优先从内存缓存读取，缓存未命中则查 SQLite
    - 崩溃恢复：启动时从 SQLite 清扫孤儿任务
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._store = get_job_store()

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        """更新任务状态（持久化 + 缓存）"""
        progress = min(int(progress), 100)

        # 更新内存缓存
        self._cache[task_id] = {
            "state": state,
            "progress": progress,
            **kwargs,
        }

        # 通过事件总线广播状态变更
        event_bus.emit("task_status", {
            "task_id": task_id,
            "state": state,
            "progress": progress,
        })

        # 同步到 SQLite（容错：磁盘写入失败不阻塞主流程）
        try:
            job = self._store.get(task_id)
            if job is None:
                # 首次写入，创建记录
                self._store.create(
                    task_id,
                    job_type=kwargs.get("task_type", "unknown"),
                    project_id=kwargs.get("project_id"),
                    meta=kwargs.get("meta"),
                )

            # 映射状态常量到 SQLite 状态字符串
            status_map = {
                const.TASK_STATE_PROCESSING: "running",
                const.TASK_STATE_COMPLETE: "done",
                const.TASK_STATE_FAILED: "failed",
            }
            sqlite_status = status_map.get(state)
            if sqlite_status == "running":
                self._store.mark_running(task_id)
            elif sqlite_status == "done":
                self._store.mark_done(task_id)
            elif sqlite_status == "failed":
                error = kwargs.get("error", "未知错误")
                self._store.mark_failed(task_id, str(error))

            # 记录事件（状态变更日志）
            import json
            event = json.dumps({
                "type": "status",
                "state": state,
                "progress": progress,
                **{k: str(v) for k, v in kwargs.items() if k not in ("error",)},
            }, ensure_ascii=False)
            self._store.append_event(task_id, f"data: {event}\n\n")

        except Exception as e:
            logger.warning(f"[State] SQLite 持久化失败（非致命）: {e}")

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态（优先缓存，降级 SQLite）"""
        # 优先内存缓存
        cached = self._cache.get(task_id)
        if cached is not None:
            return cached

        # 降级到 SQLite
        try:
            job = self._store.get(task_id)
            if job:
                # 反向映射 SQLite 状态到常量
                status_map = {
                    "pending": const.TASK_STATE_PROCESSING,
                    "running": const.TASK_STATE_PROCESSING,
                    "done": const.TASK_STATE_COMPLETE,
                    "failed": const.TASK_STATE_FAILED,
                    "cancelled": const.TASK_STATE_FAILED,
                }
                result = {
                    "state": status_map.get(job.get("status", ""), const.TASK_STATE_PROCESSING),
                    "progress": 100 if job.get("status") == "done" else 0,
                }
                if job.get("error"):
                    result["error"] = job["error"]
                # 写入缓存
                self._cache[task_id] = result
                return result
        except Exception as e:
            logger.warning(f"[State] SQLite 查询失败: {e}")

        return None

    def delete_task(self, task_id: str):
        """删除任务"""
        self._cache.pop(task_id, None)
        try:
            self._store.delete(task_id)
        except Exception:
            pass

    def sweep_orphans(self) -> int:
        """启动时清扫孤儿任务"""
        n = self._store.sweep_orphans_on_startup()
        # 清空内存缓存（刚启动时应该是空的）
        self._cache.clear()
        return n


# ---- 向后兼容：保留旧接口名 ----

class MemoryState:
    """纯内存状态管理（已废弃，保留向后兼容）"""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def update_task(self, task_id: str, state: int = const.TASK_STATE_PROCESSING,
                    progress: int = 0, **kwargs):
        progress = min(int(progress), 100)
        self._tasks[task_id] = {"state": state, "progress": progress, **kwargs}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def delete_task(self, task_id: str):
        self._tasks.pop(task_id, None)


# 全局状态实例（默认使用持久化版本）
state = PersistentState()
