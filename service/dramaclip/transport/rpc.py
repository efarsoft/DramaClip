"""JSON-RPC 2.0 信封与路由。权威定义：protocol/schemas/common.json。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR_BASE = -32000  # 业务错误段起点（分段见 docs/03-IPC协议规范.md 第 5 节）

Handler = Callable[[dict[str, Any]], Any]


class RpcDomainError(Exception):
    """业务域错误：携带分段错误码（docs/03-IPC协议规范.md §5）。

    api 层抛出，Router.dispatch 转为对应错误响应（未捕获的其他异常仍兜底 -32603）。
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RpcRequest(BaseModel):
    """入站请求信封。"""

    jsonrpc: str = "2.0"
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class RpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class RpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: RpcError | None = None


class RpcNotification(BaseModel):
    """出站通知信封（无 id）。"""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class Router:
    """方法注册表。方法名必须与 protocol/schemas 的 x-methods 一致（CI 契约测试校验）。"""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    @property
    def method_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def register(self, method: str, handler: Handler) -> None:
        if method in self._handlers:
            raise ValueError(f"RPC 方法重复注册: {method}")
        self._handlers[method] = handler

    def dispatch(self, request: RpcRequest) -> RpcResponse:
        handler = self._handlers.get(request.method)
        if handler is None:
            return error_response(request.id, METHOD_NOT_FOUND, f"方法不存在: {request.method}")
        try:
            result = handler(request.params)
        except RpcDomainError as exc:
            return error_response(request.id, exc.code, exc.message)
        except Exception as exc:  # 边界兜底：任何异常都转为错误响应而非断连
            return error_response(request.id, INTERNAL_ERROR, str(exc))
        return RpcResponse(id=request.id, result=result)


def error_response(request_id: int | str | None, code: int, message: str) -> RpcResponse:
    return RpcResponse(id=request_id, error=RpcError(code=code, message=message))


def parse_request(line: str) -> RpcRequest:
    """解析一行请求；失败抛 ValueError（调用方转 -32700 响应）。"""
    try:
        payload = json.loads(line)
        return RpcRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(str(exc)) from exc
