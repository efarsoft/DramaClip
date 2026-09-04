"""统一任务状态机（进度推送与崩溃重入依据，docs/service/03 第 3 节）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


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
            " VALUES (?, ?, ?, 'pending', 0, ?, ?)",
            (job_id, job_type, ref_id, now, now),
        )
        self._conn.commit()
        return job_id

    def mark_running(self, job_id: str) -> None:
        self._transition(job_id, "running")

    def mark_completed(self, job_id: str) -> None:
        self._transition(job_id, "completed")

    def mark_failed(self, job_id: str, error: str) -> None:
        self._transition(job_id, "failed", error=error)

    def mark_cancelled(self, job_id: str) -> None:
        self._transition(job_id, "cancelled")

    def set_progress(self, job_id: str, percent: float) -> None:
        self._conn.execute(
            "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
            (percent, _now_ms(), job_id),
        )
        self._conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, type, ref_id, status, progress, error, created_at, updated_at"
            " FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        keys = ("id", "type", "ref_id", "status", "progress", "error", "created_at", "updated_at")
        return dict(zip(keys, row, strict=True))

    def sweep_interrupted(self) -> int:
        """启动清扫：上一会话遗留的 running 任务标记失败（崩溃重入协议）。"""
        cursor = self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = '服务中断', updated_at = ?"
            " WHERE status = 'running'",
            (_now_ms(),),
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
