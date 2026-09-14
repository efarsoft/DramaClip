"""数据/资源目录解析。唯一来源：DRAMACLIP_* 环境变量（由 Electron 注入）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SUBDIRS = ("models", "cache", "outputs", "logs")


def resolve_data_dir(env: dict[str, str] | None = None) -> Path:
    """解析并初始化数据目录；env 参数便于测试注入。"""
    environ = os.environ if env is None else env
    raw = environ.get("DRAMACLIP_DATA_DIR", "").strip()
    if raw:
        base = Path(raw)
    elif sys.platform == "win32":
        appdata = environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        base = Path(appdata) / "DramaClip"
    else:
        base = Path.home() / ".local" / "share" / "dramaclip"
    for name in _SUBDIRS:
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def resolve_resources_dir(env: dict[str, str] | None = None) -> Path:
    """随应用分发的只读资源根（ffmpeg/fonts/subtitle-presets）。
    """
    environ = os.environ if env is None else env
    raw = environ.get("DRAMACLIP_RESOURCES_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "resources"


def db_path(base: Path) -> Path:
    return base / "data.db"
