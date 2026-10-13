"""AgentGateway 生命周期：设置键驱动的启停、token 自举落库、换端口重监听。"""

from __future__ import annotations

import socket
import sqlite3
import urllib.request
from pathlib import Path

import pytest

from dramaclip.api.agent_gateway import AgentGateway
from dramaclip.infra.storage import db


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "data.db")
    db.migrate(conn)
    yield conn
    conn.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            return resp.status == 200
    except OSError:
        return False


def _settings(port: int, **overrides: str) -> dict[str, str]:
    base = {
        "agent_gateway.enabled": "true",
        "agent_gateway.port": str(port),
        "agent_gateway.token": "",
    }
    base.update(overrides)
    return base


def test_disabled_by_default_keeps_listener_down(conn: sqlite3.Connection) -> None:
    gateway = AgentGateway(conn)
    gateway.sync(_settings(_free_port(), **{"agent_gateway.enabled": "false"}))
    assert gateway.running is False


def test_enable_starts_listener_and_autogenerates_token(conn: sqlite3.Connection) -> None:
    port = _free_port()
    gateway = AgentGateway(conn)
    settings = _settings(port)
    gateway.sync(settings)
    try:
        assert gateway.running is True
        assert _health(port) is True
        # token 自举：生成 + 落库 + 回写设置字典（偏好设置页据此显示）
        token = settings["agent_gateway.token"]
        assert token != ""
        stored = conn.execute(
            "SELECT value FROM settings WHERE key = 'agent_gateway.token'"
        ).fetchone()[0]
        assert stored == token
    finally:
        gateway.stop()
    assert gateway.running is False
    assert _health(port) is False


def test_port_change_restarts_listener(conn: sqlite3.Connection) -> None:
    port_a, port_b = _free_port(), _free_port()
    gateway = AgentGateway(conn)
    settings = _settings(port_a)
    gateway.sync(settings)
    try:
        assert _health(port_a) is True
        settings["agent_gateway.port"] = str(port_b)
        gateway.sync(settings)
        assert _health(port_b) is True
        assert _health(port_a) is False
    finally:
        gateway.stop()
