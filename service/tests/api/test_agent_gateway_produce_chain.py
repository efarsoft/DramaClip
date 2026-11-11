"""B3-14 生产链端点：白名单/方法透传/501 行为/handler 路由。

独立 CLI 没有生产运行时（无 AppContext/Router）→ 生产链端点如实 501，
不静默假绿；服务内网关注入 Router 后复用与桌面端同一份库函数（契约零漂移）。
"""

from __future__ import annotations

from typing import Any

from dramaclip.api import agent_gateway
from dramaclip.transport.rpc import RpcRequest, RpcResponse


class _FakeRouter:
    """记录被透传的方法与入参，回给可断言的 result。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(self, request: RpcRequest) -> RpcResponse:
        self.calls.append((request.method, dict(request.params)))
        # 模拟各 RPC 的 result 形状
        result: dict[str, Any] = {}
        if request.method == "analysis.start":
            result = {"job_id": "j_analysis"}
        elif request.method == "narration.plan_variants":
            result = {"job_id": "j_plan", "k": int(request.params.get("k") or 1)}
        elif request.method == "export.get":
            result = {"export": {"id": str(request.params.get("export_id"))}}
        elif request.method == "jobs.get":
            result = {"job": {"id": str(request.params.get("job_id"))}}
        return RpcResponse(id=request.id, result=result)


def test_produce_chain_dispatches_analysis_then_planning() -> None:
    router = _FakeRouter()
    out = agent_gateway.handle_produce_chain(
        lambda: router,
        {"project_id": "p1", "modes": ["full_narration"], "k": 2},
    )
    assert out["ok"] is True
    assert out["analysis_job_id"] == "j_analysis"
    assert out["plan_job_id"] == "j_plan"
    assert out["modes"] == ["full_narration"]
    assert out["k"] == 2
    methods = [m for m, _ in router.calls]
    assert methods == ["analysis.start", "narration.plan_variants"]
    # 规划透传的入参与白名单调用一致（k 真传下去）
    assert router.calls[1][1] == {"project_id": "p1", "modes": ["full_narration"], "k": 2}


def test_produce_chain_requires_project_and_modes() -> None:
    router = _FakeRouter()
    import pytest

    with pytest.raises(ValueError):
        agent_gateway.handle_produce_chain(lambda: router, {"modes": ["full_narration"]})
    with pytest.raises(ValueError):
        agent_gateway.handle_produce_chain(lambda: router, {"project_id": "p1"})


def test_produce_chain_501_without_router_provider() -> None:
    """router_provider=None（独立 CLI）→ NotImplementedError（handler 转 501）。"""
    import pytest

    with pytest.raises(NotImplementedError):
        agent_gateway.handle_produce_chain(None, {"project_id": "p1", "modes": ["full_narration"]})
    with pytest.raises(NotImplementedError):
        agent_gateway.handle_export_status(None, {"export_id": "e1"})
    with pytest.raises(NotImplementedError):
        agent_gateway.handle_job_status(None, {"job_id": "j1"})


def test_export_and_job_status_pass_through() -> None:
    router = _FakeRouter()
    agent_gateway.handle_export_status(lambda: router, {"export_id": "e9"})
    agent_gateway.handle_job_status(lambda: router, {"job_id": "j7"})
    methods = [m for m, _ in router.calls]
    assert methods == ["export.get", "jobs.get"]
    assert router.calls[0][1] == {"export_id": "e9"}
    assert router.calls[1][1] == {"job_id": "j7"}


def test_status_endpoints_require_ids() -> None:
    router = _FakeRouter()
    import pytest

    with pytest.raises(ValueError):
        agent_gateway.handle_export_status(lambda: router, {})
    with pytest.raises(ValueError):
        agent_gateway.handle_job_status(lambda: router, {})


def test_whitelist_blocks_state_muting_methods() -> None:
    """白名单外方法（settings.update/system.shutdown）不转发。"""
    router = _FakeRouter()

    import pytest

    with pytest.raises(ValueError):
        agent_gateway._dispatch(router, "settings.update", {"k": "v"})  # noqa: SLF001
    with pytest.raises(ValueError):
        agent_gateway._dispatch(router, "system.shutdown", {})  # noqa: SLF001
    # 白名单内方法放行
    agent_gateway._dispatch(router, "system.ping", {})  # noqa: SLF001
    assert ("system.ping", {}) in router.calls


def test_make_handler_wires_production_routes() -> None:
    """make_handler 把生产链端点挂进路由表；router_provider=None 时如实 501。"""
    import io
    from unittest.mock import MagicMock

    handler_cls = agent_gateway.make_handler(
        "tok",
        lambda: {"agent_gateway.enabled": "true"},
        trace_dir=None,
        router_provider=None,  # 独立 CLI 形态
    )
    # BaseHTTPRequestHandler 不能裸 __init__：绕过构造直接造实例，只驱动 _dispatch
    handler = object.__new__(handler_cls)
    handler._send = MagicMock()  # noqa: SLF001
    handler.headers = {"Authorization": "Bearer tok", "Content-Length": "0"}
    handler.path = "/tools/produce_chain"
    handler.rfile = io.BytesIO(b"{}")
    handler._dispatch("POST")  # noqa: SLF001
    # 无 router_provider → 生产链端点 501 如实不可用
    sent = handler._send.call_args.args
    assert sent[0] == 501
    assert sent[1]["reason"] == "not_implemented_in_this_gateway"
