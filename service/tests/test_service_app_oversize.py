"""超限响应不自杀：单条 RPC 响应超 16MB 上限回错误响应，服务进程必须活着。

此前 _dispatch_and_reply 走 _send，而 _send 把超限 ValueError 当连接死亡触发
_shutdown——大剧全量 analysis.results 逼近上限时，一次查询杀死整个服务、
在跑作业陪葬（2026-11-04 审查立案 H3）。
"""

from typing import Any

from dramaclip.service_app import ServiceApp
from dramaclip.transport.rpc import INTERNAL_ERROR, RpcRequest, RpcResponse


class _FakeConnection:
    """记录全部出站 payload；超大 payload 模拟真连接的 ValueError。"""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.sent: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any]) -> None:
        encoded_len = len(str(payload).encode("utf-8"))
        if encoded_len > self.max_bytes:
            raise ValueError(f"出站消息超过 {self.max_bytes} 字节上限")
        self.sent.append(payload)


class _StubRouter:
    """返回预置响应：够小或超大都由测试控制。"""

    def __init__(self, response: RpcResponse) -> None:
        self._response = response

    def dispatch(self, request: RpcRequest) -> RpcResponse:
        return self._response


def _make_app() -> ServiceApp:
    return ServiceApp("127.0.0.1:51800", "token")


def test_oversized_response_returns_error_without_shutdown() -> None:
    app = _make_app()
    # 上限须低于巨型响应、高于错误响应自身（错误信封约 200 字节）
    fake = _FakeConnection(max_bytes=512)
    app._connection = fake  # type: ignore[assignment]  # noqa: SLF001 - 测试注入
    huge = RpcResponse(id=1, result={"blob": "x" * 4096})
    request = RpcRequest(id=1, method="analysis.results")

    app._dispatch_and_reply(_StubRouter(huge), request)  # type: ignore[arg-type]  # noqa: SLF001

    # 服务未自杀：shutdown 事件没被置位
    assert not app._stop.is_set()  # noqa: SLF001
    # 客户端收到的是错误响应而不是断连
    assert len(fake.sent) == 1
    error_payload = fake.sent[0]
    assert error_payload["error"]["code"] == INTERNAL_ERROR
    assert "16MB" in error_payload["error"]["message"]
    assert error_payload["id"] == 1


def test_normal_response_still_delivered() -> None:
    app = _make_app()
    fake = _FakeConnection(max_bytes=1_000_000)
    app._connection = fake  # type: ignore[assignment]  # noqa: SLF001
    ok = RpcResponse(id=7, result={"ok": True})
    request = RpcRequest(id=7, method="jobs.list")

    app._dispatch_and_reply(_StubRouter(ok), request)  # type: ignore[arg-type]  # noqa: SLF001

    assert fake.sent == [{"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}]
    assert not app._stop.is_set()  # noqa: SLF001
