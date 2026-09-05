"""SQLite 在线备份与轮转（数据安全）：启动时备份一次，保留最近 7 份。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_BACKUP_DIR = "backups"
_KEEP_COUNT = 7


def backup_database(db_file: Path, *, keep: int = _KEEP_COUNT) -> Path | None:
    """在线备份（WAL 安全）到 backups/，轮转删除最旧的多余备份。返回备份路径。"""
    if not db_file.is_file():
        return None
    backup_dir = db_file.parent / _BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"data_{time.strftime('%Y%m%d_%H%M%S')}.db"
    source = sqlite3.connect(db_file)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    _rotate(backup_dir, keep)
    return target


def _rotate(backup_dir: Path, keep: int) -> None:
    backups = sorted(backup_dir.glob("data_*.db"))
    stale = backups[:-keep] if len(backups) > keep else []
    for old in stale:
        old.unlink(missing_ok=True)
