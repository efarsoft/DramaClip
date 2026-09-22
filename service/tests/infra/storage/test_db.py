"""infra.storage：迁移幂等、settings 仓储。"""

from __future__ import annotations

import sqlite3

import pytest

from dramaclip.infra.storage import db
from dramaclip.infra.storage.repos import settings as settings_repo


def test_migrate_creates_all_tables(memory_db: sqlite3.Connection) -> None:
    rows = memory_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {row[0] for row in rows}
    expected = {
        "schema_migrations",
        "projects",
        "episodes",
        "episode_prescreen",
        "episode_analysis",
        "narration_plans",
        "export_jobs",
        "tts_cache",
        "subtitle_presets",
        "jobs",
        "settings",
    }
    assert expected <= tables


def test_migrate_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        expected_migrations = [
            "001_init.sql",
            "002_add_audio_features.sql",
            "003_export_meta.sql",
            "004_export_error.sql",
            "005_project_cover.sql",
            "006_episode_name_cover.sql",
            "007_engine_configs.sql",
            "008_jobs_label_and_project_settings.sql",
            "009_ocr_segments.sql",
            "010_plan_angles.sql",
            "011_export_cover.sql",
            "012_plan_titles.sql",
            "013_episode_source_signature.sql",
        ]
        assert db.migrate(conn) == expected_migrations
        assert db.migrate(conn) == []  # 第二次全量跳过
    finally:
        conn.close()


def test_settings_roundtrip(memory_db: sqlite3.Connection) -> None:
    assert settings_repo.get_all(memory_db) == {}
    settings_repo.set_value(memory_db, "llm.model", "qwen-plus")
    settings_repo.set_value(memory_db, "llm.model", "qwen-max")  # 覆盖更新
    settings_repo.set_value(memory_db, "tts.engine", "edge")
    assert settings_repo.get_all(memory_db) == {"llm.model": "qwen-max", "tts.engine": "edge"}


# ---- SerializedConnection：共享连接上的并发写回归 ----


def test_memory_db_fixture_uses_the_serialized_factory() -> None:
    """夹具与 db.connect 必须同一形态：测试用裸连接，生产的并发事务互踩就测不出来。"""
    from tests.conftest import REPO_ROOT  # noqa: F401 - 触发夹具所在模块

    conn = sqlite3.connect(":memory:", factory=db.SerializedConnection)
    conn.execute("CREATE TABLE t (v INT)")
    conn.commit()
    conn.close()


def test_concurrent_writes_on_one_connection_do_not_error() -> None:
    """事故形状复现：多线程共用一个连接，execute/commit 并发。

    裸连接（threadsafety=3）在本用例的负载下实测会抛
    `InterfaceError: bad parameter or other API misuse` 与
    `cannot start a transaction within a transaction`；串行化后必须零错误。
    """
    import threading

    conn = sqlite3.connect(
        ":memory:", check_same_thread=False, factory=db.SerializedConnection
    )
    conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, n INT)")
    conn.execute("INSERT INTO jobs VALUES ('j1', 'pending', 0)")
    conn.commit()
    errors: list[BaseException] = []

    def poller(stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                conn.execute("SELECT status FROM jobs WHERE id=?", ("j1",)).fetchone()
            except BaseException as exc:  # noqa: BLE001 - 诊断
                errors.append(exc)

    def worker(index: int) -> None:
        for k in range(400):
            try:
                conn.execute(
                    "UPDATE jobs SET status=?, n=? WHERE id=?", ("running", k, "j1")
                )
                conn.commit()
            except BaseException as exc:  # noqa: BLE001 - 诊断
                errors.append(exc)
                return

    stop = threading.Event()
    threads = [threading.Thread(target=poller, args=(stop,), daemon=True)]
    threads += [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads[1:]:
        thread.join(timeout=60)
    stop.set()
    conn.close()
    assert errors == [], f"共享连接并发写炸了: {errors[:3]}"


def test_write_transactions_keep_ownership_across_threads() -> None:
    """线程 a 的写事务未提交时，线程 b 的写必须等待，不得挤进 a 的事务。

    `replace_all`/`set_enabled` 的多语句原子性根基：裸连接上 b 的 INSERT 会直接
    落进 a 打开的事务，a 的 commit 把 b 的半截一起提交（真事故形状）。
    """
    import threading
    import time

    conn = sqlite3.connect(
        ":memory:", check_same_thread=False, factory=db.SerializedConnection
    )
    conn.execute("CREATE TABLE t (owner TEXT)")
    conn.commit()
    a_in_tx = threading.Event()
    b_order: list[str] = []
    errors: list[BaseException] = []

    def writer_a() -> None:
        try:
            conn.execute("INSERT INTO t VALUES ('a1')")
            a_in_tx.set()
            time.sleep(0.3)  # 事务敞开：b 若挤进来就是归属失效
            conn.execute("INSERT INTO t VALUES ('a2')")
            conn.commit()
            b_order.append("a_committed")
        except BaseException as exc:  # noqa: BLE001 - 诊断
            errors.append(exc)

    def writer_b() -> None:
        try:
            assert a_in_tx.wait(5.0), "a 没进事务"
            conn.execute("INSERT INTO t VALUES ('b1')")
            conn.commit()
            b_order.append("b_committed")
        except BaseException as exc:  # noqa: BLE001 - 诊断
            errors.append(exc)

    ta, tb = threading.Thread(target=writer_a), threading.Thread(target=writer_b)
    ta.start()
    tb.start()
    ta.join(timeout=30)
    tb.join(timeout=30)
    rows = [row[0] for row in conn.execute("SELECT owner FROM t ORDER BY rowid").fetchall()]
    conn.close()
    assert errors == [], f"写事务归属互踩: {errors[:3]}"
    assert rows == ["a1", "a2", "b1"], f"b 挤进了 a 的事务或顺序错乱: {rows}"
    assert b_order == ["a_committed", "b_committed"], f"提交顺序错乱: {b_order}"


def test_result_cursor_survives_concurrent_execute() -> None:
    """execute().fetchone() 是两步：裸连接上另一线程的 execute 会把游标重置，
    fetchone 读到 None（「任务不存在」假象）或别人的行。物化后必须稳定读到自己的行。"""
    import threading

    conn = sqlite3.connect(
        ":memory:", check_same_thread=False, factory=db.SerializedConnection
    )
    conn.execute("CREATE TABLE t (tag TEXT, v INT)")
    conn.execute("INSERT INTO t VALUES ('target', 42)")
    conn.commit()
    errors: list[BaseException] = []
    start = threading.Event()

    def reader() -> None:
        start.wait()
        try:
            for _ in range(2000):
                cursor = conn.execute("SELECT v FROM t WHERE tag='target'")
                # 故意在 execute 与 fetchone 之间让别的线程跑：裸游标在这里被重置
                threading.Event().wait(0.0)
                row = cursor.fetchone()
                assert row is not None, "fetchone 读到 None：游标被并发 execute 重置"
                assert row[0] == 42, f"读到别人的行: {row}"
        except BaseException as exc:  # noqa: BLE001 - 诊断
            errors.append(exc)

    def noise() -> None:
        start.wait()
        try:
            for _ in range(4000):
                conn.execute("SELECT COUNT(*) FROM t").fetchone()
        except BaseException as exc:  # noqa: BLE001 - 诊断
            errors.append(exc)

    threads = [threading.Thread(target=reader)] + [
        threading.Thread(target=noise) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=60)
    conn.close()
    assert errors == [], f"并发下结果集错乱: {errors[:3]}"


def test_failed_write_releases_ownership() -> None:
    """坏语句不许把半个事务和归属锁留给下个线程：不回滚=所有后续作业饿死。"""
    conn = sqlite3.connect(":memory:", factory=db.SerializedConnection)
    conn.execute("CREATE TABLE t (v INT)")
    conn.commit()
    with pytest.raises(sqlite3.Error):
        conn.execute("INSERT INTO nonexistent VALUES (1)")
    # 归属已释放：后续写事务照常
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_context_manager_commits_and_rolls_back() -> None:
    """`with conn:`（engine_configs.set_enabled 的形状）必须走覆写的 commit/rollback，
    否则 C 层默认实现绕过归属释放，一次 with 就永久锁死连接。"""
    conn = sqlite3.connect(":memory:", factory=db.SerializedConnection)
    conn.execute("CREATE TABLE t (v INT)")
    conn.commit()
    with conn:
        conn.execute("INSERT INTO t VALUES (1)")
        conn.execute("INSERT INTO t VALUES (2)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    try:
        with conn:
            conn.execute("INSERT INTO t VALUES (3)")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2, "with 异常未回滚"
    # 回滚后归属未泄漏
    with conn:
        conn.execute("INSERT INTO t VALUES (4)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    conn.close()
