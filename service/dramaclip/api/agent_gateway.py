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
from dramaclip.engines.narration.copy_audit import review_copy
from dramaclip.engines.narration.findings import ReviewReport
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import RpcRequest

_SETTINGS_PREFIX = "agent_gateway."

# 生产链端点允许透传进 Router.dispatch 的 RPC 方法白名单（分析/规划/出片/任务查询）。
# 不放任意方法：网关只开放自动化生产链需要的读/提交面，不代理 settings.update、
# system.shutdown 这类能改全局状态的方法——生产链自动化不等于把整个服务裸端出去。
_PRODUCTION_CHAIN_METHODS = frozenset(
    {
        "analysis.start",
        "analysis.status",
        "analysis.results",
        "narration.plan_variants",
        "narration.list_plans",
        "narration.get_plan",
        "narration.publish_pack",
        "export.submit",
        "export.get",
        "export.list",
        "jobs.get",
        "jobs.list",
        "system.ping",
    }
)


def handle_produce_chain(
    router_provider: Callable[[], Any] | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    """生产链一条龙（B3-14 无人值守入口）：分析 → 规划 → 出片，返回各阶段 job_id。

    复用 Router.dispatch 走与桌面端同一份库函数（契约零漂移），不重造业务逻辑。
    缺 router_provider（独立 CLI 无生产运行时）时如实回 501，不静默假绿。
    """
    router = router_provider() if router_provider is not None else None
    if router is None:
        raise NotImplementedError(
            "生产链端点需要服务内网关（带 Router）；独立 CLI 不承载生产运行时"
        )
    project_id = str(body.get("project_id") or "")
    if not project_id:
        raise ValueError("body.project_id 必须非空")
    modes = [str(m) for m in (body.get("modes") or [])]
    if not modes:
        raise ValueError("body.modes 必须非空数组")
    k = int(body.get("k") or 1)
    # 阶段① 分析（已分析过会幂等跳过，不重转写）
    analysis_result = _dispatch(router, "analysis.start", {"project_id": project_id})
    analysis_job = str(analysis_result.get("job_id") or "")
    # 阶段② 规划（每模式 K 条卖点互异方案）
    plan_result = _dispatch(
        router,
        "narration.plan_variants",
        {"project_id": project_id, "modes": modes, "k": k},
    )
    plan_job = str(plan_result.get("job_id") or "")
    return {
        "ok": True,
        "project_id": project_id,
        "analysis_job_id": analysis_job,
        "plan_job_id": plan_job,
        "modes": modes,
        "k": k,
        "hint": "轮询 jobs.get(analysis_job_id / plan_job_id) 追踪进度；"
        "规划完成后用 export.submit 出片",
    }


def handle_export_status(
    router_provider: Callable[[], Any] | None, body: dict[str, Any]
) -> dict[str, Any]:
    """查某条出片 job 的状态（B3-14 轮询面）：终态返回结果与自检。"""
    router = router_provider() if router_provider is not None else None
    if router is None:
        raise NotImplementedError("独立 CLI 不承载生产运行时")
    export_id = str(body.get("export_id") or "")
    if not export_id:
        raise ValueError("body.export_id 必须非空")
    return _dispatch(router, "export.get", {"export_id": export_id})


def handle_job_status(
    router_provider: Callable[[], Any] | None, body: dict[str, Any]
) -> dict[str, Any]:
    """查某条 job（分析/规划/出片）的状态与进度（B3-14 轮询面）。"""
    router = router_provider() if router_provider is not None else None
    if router is None:
        raise NotImplementedError("独立 CLI 不承载生产运行时")
    job_id = str(body.get("job_id") or "")
    if not job_id:
        raise ValueError("body.job_id 必须非空")
    return _dispatch(router, "jobs.get", {"job_id": job_id})


def _dispatch(router: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """白名单内方法经 Router.dispatch；越界方法不转发（不代理改状态端点）。"""
    if method not in _PRODUCTION_CHAIN_METHODS:
        raise ValueError(f"方法 {method} 不在生产链白名单内")
    response = router.dispatch(RpcRequest(id="agent", method=method, params=params))
    if response.error is not None:
        raise ValueError(f"{method} 失败: {response.error.message}")
    return dict(response.result or {})


def _report_json(report: ReviewReport) -> dict[str, Any]:
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
    return _report_json(review_copy(lines, slots, mode=str(body.get("mode", ""))))


def handle_retell_check(
    body: dict[str, Any], settings: dict[str, str]
) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise ValueError("body.text 必须是非空解说稿纯文本")
    from dramaclip.engines.narration.retell import retell_check
    from dramaclip.engines.semantic.llm_client import client_for

    report = retell_check(text, client_for(settings))
    return report.to_json()


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
        # body.timeout_s 是协议字段名，进来后当下限用（工厂取 max），不改协议
        min_timeout_s=float(body.get("timeout_s") or titles_engine.TITLES_LLM_TIMEOUT_S),
        trace_path=llm_trace.trace_path(trace_dir, f"llm_titles_agent_{stamp}.json"),
    )


def make_handler(
    token: str,
    settings_provider: Callable[[], dict[str, str]],
    trace_dir: Path | None = None,
    router_provider: Callable[[], Any] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """构造带鉴权与路由的 handler 类；settings/trace_dir/router_provider 注入（测试替身用）。

    router_provider 给生产链端点（B3-14）用：服务内网关注入 Router，独立 CLI 缺省（端点回 501）。
    """

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

        def _send_not_implemented(self, detail: str) -> None:
            self._send(501, {"error": detail, "reason": "not_implemented_in_this_gateway"})

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
                "/tools/retell_check": lambda b: handle_retell_check(
                    b, settings_provider()
                ),
                "/tools/produce_chain": lambda b: handle_produce_chain(
                    router_provider, b
                ),
                "/tools/export_status": lambda b: handle_export_status(
                    router_provider, b
                ),
                "/tools/job_status": lambda b: handle_job_status(
                    router_provider, b
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
            except NotImplementedError as exc:
                self._send_not_implemented(str(exc))
            except ValueError as exc:
                self._send(422, {"error": str(exc)})

        def do_GET(self) -> None:  # noqa: N802 - http.server 命名约定
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return Handler


class AgentGateway:
    """设置键驱动的网关生命周期：sync(settings) 热生效，stop() 随服务退出。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        trace_dir: Path | None = None,
        router_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._conn = conn
        self._trace_dir = trace_dir
        self._router_provider = router_provider
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
                (
                    "127.0.0.1",
                    port,
                ),
                make_handler(
                    token,
                    lambda: settings,
                    self._trace_dir,
                    self._router_provider,
                ),
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
