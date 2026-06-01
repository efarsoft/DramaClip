"""
JSON-RPC 服务端
通过 stdin/stdout 进行进程间通信
"""

import sys
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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
        self._write_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ipc_handler")

    def _write_to_stdout(self, data: dict):
        """线程安全地将 JSON 响应或通知写入 stdout（M4 大 payload 保护）"""
        try:
            # 使用标准 json + ensure_ascii=False，避免依赖不存在的 DateTimeEncoder
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            size = len(serialized)
            if size > 40 * 1024 * 1024:
                logger.warning(f"[IPC] 响应体过大 ({size/1024/1024:.1f}MB)，建议改用文件路径或分片传输")
            with self._write_lock:
                sys.stdout.write(serialized + "\n")
                sys.stdout.flush()
        except Exception as e:
            logger.error(f"Failed to write to stdout: {e}")

    def register_handler(self, namespace: str, method: str, handler: Callable):
        """注册 RPC 方法处理器"""
        self.router.register(namespace, method, handler)

    def handle(self, request: dict) -> dict:
        """处理单个请求"""
        try:
            # 记录接收到的请求
            parsed = self.protocol.parse_request(request)
            if parsed is None:
                logger.debug(f"Received invalid request: {request}")
                return self.protocol.error_response(
                    None, -32600, "Invalid Request"
                )

            request_id, method, params = parsed
            logger.debug(f"Received request: method={method}, params={params}, id={request_id}")

            # 查找处理器
            handler = self.router.resolve(method)
            if handler is None:
                logger.warning(f"Method not found: {method}")
                return self.protocol.error_response(
                    request_id, -32601, f"Method not found: {method}"
                )

            # 执行处理
            try:
                result = handler(**(params or {}))
                logger.debug(f"Request {method} completed successfully")
                return self.protocol.success_response(request_id, result)
            except TypeError as e:
                logger.warning(f"Invalid params for {method}: {e}")
                return self.protocol.error_response(
                    request_id, -32602, f"Invalid params: {e}"
                )
            except RPCError as e:
                return self.protocol.error_response(
                    request_id, e.code, e.message, e.data
                )
            except (RuntimeError, ValueError, TypeError) as e:
                logger.exception(f"Handler error for {method}")
                return self.protocol.error_response(
                    request_id, -32603, f"Internal error: {e}"
                )
            except Exception as e:
                logger.exception(f"Unexpected handler error for {method}")
                return self.protocol.error_response(
                    request_id, -32603, f"Internal error: {type(e).__name__}"
                )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.exception("Server handle error")
            return self.protocol.error_response(None, -32600, str(e))
        except Exception as e:
            logger.exception("Unexpected server handle error")
            return self.protocol.error_response(None, -32603, type(e).__name__)

    def send_notification(self, method: str, params: Optional[dict] = None):
        """发送进度通知到 stdout"""
        notification = self.protocol.notification(method, params)
        self._write_to_stdout(notification)

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

    def _handle_and_respond(self, request: dict):
        """在线程池中处理单个请求并返回响应"""
        try:
            response = self.handle(request)
            if response:
                self._write_to_stdout(response)
        except Exception as e:
            logger.exception("Error processing request in thread pool")

    def run(self):
        """运行服务端主循环（带大 payload 保护 - M4）"""
        self._running = True
        logger.info("IPC Server started, listening on stdin...")

        MAX_LINE_SIZE = 50 * 1024 * 1024  # 50MB 硬上限，防止内存爆炸

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            if len(line) > MAX_LINE_SIZE:
                logger.error(f"[IPC] 收到超大消息 ({len(line)} bytes)，已丢弃以保护稳定性")
                error_response = self.protocol.error_response(
                    None, -32603, "Payload too large (max 50MB)"
                )
                self._write_to_stdout(error_response)
                continue

            try:
                request = json.loads(line)
                # 提交到线程池并发执行
                self._executor.submit(self._handle_and_respond, request)

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}, raw data (truncated): {line[:300]}...")
                error_response = self.protocol.error_response(
                    None, -32600, f"Parse error: {e}"
                )
                self._write_to_stdout(error_response)

            except Exception as e:
                logger.exception("Server loop error")
                error_response = self.protocol.error_response(
                    None, -32603, f"{type(e).__name__}: {str(e)[:200]}"
                )
                self._write_to_stdout(error_response)

        self._running = False
        logger.info("IPC Server stopped")

    def stop(self):
        """停止服务端并关闭线程池"""
        self._running = False
        self._executor.shutdown(wait=False)
