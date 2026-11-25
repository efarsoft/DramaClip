"""SQLite 在线备份与轮转（数据安全）：启动时备份一次，保留最近 7 份。"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path

_BACKUP_DIR = "backups"
_KEEP_COUNT = 7
# 启动快照的最小间隔。服务启动即挂时桌面端会自动重拉 3 次（退避 2/4/6s），开发期
# 也频繁重启——不间隔的话每次拉起一份，几次重试就把干净的那份挤出保留窗口。
_MIN_INTERVAL_S = 10 * 60
_STARTUP_PREFIX = "data_"
_MIGRATION_PREFIX = "premigrate_"
_SIDECARS = ("-wal", "-shm", "-journal")
_logger = logging.getLogger(__name__)


def backup_database(
    db_file: Path, *, pending: Sequence[str] = (), keep: int = _KEEP_COUNT
) -> Path | None:
    """启动时留一份快照，返回快照路径（库不存在/还是空库/间隔内已留过则 None）。

    两种快照各自命名、各自轮转，互不挤占：
    - ``pending``（待应用的迁移名）非空：**迁移前快照**，按首个待应用迁移定名，
      每个迁移边界恒一份。迁移失败会整份回滚、下次启动从同一边界重来，桌面端
      还要自动重拉 3 次——定名让重试不堆文件，原位覆盖让留下的始终是最后一次
      尝试之前的库。
    - 否则是普通启动快照：距最近一份不足 ``_MIN_INTERVAL_S`` 时跳过。
    """
    if not db_file.is_file() or db_file.stat().st_size == 0:
        return None
    backup_dir = db_file.parent / _BACKUP_DIR
    if pending:
        prefix = _MIGRATION_PREFIX
        target = backup_dir / f"{prefix}{Path(pending[0]).stem}.db"
    else:
        prefix = _STARTUP_PREFIX
        if _is_recent(backup_dir):
            return None
        target = backup_dir / f"{prefix}{time.strftime('%Y%m%d_%H%M%S')}.db"
    backup_dir.mkdir(parents=True, exist_ok=True)
    _copy(db_file, target)
    _rotate(backup_dir, prefix, keep)
    if pending:
        _logger.info(
            "迁移前快照: %s（迁移失败会整份回滚；需手工回退时：退出应用，"
            "删掉 %s 及同名 -wal/-shm，再把这份快照改名顶上）",
            target,
            db_file.name,
        )
    return target


def _is_recent(backup_dir: Path) -> bool:
    """最近一份启动快照是否还在最小间隔内。时钟被拨回（年龄为负）不算。"""
    stamps = [path.stat().st_mtime for path in backup_dir.glob(f"{_STARTUP_PREFIX}*.db")]
    if not stamps:
        return False
    return 0 <= time.time() - max(stamps) < _MIN_INTERVAL_S


def _copy(db_file: Path, target: Path) -> None:
    """在线备份（WAL 安全）。先写临时文件再原子改名：挂着正式名字的快照一定写完整。"""
    staged = target.with_name(target.name + ".tmp")
    _discard(staged)  # 上次写到一半崩掉的残骸
    try:
        source = sqlite3.connect(db_file)
        try:
            dest = sqlite3.connect(staged)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        os.replace(staged, target)
    finally:
        _discard(staged)


def _rotate(backup_dir: Path, prefix: str, keep: int) -> None:
    """同一前缀的快照保留最近 keep 份；被挤掉的连侧车（-wal/-shm/-journal）一起删，
    写到一半的 .tmp 残骸顺手清。删不动（被占用/只读）就留着并留痕——清理失败
    不许挡启动。"""
    snapshots = sorted(backup_dir.glob(f"{prefix}*.db"), key=_mtime, reverse=True)
    for stale in snapshots[keep:]:
        if _discard(stale):
            for suffix in _SIDECARS:
                _discard(Path(f"{stale}{suffix}"))
    for leftover in backup_dir.glob(f"{prefix}*.db.tmp"):
        _discard(leftover)


def _mtime(path: Path) -> float:
    return path.stat().st_mtime


def _discard(path: Path) -> bool:
    """尽力删一个文件：删掉了/本来就没有返回 True，删不动返回 False 并留痕。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _logger.warning("旧文件删不掉，先留着: %s（%s）", path, exc)
        return False
    return True
