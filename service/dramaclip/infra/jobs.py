"""统一任务状态机（进度推送与崩溃重入依据，docs/service/03 第 3 节）。"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any
from uuid import uuid4

from dramaclip.infra.clock import now_ms

_LOGGER = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: 进度 DB 写节流窗口（读写分离批①）：窗口内只更新内存缓存，不拿 _call_lock。
#: UI 通知（notifier.progress）不受影响——它不走 DB。2s 是任务详情页刷新的
#: 典型间隔，进度在 UI 上不会可见地滞后。
_PROGRESS_WRITE_INTERVAL_S = 2.0

# 两个非终态值的唯一拼写源：写 pending 的是 create，写 running 的是 mark_running；
# 比它们的是启动清扫的 SQL（两者同为崩溃残留）与 api/models.py 的下载看门狗（只认
# running 才收尾）。三处必须同值——看门狗据此判断该不该收尾，启动清扫据此判定哪些是
# 崩溃残留；拼写一分家就退回「任务永停某个非终态且重启也清不掉」那个假状态。
# 写入侧一并命名，否则常量就成了没人写的孤立值（同 exports.py 的 STATUS_PENDING）。
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"

#: 中断话术只对「做得到接着上次」的任务说，且按它们真实走的那条链分两类。
#: 可续传下载：全程走 fetch.download_file，``.incomplete`` 半成品按目标路径确定性
#: 命名、跨任务保留（模型下载 / cuda 运行时 / llama 运行时三个安装器同一条链）。
_RESUMABLE_DOWNLOAD_TYPES = ("model_download", "cuda_runtime", "llama_runtime")
#: uv 安装的运行环境（tts_runtime / music_runtime）：已装好的步骤与包都留在盘上和
#: venv 里，重试接着装；但下到一半的包 uv 不续传——所以不许说「断点续传」。
_RESUMABLE_INSTALL_TYPES = ("indextts_runtime", "music_runtime")
_INTERRUPTION_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (_RESUMABLE_DOWNLOAD_TYPES, "服务中断（下载断点已保留，重试将从断点续传）"),
    (_RESUMABLE_INSTALL_TYPES, "服务中断（运行环境没装完，已装好的部分保留，重试会接着装）"),
)


def is_terminal(status: str) -> bool:
    """是否终态：终态任务不可再迁移，也不可再取消。上层据此判断，勿各写字面量。"""
    return status in _TERMINAL_STATUSES


def parse_compute(raw: object) -> list[dict[str, Any]] | None:
    """compute 回执列解析单源（作业台账与导出台账同形同语义，exports repo 同引）。"""
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(str(raw))
    except ValueError:
        return None  # 坏 JSON 按「没有回执」处理，不演成可用证据
    return [dict(item) for item in value] if isinstance(value, list) else None


# 非终态进度上限：没到 DONE 就不许写 100——「进度 100% 但任务没完成」是比卡住更糟的
# 假状态（渲染层最后一步失败/挂起时进度条已经报满）。100 只由 mark_completed 迁移写入。
_PROGRESS_CAP = 99.0


class JobStore:
    """jobs 表仓储：创建、状态迁移、进度更新、启动清扫。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # 进度写节流缓存：job_id → (monotonic 时刻, percent, label)
        self._progress_cache: dict[str, tuple[float, float, str | None]] = {}

    def create(self, job_type: str, ref_id: str | None = None) -> str:
        job_id = uuid4().hex
        now = now_ms()
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
        # 失败事件同步落 backend.log：job 行在 DB 里有，但用户发日志时
        # backend.log 才是单文件真源（装测反馈链的教训：截图只有半行红字）
        _LOGGER.error("job %s failed: %s", job_id, error)
        self._transition(job_id, "failed", error=error)

    def append_detail(self, job_id: str, line: str) -> None:
        """运行中把失败明细追加进 error 列（轮询方即时可见，不必等终态）。

        终态 mark_failed 仍会写权威全文（同样的行再拼一遍），运行态这里只是
        让「规划队列」能逐条点亮失败行，而不是全军沉默到批次结束。"""
        self._conn.execute(
            "UPDATE jobs SET error = CASE WHEN error IS NULL OR error = ''"
            " THEN ? ELSE error || '；' || ? END, updated_at = ? WHERE id = ?",
            (line, line, now_ms(), job_id),
        )
        self._conn.commit()

    def mark_cancelled(self, job_id: str) -> None:
        self._transition(job_id, "cancelled")

    def set_progress(self, job_id: str, percent: float, label: str | None = None) -> None:
        """更新进度；label 为队列页要显示的人读阶段（如「第3集 预筛中」）。

        >=100 的写入钳到 _PROGRESS_CAP（99）：100 是终态语义，只由 mark_completed
        迁移写入；运行中的任务自报 100 会造出「进度满了但没完成」的假状态。
        (99, 100) 区间的真实值原样保留——只钳「报满」，不压中间进度。

        DB 写节流（读写分离批）：分析/导出任务的进度回调每秒多次，每次都
        拿 _call_lock 写库+commit——查询池的读全在排队（「服务查询经常卡死」
        的根因）。改为最密 _PROGRESS_WRITE_INTERVAL_S 秒落盘一次，被跳过的
        值缓存在内存，下次落盘或任务终态时最终写入。UI 通知不受影响
        （notifier.progress 直接推送不走 DB）。
        """
        if percent >= 100.0:
            percent = _PROGRESS_CAP
        now = time.monotonic()
        cached = self._progress_cache.get(job_id)
        if cached is not None and now - cached[0] < _PROGRESS_WRITE_INTERVAL_S:
            # 节流窗口内：只更新内存缓存，不拿锁写库
            self._progress_cache[job_id] = (now, percent, label)
            return
        self._progress_cache[job_id] = (now, percent, label)
        self._flush_progress(job_id, percent, label)

    def _flush_progress(self, job_id: str, percent: float, label: str | None) -> None:
        """实际写库（set_progress 的非节流路径 + flush_stale 的调用点）。"""
        if label is None:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (percent, now_ms(), job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, label = ?, updated_at = ? WHERE id = ?",
                (percent, label, now_ms(), job_id),
            )
        self._conn.commit()

    def flush_stale_progress(self) -> None:
        """把节流缓存里超过窗口的进度刷进库（终态迁移前调用，防尾值丢失）。"""
        now = time.monotonic()
        stale = [
            (jid, pct, lbl)
            for jid, (ts, pct, lbl) in self._progress_cache.items()
            if now - ts >= _PROGRESS_WRITE_INTERVAL_S
        ]
        for jid, pct, lbl in stale:
            self._flush_progress(jid, pct, lbl)
            self._progress_cache.pop(jid, None)

    def set_compute(self, job_id: str, reports: list[dict[str, Any]]) -> None:
        self._conn.execute(
            "UPDATE jobs SET compute = ?, updated_at = ? WHERE id = ?",
            (json.dumps(reports, ensure_ascii=False), now_ms(), job_id),
        )
        self._conn.commit()

    def set_ref_id(self, job_id: str, ref_id: str) -> None:
        """补写 ref_id：产物路径要到洗完才知道（自动提取的音色文件名带时间戳）。"""
        self._conn.execute(
            "UPDATE jobs SET ref_id = ?, updated_at = ? WHERE id = ?",
            (ref_id, now_ms(), job_id),
        )
        self._conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, type, ref_id, status, progress, label, error, created_at, updated_at,"
            " compute FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        keys = (
            "id", "type", "ref_id", "status", "progress",
            "label", "error", "created_at", "updated_at", "compute",
        )
        record = dict(zip(keys, row, strict=True))
        record["compute"] = parse_compute(record["compute"])
        # 读己之写（读写分离批①）：节流窗口内的最新进度可能在缓存还没落盘
        # ——get() 先查缓存合并，保证调用方看到的是最新值而不是 2s 前的。
        cached = self._progress_cache.get(job_id)
        if cached is not None:
            record["progress"] = cached[1]
            if cached[2] is not None:
                record["label"] = cached[2]
        return record

    _LIST_COLUMNS = (
        "id", "type", "ref_id", "status", "progress", "label", "error", "created_at",
        "updated_at", "compute",
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
        return [self._parse_row(row) for row in rows]

    @classmethod
    def _parse_row(cls, row: tuple[Any, ...]) -> dict[str, Any]:
        record = dict(zip(cls._LIST_COLUMNS, row, strict=True))
        record["compute"] = parse_compute(record["compute"])
        return record

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

        话术按各类任务的重试语义说（见 ``_INTERRUPTION_HINTS``）：做得到「接着上次」
        的明说——装测实锤：用户看到「服务中断」不敢点重试，以为又要白下几个 GB。
        """
        now = now_ms()
        swept = 0
        for types, hint in _INTERRUPTION_HINTS:
            cursor = self._conn.execute(
                "UPDATE jobs SET status = 'failed', error = ?, updated_at = ?"
                f" WHERE type IN ({','.join('?' * len(types))}) AND status IN (?, ?)",
                (hint, now, *types, STATUS_PENDING, STATUS_RUNNING),
            )
            swept += cursor.rowcount or 0
        hinted = _RESUMABLE_DOWNLOAD_TYPES + _RESUMABLE_INSTALL_TYPES
        cursor = self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = '服务中断', updated_at = ?"
            f" WHERE type NOT IN ({','.join('?' * len(hinted))}) AND status IN (?, ?)",
            (now, *hinted, STATUS_PENDING, STATUS_RUNNING),
        )
        self._conn.commit()
        return swept + (cursor.rowcount or 0)

    def _transition(
        self, job_id: str, status: str, error: str | None = None, progress: float | None = None
    ) -> None:
        # 终态迁移前清节流缓存：进度回调的最后几拍可能在缓存里没落盘，
        # 这里刷出去再迁移——终态行带的 progress 才是真实终值。
        self._progress_cache.pop(job_id, None)
        current = self.get(job_id)
        if current is None:
            raise ValueError(f"任务不存在: {job_id}")
        if current["status"] in _TERMINAL_STATUSES:
            raise ValueError(f"任务已终态({current['status']}), 不可迁移: {job_id}")
        if progress is None:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, now_ms(), job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, progress = ?, updated_at = ? WHERE id = ?",
                (status, error, progress, now_ms(), job_id),
            )
        self._conn.commit()
