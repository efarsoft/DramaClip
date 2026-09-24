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


# 非终态进度上限：没到 DONE 就不许写 100——「进度 100% 但任务没完成」是比卡住更糟的
# 假状态（渲染层最后一步失败/挂起时进度条已经报满）。100 只由 mark_completed 迁移写入。
_PROGRESS_CAP = 99.0


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
        # 完成即写 100：set_progress 把非终态钳在 99（_PROGRESS_CAP），终态的满进度
        # 只能在这里补写，否则完成任务永远停在 99。failed/cancelled 不补——保留
        # 中断时的进度供事后诊断。
        self._transition(job_id, "completed", progress=100.0)

    def mark_failed(self, job_id: str, error: str) -> None:
        self._transition(job_id, "failed", error=error)

    def mark_cancelled(self, job_id: str) -> None:
        self._transition(job_id, "cancelled")

    def set_progress(self, job_id: str, percent: float, label: str | None = None) -> None:
        """更新进度；label 为队列页要显示的人读阶段（如「第3集 预筛中」）。

        >=100 的写入钳到 _PROGRESS_CAP（99）：100 是终态语义，只由 mark_completed
        迁移写入；运行中的任务自报 100 会造出「进度满了但没完成」的假状态。
        (99, 100) 区间的真实值原样保留——只钳「报满」，不压中间进度。
        """
        if percent >= 100.0:
            percent = _PROGRESS_CAP
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

    def clear_finished(self) -> int:
        """删除全部终态任务记录（完成/失败/取消），返回删除条数；在跑与排队中的不动。"""
        placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
        cursor = self._conn.execute(
            f"DELETE FROM jobs WHERE status IN ({placeholders})",
            tuple(sorted(_TERMINAL_STATUSES)),
        )
        return cursor.rowcount

    def sweep_interrupted(self) -> int:
        """启动清扫：上一会话遗留的 running / pending 任务标记失败（崩溃重入协议）。
        """
        cursor = self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = '服务中断', updated_at = ?"
            " WHERE status IN (?, ?)",
            (_now_ms(), STATUS_PENDING, STATUS_RUNNING),
        )
        self._conn.commit()
        return cursor.rowcount or 0

    def _transition(
        self, job_id: str, status: str, error: str | None = None, progress: float | None = None
    ) -> None:
        current = self.get(job_id)
        if current is None:
            raise ValueError(f"任务不存在: {job_id}")
        if current["status"] in _TERMINAL_STATUSES:
            raise ValueError(f"任务已终态({current['status']}), 不可迁移: {job_id}")
        if progress is None:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, _now_ms(), job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, progress = ?, updated_at = ? WHERE id = ?",
                (status, error, progress, _now_ms(), job_id),
            )
        self._conn.commit()
