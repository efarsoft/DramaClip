"""服务日志轮转落盘：rotating file handler（10MB × 5 份）。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_file_logging(logs_dir: Path) -> Path | None:
    """挂接 root logger 的轮转文件 handler，返回日志文件路径。"""
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "backend.log"
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s - %(message)s")
        )
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        return log_file
    except OSError:
        return None
