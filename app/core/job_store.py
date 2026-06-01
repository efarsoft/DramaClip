"""
任务元数据持久化层（参考 OmniVoice-Studio backend/core/job_store.py）

存储 jobs（状态机）+ job_events（事件溯源），使任务状态在进程崩溃后可恢复。

特性：
- SQLite 持久化，WAL 模式支持并发
- 完整的生命周期管理：pending -> running -> done/failed/cancelled
- 事件溯源：每次状态变更记录到 job_events 表
- 启动时自动清扫孤儿任务（崩溃恢复）
- 事件上限管理，防止数据库膨胀
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

from app.core import DB_PATH


# 每个任务的最大事件数（防止数据库膨胀）
_EVENT_CAP_PER_JOB = 500


class JobStore:
    """SQLite 任务持久化存储"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化 jobs 和 job_events 表"""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL DEFAULT 'unknown',
                    project_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL,
                    error TEXT,
                    meta_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    job_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON jobs(project_id);
                CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, seq);
            """)
        logger.debug(f"[JobStore] 数据库已初始化: {self.db_path}")

    # ==================== 生命周期 ====================

    def create(self, job_id: str, *, job_type: str = "unknown",
               project_id: Optional[str] = None, meta: Optional[dict] = None) -> None:
        """创建新任务记录"""
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs "
                "(id, type, project_id, status, created_at, updated_at, meta_json) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (job_id, job_type, project_id, now, now, json.dumps(meta or {})),
            )

    def mark_running(self, job_id: str) -> None:
        self._update_status(job_id, "running")

    def mark_done(self, job_id: str) -> None:
        self._update_status(job_id, "done", finished=True)

    def mark_failed(self, job_id: str, error: str) -> None:
        self._update_status(job_id, "failed", finished=True, error=error)

    def mark_cancelled(self, job_id: str) -> None:
        self._update_status(job_id, "cancelled", finished=True)

    def _update_status(self, job_id: str, status: str, *,
                       finished: bool = False, error: Optional[str] = None) -> None:
        now = time.time()
        with self._conn() as conn:
            if finished:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=?, finished_at=?, error=? WHERE id=?",
                    (status, now, now, error, job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                    (status, now, job_id),
                )

    # ==================== 事件溯源 ====================

    def append_event(self, job_id: str, payload: str) -> int:
        """追加一条事件。返回新的 seq 号。"""
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            next_seq = int(row["s"]) + 1
            conn.execute(
                "INSERT INTO job_events (job_id, seq, created_at, payload) VALUES (?, ?, ?, ?)",
                (job_id, next_seq, now, payload),
            )
            # 超限修剪
            cnt = conn.execute(
                "SELECT COUNT(*) AS n FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()["n"]
            if cnt > _EVENT_CAP_PER_JOB:
                conn.execute(
                    "DELETE FROM job_events WHERE job_id = ? AND seq IN "
                    "(SELECT seq FROM job_events WHERE job_id = ? ORDER BY seq ASC LIMIT ?)",
                    (job_id, job_id, cnt - _EVENT_CAP_PER_JOB),
                )
        return next_seq

    def events_since(self, job_id: str, after_seq: int = 0, limit: int = 1000) -> List[dict]:
        """获取指定任务的事件（支持断点续传）"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT seq, created_at, payload FROM job_events "
                "WHERE job_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (job_id, after_seq, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ==================== 查询 ====================

    def get(self, job_id: str) -> Optional[dict]:
        """获取单个任务"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, *, status: Optional[str] = None,
                  project_id: Optional[str] = None, limit: int = 100) -> List[dict]:
        """列出任务，最新的在前"""
        where = []
        params: list = []
        if status == "active":
            where.append("status IN ('pending', 'running')")
        elif status:
            where.append("status = ?")
            params.append(status)
        if project_id:
            where.append("project_id = ?")
            params.append(project_id)

        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ==================== 启动恢复 ====================

    def sweep_orphans_on_startup(self) -> int:
        """
        清扫孤儿任务：将 pending/running 状态的任务标记为 failed。

        服务器重启时，之前未完成的任务已无法恢复执行，
        标记为 failed 可以避免前端显示虚假的加载动画。
        """
        msg = "任务因服务重启中断，请在项目面板中重新执行。"
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='failed', updated_at=?, finished_at=?, error=? "
                "WHERE status IN ('pending', 'running')",
                (now, now, msg),
            )
            n = cur.rowcount
        if n:
            logger.info(f"[JobStore] 启动清扫：标记 {n} 个孤儿任务为 failed")
        return n

    def delete(self, job_id: str) -> bool:
        """删除任务及其所有事件"""
        with self._conn() as conn:
            conn.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0


# ---- 全局单例 ----

_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """获取全局 JobStore 实例"""
    global _store
    if _store is None:
        _store = JobStore()
    return _store
