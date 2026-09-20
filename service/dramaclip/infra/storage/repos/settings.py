"""settings 表仓储（键值对，值统一为字符串）。"""

from __future__ import annotations

import sqlite3
import time


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {str(key): str(value) for key, value in rows}


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, int(time.time() * 1000)),
    )
    conn.commit()

def delete_value(conn: sqlite3.Connection, key: str) -> None:
    """删除设置键（提示词重置 = 删覆盖回默认）。"""
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
