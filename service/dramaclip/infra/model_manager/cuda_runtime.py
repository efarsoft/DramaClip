"""CUDA 推理运行库（cuBLAS/cuDNN）：下载、解压落位、DLL 目录注入。

刻意不 pip 进 venv：wheel 解压出 DLL 落到 data/models/cuda/<name>/，
dev 与 PyInstaller 打包两态通用（打包态 venv 冻结，pip 不可用）。
服务启动时 inject_dll_dirs() 早于 ctranslate2 首次加载即生效。
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager.fetch import _UA, download_file, fetch_json

# 钉版本：ctranslate2 4.x 配 cu12；这对组合在 CTranslate2 官方矩阵内。
_PACKAGES = [
    {"name": "cublas", "pkg": "nvidia-cublas-cu12", "version": "12.4.5.8",
     "dll": "cublas64_12.dll"},
    {"name": "cudnn", "pkg": "nvidia-cudnn-cu12", "version": "9.1.0.70",
     "dll": "cudnn64_9.dll"},
]

_PYPI = "https://pypi.org"
_MIRRORS = (
    "https://pypi.tuna.tsinghua.edu.cn",  # 清华：packages 路径与 pypi.org 一致
    "https://mirrors.aliyun.com/pypi",  # 阿里云：路径带 /pypi 前缀
)


def runtime_dir(data_dir: Path) -> Path:
    return data_dir / "models" / "cuda"


def status(data_dir: Path) -> dict[str, Any]:
    """安装态：两个 DLL 齐全才算可用（缺任一即视为未装完）。"""
    root = runtime_dir(data_dir)
    parts = {p["name"]: (root / p["name"] / p["dll"]).is_file() for p in _PACKAGES}
    return {**parts, "installed": all(parts.values())}


def inject_dll_dirs(data_dir: Path) -> int:
    """服务启动调用：把已安装的 DLL 目录加入进程搜索路径。返回注入数。"""
    root = runtime_dir(data_dir)
    injected = 0
    for p in _PACKAGES:
        d = (root / p["name"]).resolve()
        if d.is_dir():
            os.add_dll_directory(str(d))
            injected += 1
    return injected


def _wheel_meta(pkg: str, version: str) -> dict[str, Any]:
    """取 win_amd64 wheel 的 {url, size}：清华 simple 索引直取（国内可达），
    pypi.org JSON API 仅兜底——其 DNS 在国内网络常挂起且 socket 超时管不到。
    wheel 文件名用规范化下划线包名；镜像 href 带 #sha256 锚点与相对路径。"""
    filename = f"{pkg.replace('-', '_')}-{version}-py3-none-win_amd64.whl"
    simple = f"{_MIRRORS[0]}/simple/{pkg}/"
    try:
        req = urllib.request.Request(simple, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        match = re.search(r'href="([^"]*' + re.escape(filename) + r'[^"]*)"', text)
        if match:
            url = urllib.parse.urljoin(simple, match.group(1))
            return {"url": url, "size": _content_length(url), "filename": filename}
    except Exception:  # noqa: BLE001 - 镜像失败落 pypi.org 兜底
        pass
    data: dict[str, Any] = json.loads(
        json.dumps(fetch_json(f"{_PYPI}/pypi/{pkg}/{version}/json"))
    )
    for item in data.get("urls", []):
        name = str(item.get("filename", ""))
        if name.endswith(".whl") and "win_amd64" in name:
            return {"url": str(item["url"]), "size": int(item["size"]), "filename": name}
    raise ValueError(f"{pkg} {version} 无 win_amd64 wheel")


def _content_length(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return int(resp.headers.get("Content-Length") or 0)


def _mirror_url(url: str, mirror: str) -> str:
    """pypi.org 的 /packages/ 路径在镜像站同构：清华直接换域，阿里云带 /pypi 前缀。"""
    marker = "https://pypi.org/packages/"
    if url.startswith(marker):
        tail = url[len(marker):]
        return f"{mirror}/packages/{tail}"
    return url


def _make_progress(idx: int, size: int, total: int, on_progress: Any) -> Any:
    """单包进度折算全任务百分比。"""
    def _cb(done: int) -> None:
        if on_progress:
            on_progress(int((idx + done / size) * 100 / total))
    return _cb


def install(
    data_dir: Path,
    *,
    cancel: threading.Event,
    on_progress: Any | None = None,
) -> None:
    """下载两个 wheel（多镜像容错）→ 解压 DLL → 清理。可重入：已存在的包跳过。"""
    root = runtime_dir(data_dir)
    total = len(_PACKAGES)
    for idx, pkg in enumerate(_PACKAGES):
        target = root / pkg["name"]
        if (target / pkg["dll"]).is_file():
            continue
        meta = _wheel_meta(pkg["pkg"], pkg["version"])
        wheel = Path(meta["filename"])
        last_error: Exception | None = None
        for mirror in ("https://pypi.tuna.tsinghua.edu.cn", _PYPI):
            if cancel.is_set():
                raise RuntimeError("已取消")
            try:
                download_file(
                    _mirror_url(meta["url"], mirror),
                    root / wheel.name,
                    meta["size"],
                    cancel=cancel,
                    on_progress=_make_progress(idx, meta["size"], total, on_progress),
                )
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - 镜像容错
                last_error = exc
        if last_error is not None:
            raise RuntimeError(f"{pkg['pkg']} 下载失败: {last_error}") from last_error
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(root / wheel.name) as zf:
            for item in zf.namelist():
                if item.endswith(".dll"):
                    (target / Path(item).name).write_bytes(zf.read(item))
        (root / wheel.name).unlink()
    if on_progress is not None:
        on_progress(100)


def injected_hint(data_dir: Path) -> str:
    return "; ".join(str(d) for d in [runtime_dir(data_dir)] if d.is_dir())
