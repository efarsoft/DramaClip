"""infra.storage.backup：启动快照按间隔留、迁移前快照按迁移边界留、轮转不挡启动。

背景（2026-11-24 审查实锤）：此前每次启动无条件留一份、只保留 7 份。服务
启动即挂时桌面端会自动重拉 3 次，一次「打开应用」就是 4 份——两次打不开，
迁移前那份干净备份就被挤没了。本机备份目录即实证：7 份全落在 8 天里。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra.storage import backup, db

_BACKUP_DIR = "backups"
_KEEP = backup._KEEP_COUNT  # noqa: SLF001 - 测试直接读常量，改保留份数时用例自动跟随
_WINDOW = backup._MIN_INTERVAL_S  # noqa: SLF001


class _Clock:
    """可控时钟：备份的命名与间隔判断都读它，用例不必真等、也不会同秒撞名。

    起点定在真实时刻前一天：刚写出的文件带着真实修改时间，永远比「拨旧」过的
    旧快照新——轮转按修改时间排，否则新文件会先被当成最旧的删掉。
    """

    def __init__(self) -> None:
        self.now = time.time() - 86_400

    def time(self) -> float:
        return self.now

    def strftime(self, fmt: str) -> str:
        return time.strftime(fmt, time.localtime(self.now))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(backup, "time", clock)
    return clock


def _make_db(tmp_path: Path, value: int = 1) -> Path:
    db_file = tmp_path / "data.db"
    conn = db.connect(db_file)
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return db_file


def _set_value(db_file: Path, value: int) -> None:
    conn = db.connect(db_file)
    conn.execute("UPDATE t SET v = ?", (value,))
    conn.commit()
    conn.close()


def _value(snapshot: Path) -> int:
    conn = sqlite3.connect(snapshot)
    try:
        row = conn.execute("SELECT v FROM t").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        conn.close()


def _names(tmp_path: Path, pattern: str) -> list[str]:
    return sorted(path.name for path in (tmp_path / _BACKUP_DIR).glob(pattern))


def _age(path: Path, clock: _Clock, seconds: float) -> None:
    """把文件的修改时间拨到「时钟当前时刻的 seconds 秒之前」。"""
    stamp = clock.now - seconds
    os.utime(path, (stamp, stamp))


def _backup(db_file: Path, clock: _Clock, **kwargs: Any) -> Path | None:
    """留一份快照，并把它的修改时间对齐到可控时钟（刚写完的按「现在」算）。"""
    snapshot = backup.backup_database(db_file, **kwargs)
    if snapshot is not None:
        _age(snapshot, clock, 0)
    return snapshot


def _startup_snapshot(tmp_path: Path, db_file: Path, clock: _Clock) -> Path:
    """过了间隔、留一份启动快照、再把它的修改时间拨旧（早于之后留的每一份）。"""
    clock.now += _WINDOW + 1
    snapshot = _backup(db_file, clock)
    assert snapshot is not None
    _age(snapshot, clock, _WINDOW + 1)
    return snapshot


def _sidecars(*mains: Path) -> None:
    for main in mains:
        for suffix in ("-wal", "-shm"):
            Path(f"{main}{suffix}").write_bytes(b"")


# ---- 启动快照：间隔内不重复留 ----


def test_startup_snapshots_are_spaced_by_the_minimum_interval(
    tmp_path: Path, clock: _Clock
) -> None:
    db_file = _make_db(tmp_path)

    first = _backup(db_file, clock)
    assert first is not None and first.name.startswith("data_")
    assert _value(first) == 1
    # 几秒内重启（崩溃重拉/开发期）：不重复留
    assert _backup(db_file, clock) is None
    clock.now += _WINDOW - 1
    assert _backup(db_file, clock) is None, "差一秒才到期：仍不留"
    assert _names(tmp_path, "data_*.db") == [first.name]

    clock.now += 2
    second = _backup(db_file, clock)
    assert second is not None and second != first
    assert len(_names(tmp_path, "data_*.db")) == 2


def test_clock_rolled_back_does_not_suppress_snapshots(tmp_path: Path, clock: _Clock) -> None:
    """系统时钟被拨回后，最近一份快照的「年龄」是负数——不能因此一直不备份。"""
    db_file = _make_db(tmp_path)
    first = _backup(db_file, clock)
    assert first is not None
    stamp = clock.now + 3600
    os.utime(first, (stamp, stamp))

    assert _backup(db_file, clock) is not None


def test_missing_or_brand_new_database_is_skipped(tmp_path: Path, clock: _Clock) -> None:
    """库文件不存在或还是 0 字节的空库：没什么可备份，也不建目录。"""
    assert backup.backup_database(tmp_path / "data.db") is None
    (tmp_path / "data.db").write_bytes(b"")
    assert backup.backup_database(tmp_path / "data.db") is None
    assert not (tmp_path / _BACKUP_DIR).exists()


def test_snapshot_carries_data_still_sitting_in_the_wal(tmp_path: Path, clock: _Clock) -> None:
    """源库开着不关、最新一次写入还没 checkpoint：快照必须带上（在线备份的契约）。"""
    db_file = tmp_path / "data.db"
    conn = db.connect(db_file)
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    try:
        snapshot = _backup(db_file, clock)
        assert snapshot is not None
        assert _value(snapshot) == 42
    finally:
        conn.close()


def test_failed_copy_leaves_no_half_written_snapshot(tmp_path: Path, clock: _Clock) -> None:
    """源库已损坏时备份会抛错：不许留下挂着正式名字的半截文件，目录留着下次接着用。"""
    db_file = _make_db(tmp_path)
    db_file.write_bytes(b"this is not a database " * 64)

    with pytest.raises(sqlite3.DatabaseError, match="not a database"):
        backup.backup_database(db_file)

    backup_dir = tmp_path / _BACKUP_DIR
    assert backup_dir.is_dir()
    assert [path.name for path in backup_dir.iterdir()] == []


# ---- 迁移前快照：按迁移边界定名，启动快照挤不掉 ----


def test_pre_migration_snapshot_is_one_per_boundary_and_tracks_the_latest_attempt(
    tmp_path: Path, clock: _Clock
) -> None:
    """同一边界反复启动（迁移失败→桌面端自动重拉）恒一份，原位覆盖成最新。"""
    db_file = _make_db(tmp_path)
    assert _backup(db_file, clock) is not None  # 刚留过启动快照

    # 迁移前快照不受启动快照的最小间隔约束
    snapshot = _backup(db_file, clock, pending=["029_next.sql"])
    assert snapshot is not None and snapshot.name == "premigrate_029_next.db"
    assert _value(snapshot) == 1

    for value in range(2, 6):  # 4 次启动 = 首次拉起 + 3 次自动重拉
        _set_value(db_file, value)
        again = _backup(db_file, clock, pending=["029_next.sql"])
        assert again == snapshot
        assert _names(tmp_path, "premigrate_*.db") == ["premigrate_029_next.db"]
    assert _value(snapshot) == 5, "留下的必须是最后一次尝试之前的库"


def test_startup_churn_cannot_evict_pre_migration_snapshots(tmp_path: Path, clock: _Clock) -> None:
    """两个命名空间各自轮转：启动快照把保留窗口填满再溢出，迁移前快照纹丝不动。"""
    db_file = _make_db(tmp_path)
    snapshot = _backup(db_file, clock, pending=["029_next.sql"])
    assert snapshot is not None

    for _ in range(_KEEP + 3):
        _startup_snapshot(tmp_path, db_file, clock)

    assert len(_names(tmp_path, "data_*.db")) == _KEEP
    assert snapshot.is_file()


def test_pre_migration_snapshots_keep_the_newest_boundaries(
    tmp_path: Path, clock: _Clock, caplog: pytest.LogCaptureFixture
) -> None:
    """迁移边界多了也只留最近 keep 份，并且留痕说明这份快照怎么用。"""
    db_file = _make_db(tmp_path)
    with caplog.at_level(logging.INFO, logger="dramaclip.infra.storage.backup"):
        for index in range(_KEEP + 2):
            snapshot = _backup(db_file, clock, pending=[f"{index + 1:03d}_step.sql"])
            assert snapshot is not None
            _age(snapshot, clock, 10_000 - index * 60)  # 越晚的边界越新

    boundaries = range(3, _KEEP + 3)  # 最早的两个边界被挤出
    assert _names(tmp_path, "premigrate_*.db") == [
        f"premigrate_{number:03d}_step.db" for number in boundaries
    ]
    assert "premigrate_001_step.db" in caplog.text, "留了快照却没说在哪"
    assert "回退" in caplog.text and db_file.name in caplog.text


# ---- 轮转：连侧车一起删，删不动不挡启动 ----


def test_rotation_removes_evicted_snapshots_with_their_sidecars(
    tmp_path: Path, clock: _Clock
) -> None:
    db_file = _make_db(tmp_path)
    made = [_startup_snapshot(tmp_path, db_file, clock) for _ in range(_KEEP)]  # 恰好装满
    evicted, survivor = made[0], made[-1]
    _sidecars(evicted, survivor)
    unrelated = tmp_path / _BACKUP_DIR / "backup-db-0930.db"  # 手工备份：不归轮转管
    unrelated.write_bytes(b"not a sqlite file")
    _sidecars(unrelated)

    _startup_snapshot(tmp_path, db_file, clock)  # 溢出一份：最旧的连侧车一起走

    assert len(_names(tmp_path, "data_*.db")) == _KEEP
    assert not evicted.exists()
    assert not Path(f"{evicted}-wal").exists() and not Path(f"{evicted}-shm").exists()
    # 留下的那份与其侧车、手工备份一行不动
    assert survivor.exists() and Path(f"{survivor}-wal").exists()
    assert unrelated.exists() and Path(f"{unrelated}-wal").exists()


@pytest.mark.parametrize(
    "error", [PermissionError(13, "另一个程序正在使用此文件"), OSError(28, "只读")]
)
def test_undeletable_old_snapshot_does_not_break_startup(
    tmp_path: Path,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: OSError,
) -> None:
    """被挤掉的旧备份删不掉（被占用/只读）：留着、留痕、不许抛到启动流程。"""
    db_file = _make_db(tmp_path)
    made = [_startup_snapshot(tmp_path, db_file, clock) for _ in range(_KEEP)]
    locked = made[0]
    _sidecars(locked)
    real_unlink = Path.unlink
    taken: list[str] = []

    def _unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == locked.name:
            raise error
        taken.append(self.name)
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)
    for _ in range(2):  # 溢出两份：made[0] 删不动，made[1] 照常删
        _startup_snapshot(tmp_path, db_file, clock)

    assert locked.exists()
    # 主文件还开着：它的侧车不能动（动了就是在别人打开的库脚下抽文件）
    assert f"{locked.name}-wal" not in taken
    assert made[1].name in taken, "其余被挤掉的照常删"
    assert locked.name in caplog.text
