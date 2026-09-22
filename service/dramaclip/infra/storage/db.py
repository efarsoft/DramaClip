"""SQLite 连接与迁移执行。表结构权威定义：docs/service/04-数据模型.md。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Literal

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_WRITE_PREFIXES = ("insert", "update", "delete", "replace", "create", "drop", "alter")


def _is_write(sql: str) -> bool:
    """按首个关键字判写语句：写才开事务，才需要整段归属。"""
    return sql.lstrip().lower().startswith(_WRITE_PREFIXES)


class _ResultCursor:
    """物化结果集：行在 execute 的锁内一次取完。

    共享连接上 `execute(...).fetchone()` 是**两步**：另一线程在这两步之间再
    execute，会把本线程还没读的结果集整个重置——fetchone 拿到 None（上层读成
    「任务不存在」）或拿到别的查询的行（``dict(zip(...))`` 长度错配）。
    锁只能让每条语句原子，跨语句的游标消费必须由物化来兜底。
    """

    __slots__ = ("_rows", "_pos", "rowcount", "lastrowid", "description")

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._rows: list[Any] = cursor.fetchall()
        self._pos = 0
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.lastrowid
        self.description = cursor.description

    def fetchone(self) -> Any:
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self) -> list[Any]:
        rest = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rest

    def __iter__(self) -> Any:
        return iter(self.fetchall())

    def close(self) -> None:
        self._pos = len(self._rows)


class SerializedConnection(sqlite3.Connection):
    """多线程共享单连接的串行化包装（生产与测试共用的唯一连接形态）。

    事故形状（tests/api 满载偶发、生产同样可触发）：RPC 执行池、后台作业线程、
    状态轮询共用一个 ``sqlite3.Connection``。``threadsafety=3`` 只保证**单次调用**
    原子，保不住「execute→commit」这个逻辑事务：A 线程 UPDATE 开了事务，B 线程的
    UPDATE 挤进同一事务，A 的 commit 把 B 的半截一起提交，B 再 commit 就撞
    ``cannot start a transaction within a transaction``；驱动层则直接
    ``InterfaceError: bad parameter or other API misuse``。作业线程死在
    ``mark_running``，future 没人取，异常蒸发——任务永远 pending。

    两层锁 + 物化游标，缺一不可：
    - ``_call_lock``：每次 execute/commit/rollback/close 互斥，堵驱动层误用；
    - ``_tx_lock``：写事务归属——首个写语句拿锁，同线程后续写可重入，
      commit/rollback 才释放。读不占归属，仍可并发；
    - ``_ResultCursor``：execute 在锁内取完全部行。不物化的话，
      `execute(...).fetchone()` 两步之间会被别的线程的 execute 重置游标，
      读出 None 或别人的行（「任务不存在」假象与 zip 长度错配的来源）。

    写失败即回滚并交还归属：不回滚会把半个事务留给下个线程，
    不释放归属则等于永久饿死所有后续作业。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._call_lock = threading.Lock()
        self._tx_lock = threading.RLock()
        self._tx_depth: dict[int, int] = {}

    def _begin_own(self) -> None:
        owner = threading.get_ident()
        depth = self._tx_depth.get(owner, 0)
        if depth == 0:
            self._tx_lock.acquire()
        self._tx_depth[owner] = depth + 1

    def _end_own(self) -> None:
        owner = threading.get_ident()
        if self._tx_depth.pop(owner, 0) > 0:
            self._tx_lock.release()

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        write = _is_write(sql)
        if write:
            self._begin_own()
        try:
            with self._call_lock:
                return _ResultCursor(super().execute(sql, parameters))
        except BaseException:
            if write:
                self._rollback_and_release()
            raise

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        with self._call_lock:
            return super().executescript(sql_script)

    def commit(self) -> None:
        try:
            with self._call_lock:
                super().commit()
        finally:
            self._end_own()

    def rollback(self) -> None:
        try:
            with self._call_lock:
                super().rollback()
        finally:
            self._end_own()

    def _rollback_and_release(self) -> None:
        try:
            with self._call_lock:
                super().rollback()
        except sqlite3.Error:
            pass  # 连接已坏/已关：归属仍要释放，锁泄漏比回滚失败更致命
        finally:
            self._end_own()

    def close(self) -> None:
        with self._call_lock:
            super().close()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        # 不走 C 层默认实现：必须命中上面的 commit/rollback 覆写，归属才会释放
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect(db_file: Path) -> sqlite3.Connection:
    """打开连接：WAL + 外键 + 忙等待 5s + 多线程串行化。
    """
    conn = sqlite3.connect(
        db_file, check_same_thread=False, factory=SerializedConnection
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """按文件名序号执行增量迁移（幂等），返回本次应用的迁移名列表。"""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    applied = {str(row[0]) for row in conn.execute("SELECT name FROM schema_migrations")}
    done: list[str] = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in applied:
            continue
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (sql_file.name,))
        conn.commit()
        done.append(sql_file.name)
    return done
