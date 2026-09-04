"""transport.rpc：信封解析、路由分发、错误码。"""

from __future__ import annotations

import pytest

from dramaclip.transport.rpc import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    Router,
    RpcRequest,
    parse_request,
)


def _router_with_ping() -> Router:
    router = Router()
    router.register("system.ping", lambda _params: {"pong": True})
    return router


def test_dispatch_ok() -> None:
    request = RpcRequest(id=1, method="system.ping", params={})
    response = _router_with_ping().dispatch(request)
    assert response.id == 1
    assert response.result == {"pong": True}
    assert response.error is None


def test_dispatch_method_not_found() -> None:
    request = RpcRequest(id=2, method="system.nope", params={})
    response = _router_with_ping().dispatch(request)
    assert response.id == 2
    assert response.error is not None
    assert response.error.code == METHOD_NOT_FOUND


def test_dispatch_handler_exception_returns_internal_error() -> None:
    def boom(_params: dict[str, object]) -> object:
        raise RuntimeError("炸了")

    router = Router()
    router.register("system.ping", boom)
    response = router.dispatch(RpcRequest(id=3, method="system.ping"))
    assert response.error is not None
    assert response.error.code == INTERNAL_ERROR
    assert "炸了" in response.error.message


def test_register_duplicate_rejected() -> None:
    router = _router_with_ping()
    with pytest.raises(ValueError, match="重复注册"):
        router.register("system.ping", lambda _params: None)


def test_parse_request_valid_line() -> None:
    request = parse_request('{"jsonrpc":"2.0","id":"a1","method":"system.ping","params":{}}')
    assert request.method == "system.ping"
    assert request.id == "a1"


def test_parse_request_invalid_json_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_request("{not-json")


def test_parse_request_missing_method_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_request('{"jsonrpc":"2.0","id":1}')
