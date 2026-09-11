"""统一任务状态机（进度推送与崩溃重入依据，docs/service/03 第 3 节）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

# 两个非终态值的唯一拼写源：写 pending 的是 create，写 running 的是 mark_running；
# 比它们的是启动清扫的 SQL（两者同为崩溃残留）与 api/models.py 的下载看门狗（只认
# running 才收尾）。三处必须同值——看门狗据此判断该不该收尾，启动清扫据此判定哪些是
# 崩溃残留；拼写一分家就退回「任务永停某个非终态且重启也清不掉」那个假状态。
# 写入侧一并命名，否则常量就成了没人写的孤立值（同 exports.py 的 STATUS_PENDING）。
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"


def is_terminal(status: str) -> bool:
    """是否终态：终态任务不可再迁移，也不可再取消。上层据此判断，勿各写字面量。"""
    return status in _TERMINAL_STATUSES


def _now_ms() -> int:
    return int(time.time() * 1000)


class JobStore:
    """jobs 表仓储：创建、状态迁移、进度更新、启动清扫。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, job_type: str, ref_id: str | None = None) -> str:
        job_id = uuid4().hex
        now = _now_ms()
        self._conn.execute(
            "INSERT INTO jobs (id, type, ref_id, status, progress, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 0, ?, ?)",
            (job_id, job_type, ref_id, STATUS_PENDING, now, now),
        )
        self._conn.commit()
        return job_id

    def mark_running(self, job_id: str) -> None:
        self._transition(job_id, STATUS_RUNNING)

    def mark_completed(self, job_id: str) -> None:
        self._transition(job_id, "completed")

    def mark_failed(self, job_id: str, error: str) -> None:
        self._transition(job_id, "failed", error=error)

    def mark_cancelled(self, job_id: str) -> None:
        self._transition(job_id, "cancelled")

    def set_progress(self, job_id: str, percent: float, label: str | None = None) -> None:
        """更新进度；label 为队列页要显示的人读阶段（如「第3集 预筛中」）。"""
        if label is None:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (percent, _now_ms(), job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, label = ?, updated_at = ? WHERE id = ?",
                (percent, label, _now_ms(), job_id),
            )
        self._conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, type, ref_id, status, progress, label, error, created_at, updated_at"
            " FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        keys = (
            "id", "type", "ref_id", "status", "progress",
            "label", "error", "created_at", "updated_at",
        )
        return dict(zip(keys, row, strict=True))

    _LIST_COLUMNS = (
        "id", "type", "ref_id", "status", "progress", "label", "error", "created_at", "updated_at",
    )

    def list_recent(self, *, limit: int = 50, active_only: bool = False) -> list[dict[str, Any]]:
        """队列页数据源：按最近变更倒序取任务，可只要未终态。

        排序补 `created_at, id` 兜底：`updated_at` 为毫秒精度，同毫秒内变更的任务
        否则顺序随机，队列页每次刷新可能跳行。
        过滤用 NOT IN(终态集) 而非 IN(活跃集)：将来新增非终态状态时不会静默消失。
        """
        where = ""
        params: tuple[Any, ...] = (limit,)
        if active_only:
            placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
            where = f" WHERE status NOT IN ({placeholders})"
            params = (*sorted(_TERMINAL_STATUSES), limit)
        rows = self._conn.execute(
            f"SELECT {', '.join(self._LIST_COLUMNS)} FROM jobs{where}"
            " ORDER BY updated_at DESC, created_at DESC, id LIMIT ?",
            params,
        ).fetchall()
        return [dict(zip(self._LIST_COLUMNS, row, strict=True)) for row in rows]

    def sweep_interrupted(self) -> int:
        """启动清扫：上一会话遗留的 running / pending 任务标记失败（崩溃重入协议）。

        无服务运行即无任务在飞，故 pending 与 running 同一条理由成立：`executor.submit`
        不挂 done-callback，入队而 worker 始终没跑起来的行原本会永远停在 pending，
        队列页挂着一只永不推进的任务。与 `exports.reset_stale_pending` 同构——
        认非终态即复位，终态行不动，进度保留原值，两表不得互相矛盾。
        """
        cursor = self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = '服务中断', updated_at = ?"
            " WHERE status IN (?, ?)",
            (_now_ms(), STATUS_PENDING, STATUS_RUNNING),
        )
        self._conn.commit()
        return cursor.rowcount or 0

    def _transition(self, job_id: str, status: str, error: str | None = None) -> None:
        current = self.get(job_id)
        if current is None:
            raise ValueError(f"任务不存在: {job_id}")
        if current["status"] in _TERMINAL_STATUSES:
            raise ValueError(f"任务已终态({current['status']}), 不可迁移: {job_id}")
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now_ms(), job_id),
        )
        self._conn.commit()
