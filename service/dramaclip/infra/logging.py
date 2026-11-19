"""服务日志轮转落盘：rotating file handler（10MB × 5 份）+ stdout 镜像。

文件是诊断真源（用户反馈可发），stdout 镜像保 dev 终端直读。重复挂载
guard：warm 重启/多次初始化不会叠出双份行。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s - %(message)s"


def _has_stream_handler(root: logging.Logger) -> bool:
    return any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )


def setup_file_logging(logs_dir: Path) -> Path | None:
    """挂接 root logger 的轮转文件 handler，返回日志文件路径。

    重入安全：已挂过的 handler 不重复 add（warm 重启/多次初始化不叠双份行）。
    stdout 镜像与文件同 formatter——dev 终端与日志面板看到同一套行文。
    """
    root = logging.getLogger()
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "backend.log"
        if not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
        ):
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(file_handler)
        if not _has_stream_handler(root):
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(stream_handler)
        root.setLevel(logging.INFO)
        return log_file
    except OSError:
        return None
