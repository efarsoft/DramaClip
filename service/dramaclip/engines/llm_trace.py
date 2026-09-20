"""LLM 往返留痕（规格 §9.4）：把真正发出去的 prompt 与原始响应落成文件。

只在能拿到往返的地方落盘：没发请求就不写文件，留一个空壳等于伪造证据。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def trace_path(trace_dir: Path | None, name: str) -> Path | None:
    """留痕文件的唯一拼法：未给目录即不留痕。"""
    if trace_dir is None:
        return None
    return Path(trace_dir) / name


def dump_trace(path: Path | None, payload: dict[str, Any]) -> None:
    """写 system/user/原始响应；盘写不下不影响出片，留痕尽力而为。"""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass
