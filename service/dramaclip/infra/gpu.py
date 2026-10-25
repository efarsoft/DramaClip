"""GPU 探测：Windows CIM 枚举厂商 + nvidia-smi 补 CUDA 细节，宽容判定 + 会话缓存 + 启动预热。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading

from dramaclip.infra import d3d_probe

_CUDA_RE = re.compile(r"CUDA(?:\s+UMD)?\s+Version\s*:\s*(\d+(?:\.\d+)?)", re.I)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_LOCK = threading.Lock()
_CACHE: dict[str, object] | None = None
_PENDING = False


def _smi_paths() -> list[str]:
    candidates = [
        shutil.which("nvidia-smi") or "",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    return [c for c in candidates if c]


def _run(path: str, args: list[str], timeout: float) -> str:
    result = subprocess.run(  # noqa: S603 - 固定路径固定参数
        [path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    return result.stdout


def parse_query_output(output: str) -> tuple[str, str]:
    """解析 --query-gpu=name,driver_version 输出首行 → (显卡名, 驱动版本)。"""
    lines = [line for line in output.strip().splitlines() if line.strip()]
    if not lines:
        return "", ""
    parts = [part.strip() for part in lines[0].split(",")]
    return (parts[0] if len(parts) > 0 else "", parts[1] if len(parts) > 1 else "")


def parse_max_cuda(output: str) -> str:
    """从 nvidia-smi 裸输出解析驱动支持的最高 CUDA 版本（兼容 UMD 改名）。"""
    match = _CUDA_RE.search(output)
    return match.group(1) if match else ""


_VIRTUAL_MARKERS = (
    "microsoft basic display",
    "microsoft basic render",
    "microsoft remote display",
    "microsoft hyper-v video",
    "vmware",
    "virtualbox",
    "parsec",
    "citrix",
    "virtual display",
    "mirage",
)
# 顺序即优先级：名称里同时出现两家厂商时先匹配到的赢（NVIDIA 的营销名不会带 AMD/Intel 前缀）
_VENDOR_MATCHES = (
    ("nvidia", ("nvidia", "geforce", "quadro", "tesla", "rtx", "gtx")),
    ("amd", ("amd", "radeon", "ati")),
    ("intel", ("intel",)),
)
_VENDOR_ORDER = ("nvidia", "amd", "intel", "other")


def classify_vendor(name: str, vendor_id: int | None = None) -> str:
    """认厂商：PCI 厂商 ID（D3D 层采集）优先，名称 token 兜底；认不出归 other。

    宁可不归功，也不冒充 NVIDIA。
    """
    if vendor_id is not None:
        mapped = d3d_probe._PCI_VENDOR_NAMES.get(vendor_id)
        if mapped:
            return mapped
    lowered = (name or "").lower()
    for vendor, tokens in _VENDOR_MATCHES:
        if any(token in lowered for token in tokens):
            return vendor
    return "other"


def is_virtual_adapter(name: str) -> bool:
    """虚拟/基础显示设备不是显卡：远程桌面、投屏工具都会往 CIM 里塞一条。"""
    lowered = (name or "").lower()
    return any(marker in lowered for marker in _VIRTUAL_MARKERS)


def parse_cim_output(raw: str) -> list[dict[str, str]]:
    """CIM 的 ConvertTo-Json 输出 → 适配器清单；非法 JSON 抛 ValueError 由上层吞掉。

    单台适配器时 PowerShell 输出对象而非数组，两种形状都要吃；BOM 会让 json.loads 直接失败。
    """
    if not raw or not raw.strip():
        return []
    data = json.loads(raw.lstrip("\ufeff").strip())
    items = data if isinstance(data, list) else [data]
    adapters: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        if not name or is_virtual_adapter(name):
            continue
        adapters.append(
            {
                "name": name,
                "vendor": classify_vendor(name),
                "driver_version": str(item.get("DriverVersion") or "").strip(),
            }
        )
    return adapters


def choose_primary(adapters: list[dict[str, object]]) -> dict[str, object] | None:
    """主适配器按 NVIDIA > AMD > Intel > other；同级保持枚举返回顺序。"""
    for vendor in _VENDOR_ORDER:
        for adapter in adapters:
            if adapter["vendor"] == vendor:
                return adapter
    return None


_PENDING_FIELDS: dict[str, object] = {
    "ready": False,
    "vendor": "unknown",
    "name": "",
    "driver_version": "",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [],
}


_CIM_SCRIPT = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "Get-CimInstance -ClassName Win32_VideoController |"
    "Select-Object Name,DriverVersion | ConvertTo-Json -Compress"
)


def _query_cim_adapters() -> list[dict[str, str]]:
    """Windows CIM 枚举显示适配器；任何失败返回空清单，不抛错（探测不能阻塞服务）。

    只取 Name 与 DriverVersion：AdapterRAM 是 UInt32，4GB 以上的卡普遍失真，读了反而误导。
    脚本固定、无用户输入插值；命令输出不写日志，避免把主机用户名带进去。
    """
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(  # noqa: S603 - 固定命令固定参数
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _CIM_SCRIPT,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
            creationflags=_NO_WINDOW,
        )
        return parse_cim_output(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _query_nvidia_smi() -> dict[str, object] | None:
    """nvidia-smi 查询：name/driver/显存/CUDA 上限/算力；全不可用返回 None。"""
    for smi in _smi_paths():
        try:
            # compute_cap 老驱动可能不支持该字段——与常规查询分开跑，缺了不影响其余
            query = [
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ]
            head = _run(smi, query, 10.0).strip().splitlines()
            fields = [part.strip() for part in head[0].split(",")] if head else []
            name = fields[0] if len(fields) > 0 else ""
            driver = fields[1] if len(fields) > 1 else ""
            memory_total_mb = _to_int_mb(fields[2] if len(fields) > 2 else "")
            max_cuda = parse_max_cuda(_run(smi, [], 10.0))
            cap_out = _run(smi, ["--query-gpu=compute_cap", "--format=csv,noheader"], 10.0)
            compute_cap = cap_out.strip().splitlines()[0].strip() if cap_out.strip() else ""
        except (OSError, subprocess.SubprocessError):
            continue
        if not (name or driver or max_cuda):
            continue
        return {
            "name": name,
            "driver_version": driver,
            "memory_total_mb": memory_total_mb,
            "max_cuda_version": max_cuda,
            "compute_cap": compute_cap,
        }
    return None


def detect() -> dict[str, object]:
    """同步探测（阻塞，最长 ~20s）：DXGI PCI 身份 + CIM 驱动版本 + nvidia-smi CUDA 事实。

    仅由 prefetch 后台线程调用。合并规则：DXGI 可用时以它为主（厂商按 PCI ID
    精确判定 + 专用显存），CIM 按名称补驱动版本、独有适配器追加；DXGI 失败回退
    纯 CIM。虚拟设备在解析阶段剔除，smi 的 NVIDIA 条目覆盖同名项，CUDA 三项只在
    确为 NVIDIA 且 smi 可读时填充。
    """
    adapters: list[dict[str, object]] = []
    if sys.platform == "win32":
        try:
            adapters = list(_query_cim_adapters())
        except Exception:  # noqa: BLE001 - 探测不许拖垮服务：CIM 侧任何意外都当作没有适配器
            adapters = []
    d3d: list[dict[str, object]] = []
    if sys.platform == "win32":
        try:
            d3d = list(d3d_probe.enumerate_adapters())
        except Exception:  # noqa: BLE001 - DXGI/COM 任何意外都回退 CIM 路径
            d3d = []
    if d3d:
        by_name = {str(a["name"]).lower(): a for a in adapters}
        merged: list[dict[str, object]] = []
        for item in d3d:
            name = str(item["name"])
            if (
                not name
                or item.get("is_software")
                or item.get("is_virtual")
                or is_virtual_adapter(name)
            ):
                continue
            row: dict[str, object] = {
                "name": name,
                "vendor": classify_vendor(name, _to_int_maybe(item["vendor_id"])),
                "driver_version": "",
                "vendor_id": item["vendor_id"],
                "device_id": item["device_id"],
                "dedicated_video_mb": item["dedicated_video_mb"],
            }
            cim = by_name.pop(name.lower(), None)
            if cim is not None:
                row["driver_version"] = cim["driver_version"]
            merged.append(row)
        for cim in by_name.values():
            merged.append(dict(cim))
        adapters = merged
    smi = _query_nvidia_smi()
    if smi is not None:
        nvidia_name = str(smi["name"]) or ""
        nvidia_driver = str(smi["driver_version"]) or ""
        existing = next((item for item in adapters if item["vendor"] == "nvidia"), None)
        if existing is None:
            adapters.insert(
                0, {"name": nvidia_name, "vendor": "nvidia", "driver_version": nvidia_driver}
            )
        else:
            existing["driver_version"] = nvidia_driver
            if nvidia_name:
                existing["name"] = nvidia_name

    primary = choose_primary(adapters)
    vendor = primary["vendor"] if primary else "none"
    smi_nvidia = smi if smi is not None and vendor == "nvidia" else None
    return {
        "ready": True,
        "vendor": vendor,
        "name": primary["name"] if primary else "",
        "driver_version": primary["driver_version"] if primary else "",
        "max_cuda_version": str(smi_nvidia["max_cuda_version"]) if smi_nvidia else "",
        "memory_total_mb": int(str(smi_nvidia["memory_total_mb"])) if smi_nvidia else 0,
        "compute_cap": str(smi_nvidia["compute_cap"]) if smi_nvidia else "",
        "adapters": adapters,
    }


def _to_int_mb(raw: str) -> int:
    digits = re.sub(r"[^0-9]", "", raw)
    return int(digits) if digits else 0


def _to_int_maybe(raw: object) -> int | None:
    """「0x8086」形态的十六进制串 → int；非串/解析失败 → None。"""
    try:
        return int(str(raw), 16) if str(raw).startswith("0x") else int(str(raw))
    except (TypeError, ValueError):
        return None


def snapshot(force: bool = False) -> dict[str, object]:
    """非阻塞取缓存；force=True 丢弃缓存重新探测。未就绪则后台补测并返回待定态。"""
    global _CACHE
    with _LOCK:
        if force:
            _CACHE = None
        if _CACHE is not None:
            return dict(_CACHE)
    prefetch()
    return dict(_PENDING_FIELDS)


def snapshot_sync() -> dict[str, object]:
    """同步探测并落缓存（阻塞最长 ~20s）：安装器等一次性进程没有后台线程可等，
    阻塞换事实——非阻塞快照在裸进程里只会拿到「探测中」占位。"""
    global _CACHE, _PENDING
    with _LOCK:
        result = detect()
        _CACHE = dict(result)
        _PENDING = False
        return dict(result)


def prefetch() -> None:
    """后台预热/刷新探测缓存（幂等，进行中不重复开线程）。"""
    global _PENDING

    def _work() -> None:
        global _CACHE, _PENDING
        try:
            result = detect()
        except Exception:  # noqa: BLE001 - 探测失败保持未就绪，下次再测
            return
        finally:
            with _LOCK:
                _PENDING = False
        with _LOCK:
            _CACHE = result

    with _LOCK:
        if _PENDING:
            return
        _PENDING = True
    threading.Thread(target=_work, name="gpu-detect", daemon=True).start()
