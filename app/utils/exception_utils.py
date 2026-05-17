"""
DramaClip - 异常处理工具模块

提供统一的异常处理模式，避免重复代码。
"""

from typing import Type, Callable, Any, Optional
from loguru import logger
import functools
import subprocess


def safe_execute(
    func: Callable,
    *args,
    default: Any = None,
    log_message: str = None,
    log_level: str = "debug",
    raise_on: tuple[Type[Exception], ...] = None,
    **kwargs,
) -> Any:
    """
    安全执行函数，捕获异常并返回默认值
    
    Args:
        func: 要执行的函数
        *args: 位置参数
        default: 异常时返回的默认值
        log_message: 异常时的日志消息
        log_level: 日志级别 (debug/info/warning/error)
        raise_on: 需要重新抛出的异常类型
        **kwargs: 关键字参数
        
    Returns:
        函数返回值或默认值
        
    Example:
        result = safe_execute(os.unlink, path, default=None, log_message="删除文件失败")
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if raise_on and isinstance(e, raise_on):
            raise
        
        if log_message:
            log_func = getattr(logger, log_level, logger.debug)
            log_func(f"{log_message}: {e}")
        
        return default


def safe_execute_with_fallback(
    primary_func: Callable,
    fallback_func: Callable,
    *args,
    log_message: str = None,
    **kwargs,
) -> Any:
    """
    安全执行函数，失败时使用备用函数
    
    Args:
        primary_func: 主函数
        fallback_func: 备用函数
        *args: 位置参数
        log_message: 异常时的日志消息
        **kwargs: 关键字参数
        
    Returns:
        主函数或备用函数的返回值
        
    Example:
        result = safe_execute_with_fallback(
            os.unlink, 
            lambda: None,  # 空操作
            path,
            log_message="删除文件失败，跳过"
        )
    """
    try:
        return primary_func(*args, **kwargs)
    except Exception as e:
        if log_message:
            logger.debug(f"{log_message}: {e}")
        return fallback_func(*args, **kwargs)


def suppress_errors(
    log_message: str = None,
    log_level: str = "debug",
    raise_on: tuple[Type[Exception], ...] = None,
):
    """
    装饰器：抑制函数异常
    
    Args:
        log_message: 异常时的日志消息
        log_level: 日志级别
        raise_on: 需要重新抛出的异常类型
        
    Example:
        @suppress_errors(log_message="清理临时文件失败")
        def cleanup():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if raise_on and isinstance(e, raise_on):
                    raise
                
                if log_message:
                    log_func = getattr(logger, log_level, logger.debug)
                    log_func(f"{log_message}: {e}")
                
                return None
        return wrapper
    return decorator


# ============================================================================
# 常用异常类型组合
# ============================================================================

# 文件操作可能抛出的异常
FILE_EXCEPTIONS = (FileNotFoundError, PermissionError, OSError, IOError)

# 子进程可能抛出的异常
SUBPROCESS_EXCEPTIONS = (subprocess.SubprocessError, OSError, TimeoutError)

# 网络请求可能抛出的异常
NETWORK_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "safe_execute",
    "safe_execute_with_fallback",
    "suppress_errors",
    "FILE_EXCEPTIONS",
    "SUBPROCESS_EXCEPTIONS",
    "NETWORK_EXCEPTIONS",
]
