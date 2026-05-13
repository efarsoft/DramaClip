"""
JSON-RPC 协议定义
"""

import uuid
from typing import Any, Optional, Tuple


class RPCError(Exception):
    """RPC 错误异常"""

    def __init__(
        self,
        code: int,
        message: str,
        data: Optional[Any] = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    # 预定义错误码
    class Code:
        # 系统级错误 (-32000 ~ -32099)
        INTERNAL_ERROR = -32000
        BACKEND_NOT_READY = -32001
        FILE_NOT_FOUND = -32002
        PERMISSION_DENIED = -32003

        # 项目错误 (-32100 ~ -32199)
        PROJECT_NOT_FOUND = -32101
        PROJECT_ALREADY_EXISTS = -32102

        # 分析错误 (-32200 ~ -32299)
        ASR_FAILED = -32201
        UNSUPPORTED_VIDEO_FORMAT = -32202

        # 剪辑错误 (-32300 ~ -32399)
        INSUFFICIENT_HIGHLIGHTS = -32301
        TTS_SYNTHESIS_FAILED = -32302

        # 导出错误 (-32400 ~ -32499)
        FFMPEG_EXECUTION_FAILED = -32401
        INSUFFICIENT_DISK_SPACE = -32402

        # JSON-RPC 标准错误
        INVALID_REQUEST = -32600
        METHOD_NOT_FOUND = -32601
        INVALID_PARAMS = -32602
        INTERNAL_RPC_ERROR = -32603


class JsonRpcProtocol:
    """JSON-RPC 2.0 协议处理器"""

    VERSION = "2.0"

    def parse_request(
        self, request: dict
    ) -> Optional[Tuple[Any, str, Optional[dict]]]:
        """
        解析请求
        返回: (request_id, method, params) 或 None
        """
        if not isinstance(request, dict):
            return None

        if request.get("jsonrpc") != self.VERSION:
            return None

        method = request.get("method")
        if not isinstance(method, str):
            return None

        request_id = request.get("id")
        params = request.get("params")

        return (request_id, method, params)

    def success_response(self, request_id: Any, result: Any) -> dict:
        """构建成功响应"""
        return {
            "jsonrpc": self.VERSION,
            "id": request_id,
            "result": result
        }

    def error_response(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Optional[Any] = None
    ) -> dict:
        """构建错误响应"""
        response = {
            "jsonrpc": self.VERSION,
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        if data is not None:
            response["error"]["data"] = data
        return response

    def notification(
        self,
        method: str,
        params: Optional[dict] = None
    ) -> dict:
        """构建通知（无 id）"""
        notification = {
            "jsonrpc": self.VERSION,
            "method": method
        }
        if params:
            notification["params"] = params
        return notification

    def generate_id(self) -> str:
        """生成请求 ID"""
        return str(uuid.uuid4())
