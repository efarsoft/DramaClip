"""SQLite 连接与迁移执行。表结构权威定义：docs/service/04-数据模型.md。"""

from __future__ import annotations

import logging
import sqlite3
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Literal

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_logger = logging.getLogger(__name__)

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
        self._tx_lock = threading.Lock()
        self._LEAK_TIMEOUT_S = 60.0
        self._tx_depth: dict[int, int] = {}

    def _begin_own(self) -> None:
        owner = threading.get_ident()
        depth = self._tx_depth.get(owner, 0)
        if depth == 0 and not self._tx_lock.acquire(timeout=self._LEAK_TIMEOUT_S):
            # 泄漏自愈：持锁线程 60s 未收口（正常单条 execute 毫秒级）视为已消亡，
            # 强制重置锁与归属记录——永久死锁比短暂互斥破坏更致命。留 error 供追因。
            self._tx_depth.clear()
            # Lock（非 RLock）才允许他线程代释放——这是自愈能成立的前提
            self._tx_lock.release()
            print("[error] db tx_lock 等待超时，判定事务归属泄漏，已强制重置", file=sys.stderr)
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


def connect_readonly(db_file: Path) -> sqlite3.Connection:
    """打开只读连接（读写分离批②）：WAL 模式下读写天然并发，绕开
    SerializedConnection 的 _call_lock——轻量查询永不被写事务卡住。

    与 connect() 的差异：
    - 裸 sqlite3.Connection（无 SerializedConnection 包装）——读不需要串行化
    - URI 模式 readonly=True：驱动层保证不会意外写入
    - 不需要 busy_timeout：WAL 读不碰写锁
    """
    # 路径必须转义后再进 URI：``#`` 起片段、``?`` 起查询、``%`` 起转义——裸拼的话
    # 数据目录名里带一个 ``#`` 就打开另一个（新建的空）库，查询一律「没有这张表」。
    uri = f"file:{urllib.parse.quote(db_file.as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrations_pending(conn: sqlite3.Connection) -> list[str]:
    """尚未应用的迁移名（文件名序）。只报不建——启动时在留备份**之前**问，这时不能动库。"""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    applied: set[str] = set()
    if exists is not None:
        applied = {str(row[0]) for row in conn.execute("SELECT name FROM schema_migrations")}
    return [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """按文件名序号执行增量迁移（幂等），返回本次应用的迁移名列表。

    每份脚本连同「记名」是**一个事务**：中途失败整份回滚、名字不落，库停在
    上一份迁移之后——下次启动从这份重来。此前脚本裸跑、记名另起事务，炸在
    中间时前几句已经提交，重来就撞在第一句上（``duplicate column name``），
    此后每次启动都死在同一步，库却停在谁也不认识的半截状态。
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    applied = {str(row[0]) for row in conn.execute("SELECT name FROM schema_migrations")}
    done: list[str] = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in applied:
            continue
        script = (
            "BEGIN;\n"
            f"{sql_file.read_text(encoding='utf-8')}\n"
            f"INSERT INTO schema_migrations (name) VALUES ('{sql_file.name}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            conn.rollback()
            _logger.error(
                "迁移 %s 执行失败，已整份回滚（库未改动，停在上一份迁移之后）: %s",
                sql_file.name,
                exc,
            )
            raise
        done.append(sql_file.name)
    # 收尾释放建表语句占的写归属：不让启动线程在整个启动流程里攥着写锁
    conn.commit()
    return done
