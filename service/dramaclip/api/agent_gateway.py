"""Agent 网关：本机 127.0.0.1 HTTP 工具面，供外部 agent 调用审查与出稿。

由 agent_gateway.* 设置键驱动（偏好设置页「Agent 网关」分区），随服务进程常驻：
sync() 按设置启停/重启监听，settings.update 后热生效。零转发——audit/draft 的
库函数就在本进程。外部调用契约见 skills/dramaclip-agent/references/api.md；
无桌面/源码直跑的 CLI 形态见 tools/agent_server.py。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dramaclip.engines import llm_trace
from dramaclip.engines.narration import audit as A
from dramaclip.engines.narration import titles as titles_engine
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.infra.storage.repos import settings as settings_repo

_SETTINGS_PREFIX = "agent_gateway."


def _report_json(report: A.ReviewReport) -> dict[str, Any]:
    return {
        "target": report.target,
        "passed": report.passed,
        "findings": [asdict(f) for f in report.findings],
        "meta": report.meta,
    }


def handle_audit_script(body: dict[str, Any]) -> dict[str, Any]:
    script = body.get("script")
    if not isinstance(script, dict):
        raise ValueError("body.script 必须是剧本 JSON 对象")
    transcript = body.get("transcript")
    if transcript is not None and not isinstance(transcript, list):
        raise ValueError("body.transcript 必须是台词数组或 null")
    return _report_json(A.review_script(script, transcript))


def handle_audit_copy(body: dict[str, Any]) -> dict[str, Any]:
    lines = body.get("lines")
    slots = body.get("slots")
    if not isinstance(lines, list) or not isinstance(slots, list):
        raise ValueError("body.lines 与 body.slots 必须是数组")
    return _report_json(A.review_copy(lines, slots, mode=str(body.get("mode", ""))))


def handle_draft_titles(
    body: dict[str, Any], settings: dict[str, str], trace_dir: Path | None = None
) -> dict[str, Any]:
    texts = body.get("narration_texts")
    if not isinstance(texts, list) or not any(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError("body.narration_texts 必须是非空文案字符串数组")
    plan_data = {
        "narration_texts": [
            {"id": f"n{i}", "text": str(t)} for i, t in enumerate(texts) if str(t).strip()
        ]
    }
    stamp = time.strftime("%m%d_%H%M%S")
    return titles_engine.generate(
        plan_data,
        settings,
        timeout_s=float(body.get("timeout_s") or 120.0),
        trace_path=llm_trace.trace_path(trace_dir, f"llm_titles_agent_{stamp}.json"),
    )


def make_handler(
    token: str,
    settings_provider: Callable[[], dict[str, str]],
    trace_dir: Path | None = None,
) -> type[BaseHTTPRequestHandler]:
    """构造带鉴权与路由的 handler 类；settings/trace_dir 注入（测试替身用）。"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # 安静：别刷服务日志
            pass

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method: str) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._send(200, {"ok": True, "service": "dramaclip-agent"})
                return
            if self.headers.get("Authorization", "") != f"Bearer {token}":
                self._send(401, {"error": "缺少或错误的 Bearer token"})
                return
            routes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
                "/tools/audit_script": handle_audit_script,
                "/tools/audit_copy": handle_audit_copy,
                "/tools/draft_titles": lambda b: handle_draft_titles(
                    b, settings_provider(), trace_dir
                ),
            }
            handler = routes.get(path)
            if handler is None or method != "POST":
                self._send(404, {"error": f"未知端点: {method} {path}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body 必须是 JSON 对象")
            except (json.JSONDecodeError, ValueError) as exc:
                self._send(400, {"error": f"请求体非法: {exc}"})
                return
            try:
                self._send(200, handler(body))
            except LlmUnavailable as exc:
                self._send(503, {"error": str(exc)})
            except ValueError as exc:
                self._send(422, {"error": str(exc)})

        def do_GET(self) -> None:  # noqa: N802 - http.server 命名约定
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return Handler


class AgentGateway:
    """设置键驱动的网关生命周期：sync(settings) 热生效，stop() 随服务退出。"""

    def __init__(self, conn: sqlite3.Connection, trace_dir: Path | None = None) -> None:
        self._conn = conn
        self._trace_dir = trace_dir
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._signature: tuple[int, str] | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def sync(self, settings: dict[str, str]) -> str | None:
        """按设置对齐监听状态；返回人读状态变化（无变化返回 None）。写回自动生成的 token。"""
        with self._lock:
            enabled = settings.get(f"{_SETTINGS_PREFIX}enabled") == "true"
            if not enabled:
                self._stop_locked()
                return None
            port = int(settings.get(f"{_SETTINGS_PREFIX}port") or 8340)
            token = settings.get(f"{_SETTINGS_PREFIX}token") or ""
            if not token:
                token = secrets.token_urlsafe(24)
                settings_repo.set_value(self._conn, f"{_SETTINGS_PREFIX}token", token)
                settings[f"{_SETTINGS_PREFIX}token"] = token
            signature = (port, token)
            if self._server is not None and self._signature == signature:
                return None
            self._stop_locked()
            server = ThreadingHTTPServer(
                ("127.0.0.1", port), make_handler(token, lambda: settings, self._trace_dir)
            )
            thread = threading.Thread(
                target=server.serve_forever, name="agent-gateway", daemon=True
            )
            self._server = server
            self._thread = thread
            self._signature = signature
            thread.start()
            return f"Agent 网关已启动: http://127.0.0.1:{port}"

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._server is None:
            return
        server = self._server
        self._server = None
        self._thread = None
        self._signature = None
        server.shutdown()
        server.server_close()
