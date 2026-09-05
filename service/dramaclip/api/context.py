"""api 层共享上下文（依赖注入容器，docs/service/01 §4）。"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from dramaclip.engines.analysis.runtime import AnalysisRuntime
from dramaclip.infra import config, jobs
from dramaclip.transport.notify import Notifier


@dataclass
class AppContext:
    """build_router 与各命名空间共享的运行时依赖。"""

    conn: sqlite3.Connection
    settings: config.Settings
    notifier: Notifier
    executor: ThreadPoolExecutor
    job_store: jobs.JobStore
    analysis_runtime: AnalysisRuntime
    work_dir: Path  # 分析工作目录（<data>/cache/analysis）
    cancel_events: dict[str, threading.Event] = field(default_factory=dict)
