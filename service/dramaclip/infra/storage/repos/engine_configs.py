"""engine_configs repo：云端/服务端点配置的多实例存储（按域分组，单启用）。"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

_COLUMNS = ("id", "domain", "name", "base_url", "api_key", "model", "enabled", "created_at")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "••••" if value else ""
    return value[:4] + "••••" + value[-4:]


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    data = dict(zip(_COLUMNS, row, strict=True))
    data["api_key_masked"] = _mask(str(data["api_key"]))
    return data


def list_by_domain(conn: sqlite3.Connection, domain: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, domain, name, base_url, api_key, model, enabled, created_at"
        " FROM engine_configs WHERE domain = ? ORDER BY created_at",
        (domain,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get(conn: sqlite3.Connection, config_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, domain, name, base_url, api_key, model, enabled, created_at"
        " FROM engine_configs WHERE id = ?",
        (config_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def create(
    conn: sqlite3.Connection,
    domain: str,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    config_id = uuid4().hex
    conn.execute(
        "INSERT INTO engine_configs"
        " (id, domain, name, base_url, api_key, model, enabled, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (config_id, domain, name, base_url, api_key, model, _now_ms()),
    )
    conn.commit()
    config = get(conn, config_id)
    assert config is not None
    return config


def update(
    conn: sqlite3.Connection,
    config_id: str,
    *,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
) -> None:
    conn.execute(
        "UPDATE engine_configs SET name = ?, base_url = ?, api_key = ?, model = ? WHERE id = ?",
        (name, base_url, api_key, model, config_id),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, config_id: str) -> None:
    conn.execute("DELETE FROM engine_configs WHERE id = ?", (config_id,))
    conn.commit()


def set_enabled(conn: sqlite3.Connection, domain: str, config_id: str) -> None:
    """单启用：同域全部清零后再点亮目标配置（同事务）。"""
    with conn:
        conn.execute("UPDATE engine_configs SET enabled = 0 WHERE domain = ?", (domain,))
        conn.execute(
            "UPDATE engine_configs SET enabled = 1 WHERE id = ? AND domain = ?",
            (config_id, domain),
        )


def get_enabled(conn: sqlite3.Connection, domain: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, domain, name, base_url, api_key, model, enabled, created_at"
        " FROM engine_configs WHERE domain = ? AND enabled = 1 LIMIT 1",
        (domain,),
    ).fetchone()
    return _row_to_dict(row) if row else None
