"""pytest 共享夹具。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from dramaclip.infra.storage import db

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def memory_db() -> Iterator[sqlite3.Connection]:
    """已迁移的内存库（每个测试独立）。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    db.migrate(conn)
    yield conn
    conn.close()
