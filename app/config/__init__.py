import os
import sys

from loguru import logger

from app.config.unified_config import config
from app.utils import utils


def __init_logger():
    """初始化日志配置"""
    _lvl = config.get("log_level", "DEBUG")
    root_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )

    def format_record(record):
        """格式化日志记录"""
        file_path = record["file"].path
        relative_path = os.path.relpath(file_path, root_dir)
        record["file"].path = f"./{relative_path}"
        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    def log_filter(record):
        """过滤不必要的日志消息"""
        ignore_patterns = [
            "已注册模板过滤器",
            "已注册提示词",
            "注册视觉模型提供商",
            "注册文本模型提供商",
            "LLM服务提供商注册",
            "FFmpeg支持的硬件加速器",
            "硬件加速测试优先级",
            "硬件加速方法",
        ]

        if record["level"].name == "DEBUG":
            return not any(pattern in record["message"] for pattern in ignore_patterns)

        return True

    logger.remove()

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
        filter=log_filter
    )


__init_logger()
