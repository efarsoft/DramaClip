"""
IpcServer 单元测试
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ipc.server import IpcServer
from app.ipc.router import Router
from app.ipc.protocol import RPCError


@pytest.fixture
def router():
    """创建路由器"""
    return Router()


@pytest.fixture
def server(router):
    """创建服务端实例"""
    return IpcServer(router)


class TestIpcServer:
    """IpcServer 测试"""

    def test_handle_valid_request(self, server, router):
        """应能处理有效请求"""
        handler = MagicMock(return_value={"id": "1", "name": "test"})
        router.register("project", "list", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "project.list",
            "params": {},
            "id": "req-1"
        }

        response = server.handle(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-1"
        assert response["result"] == {"id": "1", "name": "test"}
        handler.assert_called_once()

    def test_handle_request_with_params(self, server, router):
        """应能传递参数给处理器"""
        handler = MagicMock(return_value={"created": True})
        router.register("project", "create", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "project.create",
            "params": {"name": "新项目", "path": "/tmp/test"},
            "id": "req-2"
        }

        response = server.handle(request)

        assert response["result"] == {"created": True}
        handler.assert_called_once_with(name="新项目", path="/tmp/test")

    def test_handle_method_not_found(self, server):
        """未注册的方法应返回错误"""
        request = {
            "jsonrpc": "2.0",
            "method": "nonexistent.method",
            "id": "req-3"
        }

        response = server.handle(request)

        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "not found" in response["error"]["message"].lower()

    def test_handle_invalid_request(self, server):
        """无效请求应返回错误"""
        request = {
            "jsonrpc": "1.0",  # 无效版本
            "method": "test"
        }

        response = server.handle(request)

        assert "error" in response
        assert response["error"]["code"] == -32600

    def test_handle_handler_type_error(self, server, router):
        """处理器参数类型错误应返回 Invalid params"""
        def handler(name: str):
            return {"name": name}

        router.register("test", "method", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "test.method",
            "params": {"wrong_param": "value"},  # 错误的参数名
            "id": "req-4"
        }

        response = server.handle(request)

        assert "error" in response
        assert response["error"]["code"] == -32602

    def test_handle_handler_rpc_error(self, server, router):
        """处理器抛出 RPCError 应返回对应错误"""
        def handler():
            raise RPCError(-32101, "Project not found")

        router.register("project", "open", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "project.open",
            "id": "req-5"
        }

        response = server.handle(request)

        assert response["error"]["code"] == -32101
        assert response["error"]["message"] == "Project not found"

    def test_handle_handler_generic_error(self, server, router):
        """处理器抛出通用异常应返回 Internal error"""
        def handler():
            raise ValueError("Something went wrong")

        router.register("test", "method", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "test.method",
            "id": "req-6"
        }

        response = server.handle(request)

        assert response["error"]["code"] == -32603
        assert "Internal error" in response["error"]["message"]

    def test_register_handler(self, server):
        """应能通过 register_handler 注册处理器"""
        handler = MagicMock(return_value="result")
        server.register_handler("test", "method", handler)

        request = {
            "jsonrpc": "2.0",
            "method": "test.method",
            "id": "req-7"
        }

        response = server.handle(request)
        assert response["result"] == "result"

    @patch('builtins.print')
    def test_send_notification(self, mock_print, server):
        """应能发送通知"""
        server.send_notification("ready", {"version": "1.0"})

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        notification = json.loads(call_args)

        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "ready"
        assert notification["params"] == {"version": "1.0"}
        assert "id" not in notification

    @patch('builtins.print')
    def test_send_progress(self, mock_print, server):
        """应能发送进度更新"""
        server.send_progress("task-1", 50, "处理中", phase="分析")

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        notification = json.loads(call_args)

        assert notification["method"] == "progress.update"
        assert notification["params"]["task_id"] == "task-1"
        assert notification["params"]["progress"] == 50
        assert notification["params"]["phase"] == "分析"

    @patch('builtins.print')
    def test_send_log(self, mock_print, server):
        """应能发送日志"""
        server.send_log("测试消息", "info")

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        notification = json.loads(call_args)

        assert notification["method"] == "log.append"
        assert notification["params"]["message"] == "测试消息"
        assert notification["params"]["level"] == "info"

    def test_stop(self, server):
        """应能停止服务端"""
        assert server._running is False
        server._running = True
        server.stop()
        assert server._running is False
