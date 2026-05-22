"""
统一异常处理模块
P0 核心：提供全局异常捕获、日志记录、用户友好提示

功能：
1. 全局异常捕获装饰器
2. 统一错误码到用户提示的映射
3. 错误日志分级记录
4. 错误恢复建议
"""

import functools
import traceback
from typing import Any, Callable, Optional, Type, Union
from loguru import logger

from app.ipc.protocol import RPCError


class AppError(Exception):
    """
    应用级异常基类

    支持错误码和用户友好消息
    """

    def __init__(
        self,
        message: str,
        code: int = -32000,
        details: Optional[Any] = None,
        recoverable: bool = True,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        self.recoverable = recoverable

    def to_rpc_error(self) -> RPCError:
        """转换为 RPC 错误"""
        return RPCError(self.code, self.message, self.details)

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} | Details: {self.details}"
        return f"[{self.code}] {self.message}"


class ValidationError(AppError):
    """验证错误"""

    def __init__(self, message: str, details: Any = None):
        super().__init__(message, code=-32602, details=details, recoverable=True)


class NotFoundError(AppError):
    """资源未找到错误"""

    def __init__(self, resource: str, identifier: str = ""):
        message = f"{resource} 未找到"
        if identifier:
            message += f": {identifier}"
        super().__init__(message, code=-32002, details={"resource": resource, "id": identifier}, recoverable=False)


class PermissionError(AppError):
    """权限错误"""

    def __init__(self, action: str, reason: str = ""):
        message = f"权限不足: {action}"
        if reason:
            message += f" ({reason})"
        super().__init__(message, code=-32003, recoverable=False)


class ResourceError(AppError):
    """资源相关错误（文件、内存、磁盘等）"""

    def __init__(self, message: str, resource_type: str = "resource", details: Any = None):
        super().__init__(
            message,
            code=-32002,
            details={"type": resource_type, **(details or {})},
            recoverable=False,
        )


class ServiceError(AppError):
    """服务调用错误（LLM、FFmpeg 等）"""

    def __init__(self, service: str, message: str, details: Any = None):
        full_message = f"{service} 服务错误: {message}"
        super().__init__(
            full_message,
            code=-32000,
            details={"service": service, **(details or {})},
            recoverable=True,
        )


class TimeoutError(AppError):
    """超时错误"""

    def __init__(self, operation: str, timeout_seconds: int = 60):
        message = f"{operation} 超时 (>{timeout_seconds}s)"
        super().__init__(
            message,
            code=-32004,
            details={"operation": operation, "timeout": timeout_seconds},
            recoverable=True,
        )


# ==================== 用户友好提示映射 ====================

ERROR_HINTS = {
    # 文件相关
    -32002: {
        "short": "文件未找到",
        "hint": "请检查文件路径是否正确，或重新导入视频文件",
    },
    -32003: {
        "short": "权限不足",
        "hint": "请以管理员身份运行，或检查文件权限设置",
    },
    # 项目相关
    -32101: {
        "short": "项目不存在",
        "hint": "请先创建项目或导入已有项目",
    },
    -32102: {
        "short": "项目已存在",
        "hint": "请使用现有项目或更改项目名称",
    },
    # 分析相关
    -32201: {
        "short": "语音识别失败",
        "hint": "请检查音频文件是否完整，或尝试更换模型",
    },
    -32202: {
        "short": "不支持的视频格式",
        "hint": "支持的格式: MP4, AVI, MKV, MOV，请转换后重试",
    },
    # 剪辑相关
    -32301: {
        "short": "高光片段不足",
        "hint": "请调整高光检测参数或选择更多视频片段",
    },
    -32302: {
        "short": "语音合成失败",
        "hint": "请检查网络连接或 API 配置",
    },
    # 导出相关
    -32401: {
        "short": "视频导出失败",
        "hint": "请检查磁盘空间是否充足，或尝试降低输出质量",
    },
    -32402: {
        "short": "磁盘空间不足",
        "hint": "请清理临时文件或释放磁盘空间",
    },
    # JSON-RPC 标准错误
    -32600: {
        "short": "无效请求",
        "hint": "请刷新页面后重试",
    },
    -32601: {
        "short": "功能不可用",
        "hint": "请联系技术支持",
    },
    -32602: {
        "short": "参数错误",
        "hint": "请检查输入参数是否正确",
    },
    -32603: {
        "short": "服务端错误",
        "hint": "请稍后重试",
    },
    # 通用
    -32000: {
        "short": "操作失败",
        "hint": "请稍后重试，如问题持续存在请联系技术支持",
    },
    -32001: {
        "short": "服务未就绪",
        "hint": "请重启应用",
    },
    -32004: {
        "short": "操作超时",
        "hint": "请检查网络连接或减少操作规模后重试",
    },
}


def get_error_hint(code: int) -> dict:
    """获取错误提示"""
    return ERROR_HINTS.get(code, {
        "short": "未知错误",
        "hint": "请稍后重试",
    })


# ==================== 异常处理装饰器 ====================


def handle_errors(
    default_code: int = -32000,
    default_message: str = "操作失败",
    log_level: str = "error",
    include_traceback: bool = False,
) -> Callable:
    """
    异常处理装饰器

    用法:
        @handle_errors(default_code=-32201, default_message="分析失败")
        def analyze_video(video_path: str):
            # ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except AppError as e:
                logger.log(log_level, f"[AppError] {func.__name__}: {e}")
                raise e.to_rpc_error()
            except RPCError:
                raise
            except FileNotFoundError as e:
                error = NotFoundError("文件", str(e))
                logger.log(log_level, f"[FileNotFoundError] {func.__name__}: {e}")
                raise error.to_rpc_error()
            except PermissionError as e:
                error = PermissionError(func.__name__, str(e))
                logger.log(log_level, f"[PermissionError] {func.__name__}: {e}")
                raise error.to_rpc_error()
            except TimeoutError as e:
                logger.log(log_level, f"[TimeoutError] {func.__name__}: {e}")
                raise e.to_rpc_error()
            except Exception as e:
                error_msg = f"{default_message}: {str(e)}"
                log_msg = f"[Unhandled] {func.__name__}: {error_msg}"

                if include_traceback:
                    logger.exception(log_msg)
                else:
                    logger.log(log_level, log_msg)

                rpc_error = RPCError(
                    default_code,
                    error_msg,
                    details={
                        "function": func.__name__,
                        "traceback": traceback.format_exc() if include_traceback else None,
                    },
                )
                raise rpc_error

        return wrapper

    return decorator


def handle_errors_async(
    default_code: int = -32000,
    default_message: str = "操作失败",
    log_level: str = "error",
) -> Callable:
    """
    异步函数的异常处理装饰器

    用法:
        @handle_errors_async(default_code=-32201, default_message="分析失败")
        async def analyze_video(video_path: str):
            # ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except AppError as e:
                logger.log(log_level, f"[AppError] {func.__name__}: {e}")
                raise e.to_rpc_error()
            except RPCError:
                raise
            except Exception as e:
                error_msg = f"{default_message}: {str(e)}"
                logger.log(log_level, f"[Unhandled] {func.__name__}: {error_msg}")
                raise RPCError(
                    default_code,
                    error_msg,
                    details={"function": func.__name__},
                )

        return wrapper

    return decorator


# ==================== 全局异常处理器 ====================


class GlobalExceptionHandler:
    """
    全局异常处理器

    用于捕获未被捕获的异常
    """

    @staticmethod
    def handle_exception(exc: Exception, context: Optional[dict] = None) -> RPCError:
        """
        处理异常并返回 RPCError

        Args:
            exc: 异常对象
            context: 上下文信息

        Returns:
            RPCError 对象
        """
        context = context or {}

        if isinstance(exc, AppError):
            logger.error(f"[AppError] {exc.message}", extra=context)
            return exc.to_rpc_error()

        if isinstance(exc, RPCError):
            logger.error(f"[RPCError] {exc.code}: {exc.message}", extra=context)
            return exc

        if isinstance(exc, FileNotFoundError):
            logger.error(f"[FileNotFoundError] {exc}", extra=context)
            return RPCError(
                -32002,
                f"文件未找到: {str(exc)}",
                data={"type": "file_not_found", **context},
            )

        if isinstance(exc, PermissionError):
            logger.error(f"[PermissionError] {exc}", extra=context)
            return RPCError(
                -32003,
                f"权限不足: {str(exc)}",
                data={"type": "permission_denied", **context},
            )

        # 未知异常
        logger.exception(f"[UnhandledException] {exc}", extra=context)
        return RPCError(
            -32000,
            f"操作失败: {str(exc)}",
            data={
                "type": "unhandled",
                "exception_type": type(exc).__name__,
                "context": context,
            },
        )

    @staticmethod
    def format_error_for_user(rpc_error: RPCError) -> dict:
        """
        将 RPCError 格式化为用户友好的错误信息

        Args:
            rpc_error: RPCError 对象

        Returns:
            用户友好的错误信息字典
        """
        hint = get_error_hint(rpc_error.code)

        return {
            "code": rpc_error.code,
            "short": hint["short"],
            "message": rpc_error.message,
            "hint": hint["hint"],
            "details": rpc_error.data,
        }


# 全局实例
error_handler = GlobalExceptionHandler()


def get_error_handler() -> GlobalExceptionHandler:
    """获取全局异常处理器"""
    return error_handler
