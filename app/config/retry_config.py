"""
DramaClip - 统一重试和超时配置模块

集中管理所有重试、超时、退避策略配置，确保系统稳定性。
"""

from dataclasses import dataclass
from typing import Tuple, Type
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryCallState,
)
import requests


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3              # 最大重试次数
    wait_multiplier: float = 1.0       # 退避乘数
    wait_min: float = 4.0              # 最小等待时间（秒）
    wait_max: float = 30.0             # 最大等待时间（秒）
    retry_exceptions: Tuple[Type[Exception], ...] = (
        requests.exceptions.RequestException,
        ConnectionError,
        TimeoutError,
    )  # 需要重试的异常类型


@dataclass
class TimeoutConfig:
    """超时配置（秒）"""
    # API 调用超时
    llm_api: int = 120                 # LLM API 调用超时
    llm_text: int = 180                # LLM 文本生成超时
    
    # 视频处理超时
    ffmpeg_short: int = 30             # FFmpeg 短操作超时
    ffmpeg_medium: int = 120           # FFmpeg 中等操作超时
    ffmpeg_long: int = 300             # FFmpeg 长操作超时
    ffmpeg_merge: int = 600            # FFmpeg 合并操作超时
    
    # 下载超时
    download_connect: int = 30         # 下载连接超时
    download_read: int = 60            # 下载读取超时
    model_download: int = 600          # 模型下载超时
    
    # 视频分析超时
    frame_extract: int = 30            # 帧提取超时
    scene_detect: int = 120            # 场景检测超时


# ============================================================================
# 预定义配置实例
# ============================================================================

# 默认重试配置
DEFAULT_RETRY = RetryConfig()

# API 重试配置（更激进的重试策略）
API_RETRY = RetryConfig(
    max_attempts=5,
    wait_multiplier=2.0,
    wait_min=4.0,
    wait_max=60.0,
)

# 关键操作重试配置（更多重试次数）
CRITICAL_RETRY = RetryConfig(
    max_attempts=5,
    wait_multiplier=1.5,
    wait_min=2.0,
    wait_max=30.0,
)

# 快速重试配置（用于非关键操作）
QUICK_RETRY = RetryConfig(
    max_attempts=2,
    wait_multiplier=1.0,
    wait_min=1.0,
    wait_max=5.0,
)

# 默认超时配置
DEFAULT_TIMEOUT = TimeoutConfig()


# ============================================================================
# 装饰器工厂函数
# ============================================================================

def create_retry_decorator(config: RetryConfig = None):
    """
    创建重试装饰器
    
    Args:
        config: 重试配置，如果为 None 则使用默认配置
        
    Returns:
        重试装饰器
        
    Example:
        @create_retry_decorator(API_RETRY)
        async def call_api():
            ...
    """
    if config is None:
        config = DEFAULT_RETRY
    
    return retry(
        stop=stop_after_attempt(config.max_attempts),
        wait=wait_exponential(
            multiplier=config.wait_multiplier,
            min=config.wait_min,
            max=config.wait_max,
        ),
        retry=retry_if_exception_type(config.retry_exceptions),
        reraise=True,
    )


def create_api_retry_decorator():
    """创建 API 专用重试装饰器"""
    return create_retry_decorator(API_RETRY)


def create_critical_retry_decorator():
    """创建关键操作重试装饰器"""
    return create_retry_decorator(CRITICAL_RETRY)


def create_quick_retry_decorator():
    """创建快速重试装饰器"""
    return create_retry_decorator(QUICK_RETRY)


# ============================================================================
# 重试回调函数
# ============================================================================

def log_retry_attempt(retry_state: RetryCallState):
    """记录重试尝试的日志"""
    from loguru import logger
    
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        f"重试 #{retry_state.attempt_number} | "
        f"函数: {retry_state.fn.__name__ if retry_state.fn else 'unknown'} | "
        f"异常: {exception}"
    )


# ============================================================================
# 工具函数
# ============================================================================

def get_timeout(category: str, operation: str = None) -> int:
    """
    获取超时配置
    
    Args:
        category: 配置类别（llm, ffmpeg, download, video）
        operation: 具体操作名称（可选）
        
    Returns:
        超时时间（秒）
    """
    timeout = DEFAULT_TIMEOUT
    
    timeouts = {
        "llm": timeout.llm_api,
        "llm_text": timeout.llm_text,
        "ffmpeg": timeout.ffmpeg_medium,
        "ffmpeg_short": timeout.ffmpeg_short,
        "ffmpeg_long": timeout.ffmpeg_long,
        "ffmpeg_merge": timeout.ffmpeg_merge,
        "download": timeout.download_read,
        "model_download": timeout.model_download,
        "frame_extract": timeout.frame_extract,
        "scene_detect": timeout.scene_detect,
    }
    
    return timeouts.get(category, timeout.llm_api)


def is_retryable_exception(exception: Exception) -> bool:
    """
    判断异常是否可重试
    
    Args:
        exception: 异常对象
        
    Returns:
        是否可重试
    """
    retryable_types = (
        requests.exceptions.RequestException,
        ConnectionError,
        TimeoutError,
        OSError,
    )
    
    # 排除编程错误
    non_retryable_types = (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    )
    
    if isinstance(exception, non_retryable_types):
        return False
    
    return isinstance(exception, retryable_types)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "RetryConfig",
    "TimeoutConfig",
    "DEFAULT_RETRY",
    "API_RETRY",
    "CRITICAL_RETRY",
    "QUICK_RETRY",
    "DEFAULT_TIMEOUT",
    "create_retry_decorator",
    "create_api_retry_decorator",
    "create_critical_retry_decorator",
    "create_quick_retry_decorator",
    "log_retry_attempt",
    "get_timeout",
    "is_retryable_exception",
]
