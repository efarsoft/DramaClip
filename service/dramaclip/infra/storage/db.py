"""SQLite 连接与迁移执行。表结构权威定义：docs/service/04-数据模型.md。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_file: Path) -> sqlite3.Connection:
    """打开连接：WAL + 外键 + 忙等待 5s。
    """
    conn = sqlite3.connect(db_file, check_same_thread=False)
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
