"""llama.cpp 视觉轨二进制的资产登记与一键下载（0.2.5 主题一 1.1）。

落位 = ``data/tools/llama.cpp/``（llama_device.server_exe 的唯一解析点）。
变体按显卡自动选：N 卡 → CUDA 12.4 构建 + CUDA 运行库两包；其余 → CPU 构建
（视觉走 CPU，慢但可用；Vulkan 变体对测与 CPU 持平，暂不入册）。

SHA256/字节数按 tag 钉死（GitHub 资产自带 digest，登记时抄录；b 系 tag 的资产
字节确定，跨构建不变）。下载双源：GitHub 直连 + gh-proxy 代理（真机 2026-11-13：
gh-proxy 连通性显著好于直连）。解压剥一层仓库前缀后**扁平化**到工具目录根——
llama-server.exe 与随包 DLL 必须同层（Windows DLL 搜索含 exe 所在目录）。
"""

from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from dramaclip.infra import gpu
from dramaclip.infra.model_manager.fetch import download_file
from dramaclip.infra.model_manager.tts_runtime import _member_parts

LLAMA_TAG = "b12376"
_DOWNLOAD_ROOT = "https://github.com/ggml-org/llama.cpp/releases/download"
_PROXY_PREFIX = "https://gh-proxy.com/"

SERVER_REL = Path("tools") / "llama.cpp" / "llama-server.exe"
_MARKER = "llama.cpp.asset.json"

_Asset = tuple[str, int, str]  # (归档文件名, 精确字节数, sha256)

_CUDA_ZIPS: tuple[_Asset, ...] = (
    (
        "llama-b12376-bin-win-cuda-12.4-x64.zip",
        319401664,
        "4797397130a64965024088d1da1464b029553bf1ecbd3ea8da1d7e09bad7f01a",
    ),
    (
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        391443627,
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    ),
)
_CPU_ZIPS: tuple[_Asset, ...] = (
    (
        "llama-b12376-bin-win-cpu-x64.zip",
        25116197,
        "f685542d9bec82679a15ceeb10c339fe3b6040e95dfcd384907bf69dc64e9c2b",
    ),
)


def tool_dir(data_dir: Path) -> Path:
    return data_dir / "tools" / "llama.cpp"


def server_exe(data_dir: Path) -> Path:
    return tool_dir(data_dir) / "llama-server.exe"


def installed(data_dir: Path) -> bool:
    return server_exe(data_dir).is_file()


def marker_state(data_dir: Path) -> dict[str, Any]:
    """已装标记：tag/variant/文件清单（无标记=旧手动放置，如实 unknown）。"""
    marker = tool_dir(data_dir) / _MARKER
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"tag": "", "variant": "", "files": []}
    if not isinstance(data, dict):
        return {"tag": "", "variant": "", "files": []}
    return {
        "tag": str(data.get("tag") or ""),
        "variant": str(data.get("variant") or ""),
        "files": [str(f) for f in data.get("files") or [] if isinstance(f, str)],
    }


def variant_for(adapters: list[dict[str, Any]] | None) -> str:
    """N 卡在场 → cuda124；其余（无卡/AMD/Intel）→ cpu（视觉走 CPU）。"""
    for adapter in adapters or []:
        if isinstance(adapter, dict) and str(adapter.get("vendor") or "") == "nvidia":
            return "cuda124"
    return "cpu"


def assets_for(variant: str) -> tuple[_Asset, ...]:
    return _CUDA_ZIPS if variant == "cuda124" else _CPU_ZIPS


def _sources_for(name: str) -> list[str]:
    tail = f"/{name}"
    base = f"{_DOWNLOAD_ROOT}/{LLAMA_TAG}{tail}"
    return [f"{_PROXY_PREFIX}{base}", base]


def _extract_zip_flat(archive: Path, dest: Path) -> list[str]:
    """剥一层仓库前缀 + 扁平化：全部文件落 dest 根（llama-server 与随包 DLL 同层）。

    成员名属于外部输入：越界/绝对路径沿用解包形状闸当场拒；文件成员一律提到
    dest 根（cudart 包存在根级与带前缀两种布局，都归一到根）。
    """
    landed: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            _member_parts(member.filename)
            if member.is_dir():
                continue
            rel = (
                member.filename.split("/", 1)[1]
                if "/" in member.filename
                else member.filename
            )
            target = dest.joinpath(_member_parts(rel)[-1])  # 扁平化：只保留文件名
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
            if target.name not in landed:
                landed.append(target.name)
    return landed


def install(
    data_dir: Path,
    *,
    cancel: threading.Event,
    on_progress: Any | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """按变体下载双包（CPU 一包）→ 解压扁平落位 → 写标记。返回 {dir, variant, tag}。"""
    if variant is None:
        adapters = gpu.snapshot_sync().get("adapters") or []
        variant = variant_for(adapters if isinstance(adapters, list) else [])
    if variant not in ("cuda124", "cpu"):
        raise RuntimeError(f"未知变体：{variant}")
    assets = assets_for(variant)
    dest = tool_dir(data_dir)
    dest.mkdir(parents=True, exist_ok=True)

    total = sum(size for _n, size, _s in assets)
    done = 0

    def _report(position: int, name: str) -> None:
        if on_progress is None:
            return
        percent = (done + position) / total * 95
        on_progress(percent, f"下载 {name}")

    landed: list[str] = []
    for index, (name, size, sha) in enumerate(assets):
        archive = dest / name
        last: Exception | None = None
        for url in _sources_for(name):
            if cancel.is_set():
                raise RuntimeError("已取消")
            try:
                download_file(url, archive, size, expected_sha256=sha, cancel=cancel)
                last = None
                break
            except Exception as exc:  # noqa: BLE001 - 双源容错
                last = exc
        if last is not None:
            raise RuntimeError(f"{name} 全部源下载失败: {last}") from last
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                _member_parts(member.filename)
        done += size
        landed.extend(_extract_zip_flat(archive, dest))
        archive.unlink(missing_ok=True)
        if on_progress is not None:
            on_progress(min(95.0, (index + 1) / len(assets) * 95), f"解压 {name}")
        if cancel.is_set():
            raise RuntimeError("已取消")

    if not (dest / "llama-server.exe").is_file():
        raise RuntimeError("解压后未找到 llama-server.exe——归档形状变了，需要更新资产登记")

    marker = {"tag": LLAMA_TAG, "variant": variant, "files": sorted(set(landed))}
    (dest / _MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=1), encoding="utf-8")
    if on_progress is not None:
        on_progress(100.0, "完成")
    return {"dir": str(dest), "variant": variant, "tag": LLAMA_TAG}
