"""infra.storage：迁移幂等、settings 仓储。"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

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
            "014_plan_scores.sql",
            "015_export_selfcheck.sql",
            "016_subtitle_band.sql",
            "017_episode_has_audio.sql",
            "018_episode_analyzed_at.sql",
            "019_bgm_tracks.sql",
            "021_visual_track.sql",
            "022_plan_publish.sql",
            "024_compute_receipts.sql",
            "025_export_degraded.sql",
            "026_publish_data.sql",
            "027_remove_highlight_cut_plans.sql",
            "028_hotwords_project_level.sql",
        ]
        assert db.migrate(conn) == expected_migrations
        assert db.migrate(conn) == []  # 第二次全量跳过
    finally:
        conn.close()


def test_migration_027_drops_highlight_cut_plans_only(memory_db: sqlite3.Connection) -> None:
    """高光混剪完全清除（2026-11-12 业主裁决）：存量方案行删除、其他模式不受牵连。

    直接执行 027 的 SQL 原文（migrate 已把它记为已应用，走机制测不到删除效果）。
    """
    memory_db.execute(
        "INSERT INTO projects (id, name, source_path, created_at, updated_at)"
        " VALUES ('p1', '剧', 'D:/x', 0, 0)"
    )
    for index, mode in enumerate(("highlight_cut", "raw_clip")):
        memory_db.execute(
            "INSERT INTO narration_plans"
            " (id, project_id, narration_mode, episode_ids, plan_data, status, created_at)"
            " VALUES (?, 'p1', ?, '[]', '{}', 'ready', 0)",
            (f"plan-{index}", mode),
        )
    sql = (db.MIGRATIONS_DIR / "027_remove_highlight_cut_plans.sql").read_text("utf-8")
    memory_db.executescript(sql)
    left = [
        row[0]
        for row in memory_db.execute("SELECT narration_mode FROM narration_plans")
    ]
    assert left == ["raw_clip"], "只删高光混剪，别的模式一行不动"


def test_migration_028_drops_global_hotwords_row(memory_db: sqlite3.Connection) -> None:
    """人工热词改项目级（2026-11-12 业主裁决）：全局行删除（跨剧泄漏源），
    其他设置键不受牵连。直接执行 028 的 SQL 原文（migrate 已记为已应用）。"""
    memory_db.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES"
        " ('asr.hotwords_extra', '骆养性、崇祯', 0),"
        " ('asr.pause_split', '1', 0)"
    )
    sql = (db.MIGRATIONS_DIR / "028_hotwords_project_level.sql").read_text("utf-8")
    memory_db.executescript(sql)
    left = {row[0] for row in memory_db.execute("SELECT key FROM settings")}
    assert left == {"asr.pause_split"}, "只删热词全局行，别的键一行不动"


# ---- 迁移原子性：一份脚本一个事务 ----


def _install_migration_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """两份迁移的临时目录：002 默认前两句能过、第三句必炸。"""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_base.sql").write_text(
        "CREATE TABLE t (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    (migrations / "002_broken.sql").write_text(
        "INSERT INTO t (id) VALUES (1);\n"
        "ALTER TABLE t ADD COLUMN note TEXT;\n"
        "INSERT INTO no_such_table (id) VALUES (1);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    return migrations


def test_failed_migration_is_rolled_back_whole_and_retries_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """脚本中途失败：整份回滚（不是把前几句留在库里）、名字不落，修好后从这份重来。

    此前每份脚本裸跑、记名另起一个事务：中途炸了前几句已经提交，下次启动
    从头再跑就撞在第一句上（``duplicate column name``），服务每次启动都死在
    同一步，库却已经停在谁也不认识的半截状态。
    """
    migrations = _install_migration_dir(tmp_path, monkeypatch)
    conn = db.connect(tmp_path / "data.db")
    conn._LEAK_TIMEOUT_S = 0.3
    try:
        with (
            caplog.at_level(logging.ERROR, logger="dramaclip.infra.storage.db"),
            pytest.raises(sqlite3.OperationalError, match="no_such_table"),
        ):
            db.migrate(conn)

        columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(t)")]
        assert columns == ["id"], f"半截迁移留在了库里: {columns}"
        assert conn.execute("SELECT * FROM t").fetchall() == []
        applied = [str(row[0]) for row in conn.execute("SELECT name FROM schema_migrations")]
        assert applied == ["001_base.sql"]
        assert "002_broken.sql" in caplog.text and "回滚" in caplog.text

        # 回滚后连接照常可用，写归属没留给启动线程：别的线程的写不必等超时自愈
        errors: list[BaseException] = []

        def _other_thread_writes() -> None:
            try:
                conn.execute("INSERT INTO t (id) VALUES (7)")
                conn.commit()
            except BaseException as exc:  # noqa: BLE001 - 诊断
                errors.append(exc)

        thread = threading.Thread(target=_other_thread_writes)
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive() and errors == [], f"写归属泄漏: {errors}"
        assert "tx_lock" not in capsys.readouterr().err, "别的线程的写等到了超时自愈"

        # 修好脚本后从 002 整份重来（列也在这一份里加回来）：001 不重跑，一次到位
        (migrations / "002_broken.sql").write_text(
            "ALTER TABLE t ADD COLUMN note TEXT;\n"
            "INSERT INTO t (id, note) VALUES (1, 'ok');\n",
            encoding="utf-8",
        )
        assert db.migrate(conn) == ["002_broken.sql"]
        rows = conn.execute("SELECT id, note FROM t ORDER BY id").fetchall()
        assert rows == [(1, "ok"), (7, None)]
    finally:
        conn.close()


def test_migrations_pending_is_read_only_and_tracks_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """待应用清单只报不建：它在备份之前问，这时不能动库。"""
    migrations = _install_migration_dir(tmp_path, monkeypatch)
    (migrations / "002_broken.sql").write_text(
        "ALTER TABLE t ADD COLUMN note TEXT;\n", encoding="utf-8"
    )
    conn = db.connect(tmp_path / "data.db")
    try:
        assert db.migrations_pending(conn) == ["001_base.sql", "002_broken.sql"]
        tables = [
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        assert tables == [], "问个清单把库改了"

        assert db.migrate(conn) == ["001_base.sql", "002_broken.sql"]
        assert db.migrations_pending(conn) == []
    finally:
        conn.close()


def test_migrations_pending_matches_what_migrate_applies_on_the_real_dir() -> None:
    """对着真实迁移目录：清单就是 migrate 实际会应用的那些（备份据此决定留哪类快照）。"""
    conn = sqlite3.connect(":memory:", factory=db.SerializedConnection)
    try:
        pending = db.migrations_pending(conn)
        assert pending and db.migrate(conn) == pending
        assert db.migrations_pending(conn) == []
    finally:
        conn.close()


# ---- 只读连接：URI 转义 ----


def test_connect_readonly_opens_the_requested_file_when_the_path_has_uri_delimiters(
    tmp_path: Path,
) -> None:
    """数据目录含 ``#`` / ``%`` 时也必须读到同一个库（2026-11-24 审查实锤）。

    URI 里 ``#`` 起片段、``?`` 起查询：裸拼的路径在 ``#`` 处被截断，打开的是
    另一个库——查询一律「没有这张表」，还在数据目录之外留下一个游离文件。
    """
    data_dir = tmp_path / "数据 #1 100%"
    data_dir.mkdir()
    db_file = data_dir / "data.db"
    writer = db.connect(db_file)
    writer.execute("CREATE TABLE t (v INTEGER)")
    writer.execute("INSERT INTO t VALUES (42)")
    writer.commit()
    writer.close()

    reader = db.connect_readonly(db_file)
    try:
        assert reader.execute("SELECT v FROM t").fetchone()[0] == 42
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO t VALUES (1)")  # 只读：驱动层拦写
    finally:
        reader.close()
    assert list(tmp_path.iterdir()) == [data_dir], "在数据目录之外留下了游离文件"


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


def test_leaked_ownership_is_healed_by_another_thread(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """持有归属的线程「死亡」（不再有任何动作）→ 另一线程超时后强制收复并继续写。

    RLock 时代这里的自愈是空操作：release() 由非持有线程调用必 RuntimeError，
    被吞掉之后的无超时 acquire 就永久等一个已消失的线程（2026-09-30 全量分析
    卡死 30 分钟的根因）。换 Lock 后代释放真正生效。
    """
    memory_db._LEAK_TIMEOUT_S = 0.2  # type: ignore[attr-defined]
    done = threading.Event()
    healed = threading.Event()

    def _dead_owner() -> None:
        memory_db.execute(
            "INSERT INTO projects (id, name, source_path, status, settings, created_at, updated_at)"
            " VALUES ('dead', 'd', ?, 'pending', '{}', 1, 1)",
            (str(tmp_path / "dead-src"),),
        )
        memory_db.commit()
        done.set()  # 这条线程到此「死亡」：不再有任何动作（故意不收尾什么）

    threading.Thread(target=_dead_owner, daemon=True).start()
    done.wait(5)

    def _healer() -> None:
        memory_db.execute(
            "INSERT INTO projects (id, name, source_path, status, settings, created_at, updated_at)"
            " VALUES ('heal', 'h', ?, 'pending', '{}', 2, 2)",
            (str(tmp_path / "heal-src"),),
        )
        memory_db.commit()
        healed.set()

    threading.Thread(target=_healer, daemon=True).start()
    assert healed.wait(5), "泄漏归属未在超时后被另一线程收复"

    row = memory_db.execute("SELECT name FROM projects WHERE id = 'heal'").fetchone()
    assert row is not None and row[0] == "h"
