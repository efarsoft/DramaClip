"""
JSON-RPC 服务端
通过 stdin/stdout 进行进程间通信
"""

import sys
import json
from typing import Any, Callable, Optional
from loguru import logger
from .protocol import JsonRpcProtocol, RPCError
from .router import Router


class IpcServer:
    """
    JSON-RPC 服务端
    读取 stdin 的 JSON-RPC 请求，执行并返回响应
    """

    def __init__(self, router: Optional[Router] = None):
        self.protocol = JsonRpcProtocol()
        self.router = router or Router()
        self._running = False

    def register_handler(self, namespace: str, method: str, handler: Callable):
        """注册 RPC 方法处理器"""
        self.router.register(namespace, method, handler)

    def handle(self, request: dict) -> dict:
        """处理单个请求"""
        try:
            parsed = self.protocol.parse_request(request)
            if parsed is None:
                return self.protocol.error_response(
                    None, -32600, "Invalid Request"
                )

            request_id, method, params = parsed

            # 查找处理器
            handler = self.router.resolve(method)
            if handler is None:
                return self.protocol.error_response(
                    request_id, -32601, f"Method not found: {method}"
                )

            # 执行处理
            try:
                result = handler(**(params or {}))
                return self.protocol.success_response(request_id, result)
            except TypeError as e:
                return self.protocol.error_response(
                    request_id, -32602, f"Invalid params: {e}"
                )
            except RPCError as e:
                return self.protocol.error_response(
                    request_id, e.code, e.message, e.data
                )
            except Exception as e:
                logger.exception(f"Handler error for {method}")
                return self.protocol.error_response(
                    request_id, -32603, f"Internal error: {e}"
                )

        except Exception as e:
            logger.exception("Server handle error")
            return self.protocol.error_response(None, -32603, str(e))

    def send_notification(self, method: str, params: Optional[dict] = None):
        """发送进度通知到 stdout"""
        notification = self.protocol.notification(method, params)
        print(json.dumps(notification), flush=True)

    def send_progress(
        self,
        task_id: str,
        progress: int,
        message: str,
        phase: Optional[str] = None,
        detail: Optional[dict] = None
    ):
        """发送进度更新"""
        params = {
            "task_id": task_id,
            "progress": progress,
            "message": message,
        }
        if phase:
            params["phase"] = phase
        if detail:
            params["detail"] = detail

        self.send_notification("progress.update", params)

    def send_log(self, message: str, level: str = "info"):
        """发送日志通知"""
        self.send_notification("log.append", {
            "message": message,
            "level": level
        })

    def run(self):
        """运行服务端主循环"""
        self._running = True
        logger.info("IPC Server started, listening on stdin...")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = self.handle(request)

                if response:
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                error_response = self.protocol.error_response(
                    None, -32600, f"Parse error: {e}"
                )
                print(json.dumps(error_response), flush=True)

            except Exception as e:
                logger.exception("Server loop error")
                error_response = self.protocol.error_response(
                    None, -32603, str(e)
                )
                print(json.dumps(error_response), flush=True)

        self._running = False
        logger.info("IPC Server stopped")

    def stop(self):
        """停止服务端"""
        self._running = False
