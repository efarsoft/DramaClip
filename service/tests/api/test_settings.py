"""api.settings：get/update/test_llm（连通性测试含本地伪 OpenAI 服务器）。"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from dramaclip.api import settings as settings_api
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, settings: dict[str, str]) -> None:
        from types import SimpleNamespace

        self.context = SimpleNamespace(conn=conn, settings=settings)
        self.router = Router()
        settings_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result


def test_update_rejects_unknown_key(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    response = harness.router.dispatch(
        RpcRequest(id=1, method="settings.update", params={"values": {"nope.key": "1"}})
    )
    assert response.error is not None and response.error.code == -32001


def test_test_llm_unconfigured(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {"llm.base_url": "", "llm.model": ""})
    response = harness.router.dispatch(RpcRequest(id=1, method="settings.test_llm", params={}))
    assert response.error is not None and response.error.code == -32003


def test_test_llm_unreachable(memory_db: sqlite3.Connection) -> None:
    harness = Harness(
        memory_db, {"llm.base_url": "http://127.0.0.1:9", "llm.model": "x", "llm.api_key": ""}
    )
    response = harness.router.dispatch(RpcRequest(id=1, method="settings.test_llm", params={}))
    assert response.error is not None and response.error.code == -32004


class _FakeOpenAI(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server 命名约定
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def test_test_llm_success_with_fake_server(
    memory_db: sqlite3.Connection, tmp_path: Any
) -> None:
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        harness = Harness(
            memory_db,
            {"llm.base_url": f"http://127.0.0.1:{server.server_port}", "llm.model": "fake"},
        )
        result = harness.rpc("settings.test_llm", {})
        assert result["ok"] is True
        assert result["model"] == "fake"
        assert result["latency_ms"] >= 0
    finally:
        server.shutdown()
