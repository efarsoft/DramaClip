"""
JsonRpcProtocol 单元测试
"""

import pytest
import sys
from pathlib import Path

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ipc.protocol import JsonRpcProtocol, RPCError


@pytest.fixture
def protocol():
    """创建协议实例"""
    return JsonRpcProtocol()


class TestJsonRpcProtocol:
    """JsonRpcProtocol 测试"""

    def test_parse_valid_request(self, protocol):
        """应能解析有效请求"""
        request = {
            "jsonrpc": "2.0",
            "method": "project.list",
            "params": {},
            "id": "test-123"
        }

        result = protocol.parse_request(request)
        assert result is not None

        request_id, method, params = result
        assert request_id == "test-123"
        assert method == "project.list"
        assert params == {}

    def test_parse_request_without_params(self, protocol):
        """应能解析无参数的请求"""
        request = {
            "jsonrpc": "2.0",
            "method": "system.ping",
            "id": 1
        }

        result = protocol.parse_request(request)
        assert result is not None

        request_id, method, params = result
        assert request_id == 1
        assert method == "system.ping"
        assert params is None

    def test_parse_request_without_id(self, protocol):
        """应能解析无 ID 的请求（通知）"""
        request = {
            "jsonrpc": "2.0",
            "method": "progress.update",
            "params": {"progress": 50}
        }

        result = protocol.parse_request(request)
        assert result is not None

        request_id, method, params = result
        assert request_id is None
        assert method == "progress.update"

    def test_parse_invalid_jsonrpc_version(self, protocol):
        """无效的 jsonrpc 版本应返回 None"""
        request = {
            "jsonrpc": "1.0",
            "method": "test"
        }

        result = protocol.parse_request(request)
        assert result is None

    def test_parse_missing_method(self, protocol):
        """缺少 method 字段应返回 None"""
        request = {
            "jsonrpc": "2.0",
            "id": 1
        }

        result = protocol.parse_request(request)
        assert result is None

    def test_parse_non_dict_request(self, protocol):
        """非字典请求应返回 None"""
        result = protocol.parse_request("not a dict")
        assert result is None

        result = protocol.parse_request(123)
        assert result is None

        result = protocol.parse_request(None)
        assert result is None

    def test_success_response(self, protocol):
        """成功响应格式应正确"""
        response = protocol.success_response("test-123", {"data": "value"})

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "test-123"
        assert response["result"] == {"data": "value"}
        assert "error" not in response

    def test_error_response(self, protocol):
        """错误响应格式应正确"""
        response = protocol.error_response("test-123", -32601, "Method not found")

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "test-123"
        assert "result" not in response
        assert response["error"]["code"] == -32601
        assert response["error"]["message"] == "Method not found"

    def test_error_response_with_data(self, protocol):
        """带 data 的错误响应格式应正确"""
        response = protocol.error_response(
            "test-123", -32602, "Invalid params", {"detail": "missing field"}
        )

        assert response["error"]["data"] == {"detail": "missing field"}

    def test_notification(self, protocol):
        """通知格式应正确（无 id）"""
        notification = protocol.notification("progress.update", {"progress": 50})

        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "progress.update"
        assert notification["params"] == {"progress": 50}
        assert "id" not in notification

    def test_notification_without_params(self, protocol):
        """无参数的通知格式应正确"""
        notification = protocol.notification("ready")

        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "ready"
        assert "params" not in notification

    def test_generate_id(self, protocol):
        """生成的 ID 应为字符串且不为空"""
        id1 = protocol.generate_id()
        id2 = protocol.generate_id()

        assert isinstance(id1, str)
        assert len(id1) > 0
        assert id1 != id2  # 每次生成的 ID 应不同


class TestRPCError:
    """RPCError 测试"""

    def test_create_error(self):
        """应能创建错误"""
        error = RPCError(-32601, "Method not found")

        assert error.code == -32601
        assert error.message == "Method not found"
        assert error.data is None
        assert str(error) == "Method not found"

    def test_create_error_with_data(self):
        """应能创建带 data 的错误"""
        error = RPCError(-32602, "Invalid params", {"field": "name"})

        assert error.code == -32602
        assert error.message == "Invalid params"
        assert error.data == {"field": "name"}

    def test_error_codes(self):
        """预定义错误码应存在"""
        assert RPCError.Code.INTERNAL_ERROR == -32000
        assert RPCError.Code.METHOD_NOT_FOUND == -32601
        assert RPCError.Code.INVALID_PARAMS == -32602
