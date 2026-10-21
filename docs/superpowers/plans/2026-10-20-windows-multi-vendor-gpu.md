# Windows 多厂商 GPU 覆盖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把宿主 GPU 探测、视频硬编候选、设备解析入口与界面口径统一到「宿主厂商」这一事实源，让非 NVIDIA 主机在 Windows 上拿到正确的显存/文案/硬编路径，同时把 AI 推理加速的承诺收口到 CUDA-only + 三套运行时各自算力下限。

**Architecture:** 四层各归一位事实源——`infra/gpu.py` 出宿主硬件事实（CIM 枚举 + nvidia-smi 合并）；`infra/device_profile.py` 把硬件事实 + 运行时安装态合成一张能力表（`caps` 的 `ok`/`ready`/`reason`）；新增 `infra/device_resolve.py` 是引擎侧唯一的「用户意图 → 设备串」解析入口；运行时执行证据继续写既有算力账本（`jobs.compute` / `export_jobs.compute`）。前端只读 `caps` 与 `vendor`，不解析任何后端文案。

**Tech Stack:** Python 3.12/3.13（stdlib `subprocess` + PowerShell CIM，零新依赖）、pytest、ruff；Electron + React 19 + antd + TypeScript + vitest；FFmpeg 8.x 硬编试编。

**Spec:** [docs/superpowers/specs/2026-10-20-windows-multi-vendor-gpu-design.md](../specs/2026-10-20-windows-multi-vendor-gpu-design.md)（实施按 §2–§7、验收按 §8/§12；本计划逐任务论证以该文件为准）

## Global Constraints

- 不新增 Python/npm 依赖；不改打包配置、CI 工作流、依赖清单、分发形态（规格 §10 约束）。
- 不合并、不重写 `docs/05-开发路线图.md`。
- 除本计划明确要求的提交外不提交；提交只按明确路径 `git add <file>`，**禁止广域 `git add` / `git add -A` / `git add .`**。工作树里有大量同线程未提交的 P1–P3 改动，任何 `git add` 前先 `git status` 核对。
- **AI 引擎（ASR / TTS / 人声分离）的 GPU 加速只支持 NVIDIA CUDA**：不引入 DirectML / ROCm / torch-directml / CoreML（业主 2026-10-20 定则）。
- 视频硬编（AMF / QSV / NVENC）不属于 CUDA 承诺，可用性**只由真试编决定**；`h264_amf` 在开发机上的失败不作任何厂商判据。
- 机型基准是主流类别；开发机（Quadro M4000 sm_52 + Radeon RX 5500 XT + GameViewer 虚拟适配器）**只作回归，不作厂商判据、不据它调算力下限**。
- `unknown ≠ ok`、`unsupported ≠ pass`；降级必须可见（回执写明原因），禁止静默降级。
- 分支判据只读宿主事实与 `caps`，**禁止解析 `hint`/`reason`/`recommendation` 文案**（规格 §1 根因 4、§3.6、§6）。
- macOS/Linux 探测路径本批不改（规格 §2.3）。
- 每个任务收尾：新增/修改的测试先红后绿，`cd service && ../.venv/Scripts/python -m pytest tests -q` 相关目录全绿才进入下一任务；前端任务用 `cd desktop && npm run typecheck && npm test`。

## File Structure

**后端（生产）**
- `service/dramaclip/infra/gpu.py` — 宿主探测：切出 `classify_vendor` / `is_virtual_adapter` / `parse_cim_output` / `choose_primary` / `_query_cim_adapters` / `_query_nvidia_smi` 六个可测单元，`detect()` 只做合并与组装；`_PENDING_FIELDS` 增 `adapters`。（Task 1）
- `service/dramaclip/infra/device_profile.py` — 厂商分档标签与推荐、驱动三分支、`caps` 的 `reason` 与 sm_70 下限、`indextts2_gpu.ready` 真结论、`torch_variant` 入参。（Task 2）
- `service/dramaclip/api/system.py` — `health()` 把 `tts_runtime.torch_variant(data_dir)` 传给 `profile()`。（Task 2）
- `service/dramaclip/infra/device_resolve.py`（新增）— 唯一设备解析入口 `resolve()` + `DeviceResolution`。（Task 3）
- `service/dramaclip/engines/analysis/runtime.py` — `_build_transcriber` 三种本地引擎改为 `resolve`。（Task 4）
- `service/dramaclip/engines/tts/factory.py` — `create()` 的 device 由调用方意图经 `resolve` 得到（新增 `data_dir` 关键字入参）。（Task 4）
- `service/dramaclip/api/engines.py` — 自检 `_asr` / `_tts` 直连 `resolve`。（Task 4）
- `service/dramaclip/api/tts.py` — 试听 `_preview_audio` 走 `resolve`；`auto_voice` / `clean_reference` 分离设备恒 `auto` + 建 `voice_clean` 任务行。（Task 4、Task 7）
- `service/dramaclip/engines/narration/*.py` 的 `_EnginePool` — 合成设备由 resolve 决定。（Task 4）
- `service/dramaclip/engines/exporter/encoder.py` — win32 候选序加 `h264_amf`、AMF 质量参数、`_HW_ENCODERS` 增 `h264_amf`。（Task 5）
- `service/dramaclip/infra/compute.py` — 仅模块 docstring 的示例编码器清单补 `amf`。（Task 5）
- `service/dramaclip/engines/tts/auto_voice.py` — 降级链补 CPU 分离一档；清洗回执随参数进出。（Task 7）
- `service/dramaclip/engines/tts/vocal_separation.py` — 请求恒 `auto`；CUDA 试跑失败按 auto 语义完整重跑 CPU 并写原因。（Task 7）
- `service/dramaclip/api/export.py` — `_ensure_clone_voice` 的清洗报告并入导出 `reports` 账；不再传 `tts.device`。（Task 7）
- `service/dramaclip/infra/jobs.py` — 新增 `set_ref_id(job_id, ref_id)`。（Task 7）
- `protocol/schemas/tts.json` — `tts.clean_reference` / `tts.auto_voice` 的 result 增 `job_id`（契约测试只比方法名，字段级必须手工同步）。（Task 7）
- `scripts/verify_gpu_coverage.py` — `_select_hw_encoder`、`judge_actual` 接受 AMF、`_environment()` 增 `host_gpu`。（Task 6）

**前端/协议**
- `protocol/ts/index.ts` — `GpuVendor` / `GpuAdapter` / `GpuInfo.adapters` / `DeviceCap.reason` / `DeviceCaps`。（Task 8）
- `desktop/src/features/engines/machineFit.ts` — `MachineSpecs` 增 `gpu?` / `caps?`。（Task 8）
- `desktop/src/features/engines/deviceOptions.ts`（新增）— 引擎 → cap 的唯一映射与选项生成。（Task 8）
- `desktop/src/features/engines/AsrTab.tsx`、`TtsTab.tsx` — 设备选项按 machine + 所选引擎生成。（Task 8）
- `desktop/src/features/engines/GpuCard.tsx`、`MachinePanel.tsx`、`StatusBar.tsx`、`useGpuInfo.ts`、`jobMeta.ts`、`settings/sections.ts` — §6.3 文案矩阵、`gpuSummary` 删除、`voice_clean` 标签、编码器选项。（Task 9、Task 10）

**测试**
- `service/tests/infra/test_gpu_multi_vendor.py`（新）· `test_device_profile_multi_vendor.py`（新）· `test_device_resolve.py`（新）· `test_gpu_and_fallback.py`（适配）
- `service/tests/engines/test_device_resolve_wiring.py`（新）· `tests/engines/exporter/test_hw_probe.py` · `tests/engines/tts/test_auto_voice_clean.py` · `tests/test_verify_gpu_coverage.py`
- `service/tests/api/test_tts_clean_reference.py` · `test_export_voice_preflight.py`
- `desktop/src/features/engines/__tests__/deviceOptions.test.ts`（新）· `GpuCard.test.tsx`（新）· `MachinePanelEnv.test.tsx` · `desktop/src/components/layout/__tests__/StatusBar.test.tsx`（新）· `desktop/src/features/jobs/__tests__/jobMeta.test.ts` · `desktop/src/features/settings/__tests__/sections.test.ts`

---

## Task 1: 宿主探测改为 CIM + nvidia-smi 两路合并（`gpu.py`）

**Files:**
- Modify: `service/dramaclip/infra/gpu.py`（现 137 行，`detect()` 在 :66-97，`_PENDING_FIELDS` 在 :55-63）
- Create: `service/tests/infra/test_gpu_multi_vendor.py`
- Test: `service/tests/infra/test_gpu_multi_vendor.py`（新增）、`service/tests/infra/test_gpu_and_fallback.py`（形状适配）

**Interfaces:**
- Consumes: 无（本任务是最底层事实源）。
- Produces:
  - `gpu.classify_vendor(name: str) -> str` → `"nvidia" | "amd" | "intel" | "other"`
  - `gpu.is_virtual_adapter(name: str) -> bool`
  - `gpu.parse_cim_output(raw: str) -> list[dict[str, str]]`，每项 `{"name", "vendor", "driver_version"}`；非法 JSON 抛 `ValueError`
  - `gpu.choose_primary(adapters: list[dict[str, str]]) -> dict[str, str] | None`
  - `gpu.detect() -> dict[str, object]`：在既有键之外**必定**包含 `"adapters": list[dict[str, str]]`
  - `gpu.snapshot()` / `gpu.prefetch()` 签名与缓存语义不变；`_PENDING_FIELDS` 增加 `"adapters": []`

- [ ] **Step 1: 写失败测试（纯函数四件套）**

创建 `service/tests/infra/test_gpu_multi_vendor.py`：

```python
"""宿主 GPU 探测的多厂商事实：CIM 枚举 + nvidia-smi 合并，虚拟适配器不算显卡。

判据是「宿主有什么卡」，不是「有没有 N 卡」——AMD/Intel 主机的 vendor 必须如实，
否则界面与设备选项都会把有卡的主机报成无卡（规格 §1 根因 1/6）。
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from dramaclip.infra import gpu


def test_classify_vendor_by_name_prefix_order() -> None:
    assert gpu.classify_vendor("NVIDIA GeForce RTX 3060") == "nvidia"
    assert gpu.classify_vendor("Quadro M4000") == "nvidia"
    assert gpu.classify_vendor("Radeon (TM) RX 6600") == "amd"
    assert gpu.classify_vendor("AMD Radeon Graphics") == "amd"
    assert gpu.classify_vendor("ATI Radeon X1900") == "amd"
    assert gpu.classify_vendor("Intel(R) UHD Graphics 770") == "intel"
    assert gpu.classify_vendor("Some Unknown 3D Controller") == "other"
    assert gpu.classify_vendor("") == "other"


def test_virtual_adapters_are_filtered() -> None:
    for name in (
        "Microsoft Basic Display Adapter",
        "Microsoft Basic Render Driver",
        "Microsoft Remote Display Adapter",
        "Microsoft Hyper-V Video",
        "VMware SVGA II Adapter",
        "VirtualBox Graphics Adapter",
        "Parsec Virtual Display Adapter",
        "Citrix Workspace Assistant Display",
        "GameViewer Virtual Display Adapter",
        "Mirage MQ Helper",
    ):
        assert gpu.is_virtual_adapter(name), name
    assert not gpu.is_virtual_adapter("AMD Radeon RX 6600")
    assert not gpu.is_virtual_adapter("Intel(R) Iris(R) Xe Graphics")


def test_parse_cim_output_accepts_single_object_and_array() -> None:
    single = json.dumps({"Name": "AMD Radeon RX 6600", "DriverVersion": "31.0.12027.9001"})
    assert gpu.parse_cim_output(single) == [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027.9001"}
    ]
    array = json.dumps(
        [
            {"Name": "Intel(R) UHD Graphics 770", "DriverVersion": "31.0.101.5333"},
            {"Name": "GameViewer Virtual Display Adapter", "DriverVersion": "1.0.0"},
        ]
    )
    # 虚拟设备在 parse 阶段就剔除：调用方不需要再记一遍过滤规则
    assert gpu.parse_cim_output(array) == [
        {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0.101.5333"}
    ]


def test_parse_cim_output_tolerates_bom_and_missing_fields() -> None:
    raw = '﻿[{"Name": "AMD Radeon RX 6600"}]'
    assert gpu.parse_cim_output(raw) == [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": ""}
    ]


def test_parse_cim_output_rejects_illegal_json() -> None:
    with pytest.raises(ValueError):
        gpu.parse_cim_output("not json at all")


def test_choose_primary_prefers_nvidia_then_amd_then_intel() -> None:
    adapters = [
        {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0"},
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0"},
        {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "551.61"},
    ]
    assert gpu.choose_primary(adapters)["name"] == "NVIDIA GeForce RTX 3060"
    without_nvidia = [a for a in adapters if a["vendor"] != "nvidia"]
    assert gpu.choose_primary(without_nvidia)["name"] == "AMD Radeon RX 6600"
    assert gpu.choose_primary([adapters[0]])["name"] == "Intel(R) UHD Graphics 770"
    other_only = [{"name": "USB 3D Hub", "vendor": "other", "driver_version": ""}]
    assert gpu.choose_primary(other_only) == other_only[0]
    assert gpu.choose_primary([]) is None


def test_choose_primary_keeps_cim_order_within_same_vendor() -> None:
    adapters = [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "1"},
        {"name": "AMD Radeon Pro W5700", "vendor": "amd", "driver_version": "2"},
    ]
    assert gpu.choose_primary(adapters)["name"] == "AMD Radeon RX 6600"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_gpu_multi_vendor.py -q`
Expected: FAIL —`AttributeError: module 'dramaclip.infra.gpu' has no attribute 'classify_vendor'`

- [ ] **Step 3: 实现纯函数四件套**

在 `service/dramaclip/infra/gpu.py` 的 `parse_max_cuda` 之后、`_PENDING_FIELDS` 之前插入：

```python
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


def classify_vendor(name: str) -> str:
    """按适配器名认厂商；认不出归 other——宁可不归功，也不冒充 NVIDIA。"""
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
    data = json.loads(raw.lstrip("﻿").strip())
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


def choose_primary(adapters: list[dict[str, str]]) -> dict[str, str] | None:
    """主适配器按 NVIDIA > AMD > Intel > other；同级保持 CIM 返回顺序。"""
    for vendor in _VENDOR_ORDER:
        for adapter in adapters:
            if adapter["vendor"] == vendor:
                return adapter
    return None
```

同时把 `import json` 加进文件头的 import 段（`re`/`shutil`/`subprocess`/`threading` 之后，按字母序），`_PENDING_FIELDS` 增加一行：

```python
    "compute_cap": "",
    "adapters": [],
```

- [ ] **Step 4: 运行确认纯函数测试通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_gpu_multi_vendor.py -q`
Expected: PASS（6 个用例）

- [ ] **Step 5: 写失败测试（detect 合并规则）**

在 `service/tests/infra/test_gpu_multi_vendor.py` 追加：

```python
def _stub_queries(
    monkeypatch: pytest.MonkeyPatch,
    cim: Any,
    smi: Any,
    platform: str = "win32",
) -> None:
    monkeypatch.setattr(gpu.sys, "platform", platform, raising=False)
    monkeypatch.setattr(gpu, "_query_cim_adapters", cim)
    monkeypatch.setattr(gpu, "_query_nvidia_smi", smi)


def test_detect_reports_amd_host_with_adapters_and_empty_cuda_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = [{"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027"}]
    _stub_queries(monkeypatch, lambda: adapters, lambda: None)
    info = gpu.detect()
    assert info["ready"] is True
    assert info["vendor"] == "amd"
    assert info["name"] == "AMD Radeon RX 6600"
    assert info["driver_version"] == "31.0.12027"
    # 非 N 卡不采信 AdapterRAM：显存宁可为 0，不写假数（规格 §2.1）
    assert info["memory_total_mb"] == 0
    assert info["max_cuda_version"] == ""
    assert info["compute_cap"] == ""
    assert info["adapters"] == adapters


def test_detect_nvidia_smi_overrides_cim_nvidia_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cim = [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "546.00"}]
    smi = {
        "name": "NVIDIA GeForce RTX 3060",
        "driver_version": "551.61",
        "memory_total_mb": 12288,
        "max_cuda_version": "12.4",
        "compute_cap": "8.6",
    }
    _stub_queries(monkeypatch, lambda: cim, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["driver_version"] == "551.61", "CUDA 细节只来自 nvidia-smi"
    assert info["memory_total_mb"] == 12288
    assert info["max_cuda_version"] == "12.4"
    assert info["adapters"][0]["driver_version"] == "551.61"


def test_detect_adds_nvidia_adapter_when_only_smi_sees_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cim = [{"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0"}]
    smi = {
        "name": "NVIDIA GeForce RTX 4060",
        "driver_version": "552.22",
        "memory_total_mb": 8192,
        "max_cuda_version": "12.4",
        "compute_cap": "8.9",
    }
    _stub_queries(monkeypatch, lambda: cim, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia", "主适配器优先级 NVIDIA > Intel"
    assert [a["vendor"] for a in info["adapters"]] == ["nvidia", "intel"]


def test_detect_cim_only_nvidia_leaves_cuda_fields_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CIM 看得到 N 卡但 nvidia-smi 不可用：vendor 如实 nvidia，CUDA 三项为空——不得据此判驱动旧。"""
    cim = [{"name": "NVIDIA GeForce GTX 1650", "vendor": "nvidia", "driver_version": "546.33"}]
    _stub_queries(monkeypatch, lambda: cim, lambda: None)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["name"] == "NVIDIA GeForce GTX 1650"
    assert info["driver_version"] == "546.33"
    assert info["max_cuda_version"] == ""
    assert info["memory_total_mb"] == 0
    assert info["compute_cap"] == ""


def test_detect_cim_failure_still_uses_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> list[dict[str, str]]:
        raise RuntimeError("powershell 不存在")

    smi = {
        "name": "NVIDIA T400",
        "driver_version": "551.61",
        "memory_total_mb": 4096,
        "max_cuda_version": "12.4",
        "compute_cap": "7.5",
    }
    _stub_queries(monkeypatch, boom, lambda: smi)
    info = gpu.detect()
    assert info["vendor"] == "nvidia"
    assert info["adapters"] == [
        {"name": "NVIDIA T400", "vendor": "nvidia", "driver_version": "551.61"}
    ]


def test_detect_no_adapter_at_all_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_queries(monkeypatch, lambda: [], lambda: None)
    info = gpu.detect()
    assert info["vendor"] == "none"
    assert info["adapters"] == []


def test_detect_non_windows_skips_cim(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _stub_queries(
        monkeypatch,
        lambda: calls.append(1) or [],
        lambda: None,
        platform="darwin",
    )
    info = gpu.detect()
    assert calls == []
    assert info["vendor"] == "none"


def test_parse_cim_command_is_fixed_and_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, '[{"Name":"AMD Radeon RX 6600"}]', "")

    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    out = gpu._query_cim_adapters()  # noqa: SLF001
    assert out == [{"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": ""}]
    joined = " ".join(seen["cmd"])
    assert "Win32_VideoController" in joined
    assert "DriverVersion" in joined
    assert "Name" in joined
    assert "AdapterRAM" not in joined, "AdapterRAM 是 UInt32，现代显卡普遍失真，不采信"
    assert seen["timeout"] == 10.0
    assert seen["creationflags"] == gpu._NO_WINDOW  # noqa: SLF001


def test_query_cim_adapters_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["powershell.exe"], 10)

    monkeypatch.setattr(gpu.subprocess, "run", boom)
    assert gpu._query_cim_adapters() == []  # noqa: SLF001


def test_snapshot_pending_shape_includes_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu, "_CACHE", None, raising=False)
    monkeypatch.setattr(gpu, "prefetch", lambda: None)
    snap = gpu.snapshot()
    assert snap["ready"] is False
    assert snap["vendor"] == "unknown"
    assert snap["adapters"] == []
```

- [ ] **Step 6: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_gpu_multi_vendor.py -q`
Expected: FAIL — 新增用例报 `AttributeError: module 'dramaclip.infra.gpu' has no attribute 'sys'` / `_query_cim_adapters`。

- [ ] **Step 7: 拆出两个查询函数并重写 detect**

`service/dramaclip/infra/gpu.py` 的文件头 import 段补 `import sys`；`detect()` 整体替换为：

```python
_CIM_SCRIPT = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "Get-CimInstance -ClassName Win32_VideoController |"
    "Select-Object Name,DriverVersion | ConvertTo-Json -Compress"
)


def _query_cim_adapters() -> list[dict[str, str]]:
    """Windows CIM 枚举显示适配器；任何失败返回空清单，不抛错（探测不能阻塞服务）。

    脚本固定、无用户输入插值；命令原文不写日志，避免把主机用户名带进去。
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
    """同步探测（阻塞，最长 ~20s）：CIM 厂商事实 + nvidia-smi CUDA 事实 → 宿主结论。

    仅由 prefetch 后台线程调用。合并规则见规格 §2.2：虚拟设备先剔除，smi 的 NVIDIA
    条目覆盖 CIM 同名项，CUDA 三项只在该项确为 NVIDIA 且 smi 可读时填充。
    """
    adapters = list(_query_cim_adapters()) if sys.platform == "win32" else []
    smi = _query_nvidia_smi()
    if smi is not None:
        nvidia_name = str(smi["name"]) or ""
        nvidia_adapter = {
            "name": nvidia_name,
            "vendor": "nvidia",
            "driver_version": str(smi["driver_version"]) or "",
        }
        existing = next((a for a in adapters if a["vendor"] == "nvidia"), None)
        if existing is None:
            adapters.insert(0, nvidia_adapter)
        else:
            existing["driver_version"] = nvidia_adapter["driver_version"]
            if nvidia_name:
                existing["name"] = nvidia_name

    primary = choose_primary(adapters)
    vendor = primary["vendor"] if primary else "none"
    has_smi_nvidia = smi is not None and vendor == "nvidia"
    return {
        "ready": True,
        "vendor": vendor,
        "name": primary["name"] if primary else "",
        "driver_version": primary["driver_version"] if primary else "",
        "max_cuda_version": str(smi["max_cuda_version"]) if has_smi_nvidia else "",
        "memory_total_mb": int(smi["memory_total_mb"]) if has_smi_nvidia else 0,
        "compute_cap": str(smi["compute_cap"]) if has_smi_nvidia else "",
        "adapters": adapters,
    }
```

`snapshot(force)` / `prefetch()` / `_to_int_mb` / `_smi_paths` / `_run` / `parse_query_output` 不变。

- [ ] **Step 8: 适配既有形状测试**

`service/tests/infra/test_gpu_and_fallback.py` 的 `test_detect_reports_cpu_when_smi_missing`（以及同文件任何直接调 `gpu.detect()` 的用例）现在会在 Windows 本机真的枚举到物理卡。给每个此类用例补 CIM 桩：

```python
    monkeypatch.setattr(gpu, "_query_cim_adapters", lambda: [])
```

若该用例断言 `_PENDING_FIELDS` 的键集合，同步把 `adapters` 加进期望集合——这是形状扩展，不是放宽断言。

- [ ] **Step 9: 运行本任务全部测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_gpu_multi_vendor.py tests/infra/test_gpu_and_fallback.py -q`
Expected: PASS，输出无 warning。

- [ ] **Step 10: 提交**

```bash
git status --short service/dramaclip/infra/gpu.py service/tests/infra/test_gpu_multi_vendor.py service/tests/infra/test_gpu_and_fallback.py
git add service/dramaclip/infra/gpu.py service/tests/infra/test_gpu_multi_vendor.py service/tests/infra/test_gpu_and_fallback.py
git commit -m "feat: GPU 探测改 CIM+nvidia-smi 两路合并——AMD/Intel 主机不再被报成无卡"
```

---

## Task 2: 能力表按厂商说话（`device_profile.py` + `system.health` 接线）

**Files:**
- Modify: `service/dramaclip/infra/device_profile.py`（现 238 行：`_TIER_LABELS` :20-26、`tier_of` :29-40、`profile` :109-237）
- Modify: `service/dramaclip/api/system.py:37-41`（health 传 `torch_variant`）
- Create: `service/tests/infra/test_device_profile_multi_vendor.py`
- Modify: `service/tests/infra/test_gpu_and_fallback.py:217`（`tier_of("nvidia", 0)` 的期望随 §3.1 语义变更）

**Interfaces:**
- Consumes: Task 1 的 `gpu.detect()` 快照（`vendor` 可为 `nvidia|amd|intel|other|none|unknown`，非 N 卡 `memory_total_mb` 恒 0）。
- Produces:
  - `device_profile.tier_of(vendor: str, memory_total_mb: int) -> str`：**仅** `vendor=="nvidia"` 且 `memory_total_mb > 0` 才按阈值分档，其余一律 `"none"`
  - `device_profile.profile(snapshot, cuda_runtime_installed, *, separation_ort=None, torch_variant: str | None = None) -> dict`
  - 每个 `caps[key]` 的形状固定为 `{"ok": bool, "ready": bool, "hint": str, "reason": str}`；`reason` 是短句原因（界面直接展示），过关时为空串
  - `driver_guidance` 仍为 `{"needed", "url", "min_driver", "reason"}`，但 `needed` 现在覆盖「驱动过旧」与「驱动不可读」两种
  - 模块常量供 Task 3 复用：`device_profile.CAPS`（能力键集合）

- [ ] **Step 1: 写失败测试**

创建 `service/tests/infra/test_device_profile_multi_vendor.py`：

```python
"""能力表的多厂商口径：有卡就说有卡，AI 加速只认 CUDA，读不到不等于太旧。

三条判据各自独立（规格 §3.2/§3.3/§3.5）：厂商标签、驱动可读性、每条栈的算力下界。
开发机（sm_52 + RX 5500 XT）只作回归，任何用例都不许把它的实况当判据。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.infra import device_profile

_AMD = {
    "ready": True,
    "vendor": "amd",
    "name": "AMD Radeon RX 6600",
    "driver_version": "31.0.12027.9001",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [
        {"name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027.9001"}
    ],
}
_INTEL = {**_AMD, "vendor": "intel", "name": "Intel(R) UHD Graphics 770"}
_OTHER = {**_AMD, "vendor": "other", "name": "USB 3D Controller"}
_NONE = {**_AMD, "vendor": "none", "name": "", "driver_version": "", "adapters": []}
_PENDING = {**_AMD, "ready": False, "vendor": "unknown", "name": "", "adapters": []}
# NVIDIA 主流独显（RTX 3060 档）：算力 ≥7.0、驱动支持 CUDA 12
_NVIDIA_OK = {
    "ready": True,
    "vendor": "nvidia",
    "name": "NVIDIA GeForce RTX 3060",
    "driver_version": "551.61",
    "max_cuda_version": "12.4",
    "memory_total_mb": 12288,
    "compute_cap": "8.6",
    "adapters": [
        {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "driver_version": "551.61"}
    ],
}
# GTX 10 存量段（Pascal sm_61）：ctranslate2 能用、torch cu128 不能用、ORT 能用
_GTX10 = {**_NVIDIA_OK, "name": "NVIDIA GeForce GTX 1060", "memory_total_mb": 6144,
          "compute_cap": "6.1"}
# CIM 认得出 N 卡但 nvidia-smi 不可用：CUDA 三项读不到，不许说成「驱动太旧」
_NVIDIA_NO_SMI = {
    "ready": True,
    "vendor": "nvidia",
    "name": "NVIDIA GeForce GTX 1650",
    "driver_version": "546.33",
    "max_cuda_version": "",
    "memory_total_mb": 0,
    "compute_cap": "",
    "adapters": [
        {"name": "NVIDIA GeForce GTX 1650", "vendor": "nvidia", "driver_version": "546.33"}
    ],
}


def _caps(snap: dict[str, Any], **kwargs: Any) -> dict[str, dict[str, Any]]:
    return device_profile.profile(snap, **kwargs)["caps"]


def test_tier_of_requires_nvidia_and_readable_vram() -> None:
    assert device_profile.tier_of("nvidia", 12288) == "mid"
    # 显存读不到（0）不再是「入门档」：那是未知，不是小卡
    assert device_profile.tier_of("nvidia", 0) == "none"
    for vendor in ("amd", "intel", "other", "none", "unknown"):
        assert device_profile.tier_of(vendor, 24576) == "none", vendor


@pytest.mark.parametrize(
    ("snap", "label"),
    [
        (_AMD, "AMD 显卡 · 视频硬编，AI 引擎走 CPU"),
        (_INTEL, "Intel 显卡 · 视频硬编，AI 引擎走 CPU"),
        (_OTHER, "其他显卡 · AI 引擎走 CPU"),
        (_NONE, "未检测到独立显卡"),
        (_PENDING, "显卡探测中…"),
        (_NVIDIA_OK, "主力（12-19GB 显存）"),
        (_NVIDIA_NO_SMI, "NVIDIA 显卡 · 显存信息不可读"),
    ],
)
def test_tier_label_names_the_host_fact(snap: dict[str, Any], label: str) -> None:
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["tier_label"] == label
    assert prof["tier"] == ("mid" if snap is _NVIDIA_OK else "none")


def test_amd_host_recommends_amf_not_cloud() -> None:
    prof = device_profile.profile(_AMD, cuda_runtime_installed=False)
    assert "AMF" in prof["recommendation"]
    assert "NVIDIA CUDA" in prof["recommendation"]
    assert "云端" in prof["recommendation"], "AI 走 CPU 时仍要给出云端这条路"
    prof_intel = device_profile.profile(_INTEL, cuda_runtime_installed=False)
    assert "QSV" in prof_intel["recommendation"]
    prof_other = device_profile.profile(_OTHER, cuda_runtime_installed=False)
    assert "真试编" in prof_other["recommendation"]
    assert device_profile.profile(_NONE, cuda_runtime_installed=False)[
        "recommendation"
    ].startswith("推荐启用云端引擎")
    assert "CPU" in device_profile.profile(_PENDING, cuda_runtime_installed=False)[
        "recommendation"
    ]


@pytest.mark.parametrize("snap", [_AMD, _INTEL, _OTHER, _NONE])
def test_non_nvidia_caps_are_not_ready_with_vendor_hint(snap: dict[str, Any]) -> None:
    caps = _caps(snap, cuda_runtime_installed=True)
    for key in (
        "faster_whisper_gpu",
        "funasr_gpu",
        "indextts2_gpu",
        "vocal_separation_gpu",
        "local_visual_2b",
    ):
        assert caps[key]["ok"] is False and caps[key]["ready"] is False, key
        assert caps[key]["reason"], key
    assert "NVIDIA CUDA" in caps["vocal_separation_gpu"]["hint"]
    assert "仅支持" in caps["vocal_separation_gpu"]["hint"]
    assert "音色克隆" in caps["indextts2_gpu"]["hint"]


def test_pending_snapshot_hints_probing_not_refusal() -> None:
    caps = _caps(_PENDING, cuda_runtime_installed=False)
    assert caps["faster_whisper_gpu"]["hint"] == "显卡状态探测中：转写暂走 CPU"
    assert caps["vocal_separation_gpu"]["hint"] == "显卡状态探测中：人声分离暂走 CPU"
    assert caps["local_visual_4b"]["hint"] == "显卡状态探测中"


def test_every_cap_carries_reason_and_goes_through_the_same_shape() -> None:
    caps = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    for key, cap in caps.items():
        assert set(cap) == {"ok", "ready", "hint", "reason"}, key
        assert isinstance(cap["ok"], bool) and isinstance(cap["ready"], bool), key
    assert caps["faster_whisper_gpu"]["reason"] == ""
    assert caps["indextts2_gpu"]["ready"] is True


def test_indextts2_ready_follows_the_tts_venv_torch_variant() -> None:
    """torch cu128 是 tts-venv 的事：变体 cpu 就不许亮 ready，变体 cuda 才 ready。"""
    cpu = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cpu")
    cuda = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    assert cpu["indextts2_gpu"]["ok"] is True
    assert cpu["indextts2_gpu"]["ready"] is False
    assert "CPU 轮" in cpu["indextts2_gpu"]["reason"]
    assert cuda["indextts2_gpu"]["ready"] is True
    assert cuda["indextts2_gpu"]["hint"] == ""


def test_gtx10_blocks_torch_stack_but_not_ct2_or_ort() -> None:
    """§3.5 主验收：sm_61 上 whisper 可用、torch 音色克隆永久不可用、分离仍可用。"""
    caps = _caps(
        _GTX10, cuda_runtime_installed=True, torch_variant="cpu",
        separation_ort={"variant": "gpu", "gpu": True, "reason": ""},
    )
    assert caps["faster_whisper_gpu"]["ok"] is True
    assert caps["indextts2_gpu"]["ok"] is False, "sm_61 低于 torch cu128 的 sm_70 下界"
    assert "sm_70" in caps["indextts2_gpu"]["hint"]
    assert caps["vocal_separation_gpu"]["ready"] is True
    assert caps["funasr_gpu"]["ok"] is True, "funasr 不写静态算力下限（两套运行时实况不同）"


def test_funasr_has_no_static_floor_ready_follows_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """老卡（sm_52）上 funasr 可能真在 GPU 跑：静态下限会造假阴性，ready 只看探测。"""
    snap = {**_NVIDIA_OK, "compute_cap": "5.2", "memory_total_mb": 8192}
    monkeypatch.setattr(device_profile, "_SERVICE_TORCH_STATE", (True, True, "5.2"))
    assert _caps(snap, cuda_runtime_installed=True, torch_variant="cpu")[
        "funasr_gpu"
    ]["ready"] is True
    monkeypatch.setattr(device_profile, "_SERVICE_TORCH_STATE", (False, False, ""))
    assert _caps(snap, cuda_runtime_installed=True, torch_variant="cpu")[
        "funasr_gpu"
    ]["ready"] is False


def test_driver_unreadable_is_not_reported_as_too_old() -> None:
    """§3.3：读不到 ≠ 太旧。reason 说「无法确认」，不许冒充 CUDA 上限过低。"""
    prof = device_profile.profile(_NVIDIA_NO_SMI, cuda_runtime_installed=False)
    guidance = prof["driver_guidance"]
    assert guidance["needed"] is True
    assert "未能读取" in guidance["reason"]
    assert "低于 12" not in guidance["reason"]
    assert "nvidia-smi" in guidance["reason"]
    assert "驱动信息不可读" in prof["recommendation"]
    caps = prof["caps"]
    assert caps["faster_whisper_gpu"]["ready"] is False
    assert caps["faster_whisper_gpu"]["hint"] == "未能读取 NVIDIA 驱动信息，无法确认 CUDA 12 支持"


def test_driver_too_old_still_says_so_with_the_number() -> None:
    snap = {**_NVIDIA_OK, "max_cuda_version": "11.8"}
    prof = device_profile.profile(snap, cuda_runtime_installed=False)
    assert prof["driver_guidance"]["needed"] is True
    assert "11.8" in prof["driver_guidance"]["reason"]
    assert "低于 12" in prof["driver_guidance"]["reason"]
    assert "更新 NVIDIA 驱动" in prof["recommendation"]


def test_local_visual_caps_stay_not_ready_for_everyone() -> None:
    """视觉轨的 CUDA 构建资产还没进资产库：任何宿主都不得提前点亮。"""
    for snap in (_NVIDIA_OK, _AMD, _NONE):
        caps = _caps(snap, cuda_runtime_installed=True, torch_variant="cuda")
        for key in ("local_visual_2b", "local_visual_4b", "local_visual_8b"):
            assert caps[key]["ready"] is False, f"{snap['vendor']}/{key}"


def test_local_visual_ok_follows_the_vram_floor() -> None:
    """12GB 的 N 卡够 4B 档、不够 8B 档：显存门槛与厂商无关，只与 N 卡 + 显存有关。"""
    caps = _caps(_NVIDIA_OK, cuda_runtime_installed=True, torch_variant="cuda")
    assert caps["local_visual_2b"]["ok"] is True
    assert caps["local_visual_4b"]["ok"] is True
    assert caps["local_visual_8b"]["ok"] is False
    assert caps["local_visual_8b"]["reason"]

    amd = _caps(_AMD, cuda_runtime_installed=True, torch_variant="cuda")
    assert amd["local_visual_2b"]["ok"] is False
```

`system.health` 的接线用例放在 Step 5 新建的 `service/tests/api/test_system_health.py` 里（`health()` 得先成为模块级函数才有可测出口）。

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_device_profile_multi_vendor.py -q`
Expected: FAIL —`tier_of("nvidia", 0)` 现为 `"low"`、`tier_label` 仍是「未检测到 NVIDIA 显卡」、`caps` 缺 `reason`、`profile()` 不接受 `torch_variant`（`TypeError`）。

- [ ] **Step 3: 重写 `device_profile.py` 的标签/推荐/能力表**

模块头部常量替换为（`_MIN_DRIVER_MAJOR`、`_DRIVER_URL` 不动）：

```python
_TIER_LABELS = {
    "none": "未检测到独立显卡",
    "low": "入门（<6GB 显存）",
    "entry": "标准（6-11GB 显存）",
    "mid": "主力（12-19GB 显存）",
    "high": "高配（20GB+ 显存）",
}
# 非 NVIDIA 主机有卡是事实：标签说清「硬编可用、AI 走 CPU」，别再冒充「没有显卡」。
_VENDOR_TIER_LABELS = {
    "amd": "AMD 显卡 · 视频硬编，AI 引擎走 CPU",
    "intel": "Intel 显卡 · 视频硬编，AI 引擎走 CPU",
    "other": "其他显卡 · AI 引擎走 CPU",
}
_VENDOR_RECOMMENDATIONS = {
    "amd": "视频导出可用本卡硬件编码（AMF，导出时真试编）；"
    "ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎",
    "intel": "视频导出可用本卡硬件编码（QSV，导出时真试编）；"
    "ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎",
    "other": "视频导出会在真试编后选择硬编或 libx264；ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU",
}
_PENDING_LABEL = "显卡探测中…"
_PENDING_RECOMMENDATION = "显卡状态探测中：本地引擎均可先用 CPU 运行"
_NO_CARD_RECOMMENDATION = "推荐启用云端引擎（百炼）：本地 GPU 加速不可用或显存不足"
_VRAM_UNKNOWN_LABEL = "NVIDIA 显卡 · 显存信息不可读"

#: 能力键的唯一清单：Task 3 的解析入口与前端都按这张表取数，别处不再抄一份。
CAPS = (
    "faster_whisper_gpu",
    "funasr_gpu",
    "indextts2_gpu",
    "vocal_separation_gpu",
    "local_visual_2b",
    "local_visual_4b",
    "local_visual_8b",
)
_PROBING_HINTS = {
    "faster_whisper_gpu": "显卡状态探测中：转写暂走 CPU",
    "funasr_gpu": "显卡状态探测中：转写暂走 CPU",
    "indextts2_gpu": "显卡状态探测中：音色克隆暂走 CPU",
    "vocal_separation_gpu": "显卡状态探测中：人声分离暂走 CPU",
    "local_visual": "显卡状态探测中",
}
_NON_NVIDIA_HINTS = {
    "faster_whisper_gpu": "转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "funasr_gpu": "转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "indextts2_gpu": "音色克隆 GPU 加速需要 NVIDIA CUDA，当前走 CPU",
    "vocal_separation_gpu": "人声分离 GPU 加速仅支持 NVIDIA CUDA，当前走 CPU",
    "local_visual": "本地视觉模型需要 NVIDIA CUDA，当前不可用",
}
_REASON_PROBING = "显卡状态探测中"
_REASON_NON_NVIDIA = "本机无 NVIDIA 显卡，加速需要 CUDA"
_REASON_DRIVER_UNKNOWN = "未能读取 NVIDIA 驱动信息"
_REASON_DRIVER_OLD = "驱动支持的 CUDA 上限低于 12"
_REASON_VRAM_UNKNOWN = "显存信息不可读"
_REASON_VRAM_LOW = "显存不足 4GB"
_REASON_RUNTIME_MISSING = "CUDA 运行库未安装"
_REASON_TORCH_CPU_WHEEL = "本地运行环境的 torch 是 CPU 轮"
# torch cu128（tts-venv）的可执行内核下界：低于此算力装得上、算子无内核（2026-10-16 实测）
_TORCH_MIN_CC = (7, 0)
```

`tier_of` 改为：

```python
def tier_of(vendor: str, memory_total_mb: int) -> str:
    """显存分档：只有 NVIDIA 且显存真读得到才分档，其余一律 none。

    「显存读不到」不是小卡：非 N 卡不采信 AdapterRAM（UInt32 普遍失真），N 卡掉了
    nvidia-smi 也是 0——都归 none，由厂商标签与驱动分支各自说清原因。
    """
    if vendor != "nvidia" or memory_total_mb <= 0:
        return "none"
    gb = memory_total_mb / 1024.0
    if gb < 6.0:
        return "low"
    if gb < 12.0:
        return "entry"
    if gb < 20.0:
        return "mid"
    return "high"
```

在 `_parse_cc` 之后追加两个小工具：

```python
def _cap(ok: bool, ready: bool, hint: str, reason: str) -> dict[str, Any]:
    """能力项的形状唯一出口：reason 是给程序与界面标签用的短句，hint 是给人看的整句。"""
    return {"ok": ok, "ready": ready, "hint": hint, "reason": reason}


def _tts_torch_variant(override: str | None) -> str:
    """tts-venv 的 torch 变体：调用方给了就用调用方的（按它自己的 data_dir），否则现读全局。"""
    if override is not None:
        return override if override in ("cuda", "cpu") else "unknown"
    return "cuda" if _torch_variant_is_cuda() else "unknown"
```

`profile()` 整体替换为：

```python
def profile(
    snapshot: dict[str, Any],
    cuda_runtime_installed: bool,
    *,
    separation_ort: dict[str, Any] | None = None,
    torch_variant: str | None = None,
) -> dict[str, Any]:
    """探测快照 + 运行库/ORT/torch 安装态 → 设备档位与各引擎能力结论。

    ``separation_ort`` 是 tts_runtime.ort_state（安装期真实 session 探测的 marker）；
    ``torch_variant`` 是 tts_runtime.torch_variant。两者由调用方按**自己的 data_dir**
    读进来：本函数不许再去猜全局 data_dir，否则 system.health 与解析入口会各得结论。
    安装态与可用态分开——GPU 轮装上了但 session 落 CPU 时必须如实不 ready。
    """
    vendor = str(snapshot.get("vendor") or "none")
    name = str(snapshot.get("name") or "")
    memory_total_mb = int(snapshot.get("memory_total_mb") or 0)
    max_cuda_version = str(snapshot.get("max_cuda_version") or "")
    probing = vendor == "unknown"
    nvidia_hw = vendor == "nvidia"
    tier = tier_of(vendor, memory_total_mb)
    is_nvidia = nvidia_hw and tier != "none"  # N 卡且显存可读
    vram_gb = memory_total_mb / 1024.0

    cc_raw = str(snapshot.get("compute_cap") or "") or _service_torch_state()[2]
    cc = _parse_cc(cc_raw)
    whisper_blocked = cc is not None and cc < _CTRANSLATE2_MIN_CC
    torch_blocked = cc is not None and cc < _TORCH_MIN_CC

    # §3.3 三分支：读不到（unknown）与读到了但太低（old）是两件事，前者不能冒充后者。
    driver_old = nvidia_hw and max_cuda_version != "" and not _cuda_major_ok(max_cuda_version)
    driver_unknown = nvidia_hw and max_cuda_version == ""
    guidance_reason = ""
    if driver_unknown:
        guidance_reason = (
            "未能读取 NVIDIA 驱动的 CUDA 上限（nvidia-smi 不可用或查询失败），"
            "无法确认 CUDA 12 支持：请重装 NVIDIA 驱动后重试"
        )
    elif driver_old:
        guidance_reason = f"驱动支持的 CUDA 上限 {max_cuda_version} 低于 12，" \
            "GPU 加速（CUDA 运行库）无法启用"
    driver_guidance = {
        "needed": driver_unknown or driver_old,
        "url": _DRIVER_URL,
        "min_driver": str(_MIN_DRIVER_MAJOR),
        "reason": guidance_reason,
    }

    cuda_ok = is_nvidia and _cuda_major_ok(max_cuda_version)
    variant = _tts_torch_variant(torch_variant)

    if probing:
        tier_label = _PENDING_LABEL
    elif nvidia_hw:
        tier_label = _TIER_LABELS[tier] if tier != "none" else _VRAM_UNKNOWN_LABEL
    else:
        tier_label = _VENDOR_TIER_LABELS.get(vendor) or _TIER_LABELS["none"]

    runtime_tail = "（安装 CUDA 运行库后生效）" if is_nvidia and not cuda_runtime_installed else ""
    # 优先级 §3.3：驱动不可读 > 显存不可读 > 驱动过旧 > 常规分档
    if probing:
        recommendation = _PENDING_RECOMMENDATION
    elif driver_unknown:
        recommendation = (
            "NVIDIA 驱动信息不可读（nvidia-smi 不可用或查询失败）：修复驱动后重试，或改用云端引擎"
        )
    elif nvidia_hw and not is_nvidia:
        recommendation = (
            "NVIDIA 显卡在场但显存信息不可读：重装 NVIDIA 驱动后重试，或改用云端引擎"
        )
    elif driver_old:
        recommendation = (
            f"驱动支持的 CUDA 上限 {max_cuda_version} 低于 12：先更新 NVIDIA 驱动，或改用云端引擎"
        )
    elif vendor in _VENDOR_RECOMMENDATIONS:
        recommendation = _VENDOR_RECOMMENDATIONS[vendor]
    elif tier in ("none", "low"):
        recommendation = _NO_CARD_RECOMMENDATION
    else:
        recommendation = "本地 GPU 引擎可启用" + runtime_tail

    def note(cap_key: str, local: bool = False) -> tuple[str, str, bool]:
        """待定/非 NVIDIA 两类短路：(hint, reason, 是否短路)。"""
        short = cap_key if not local else "local_visual"
        if probing:
            return _PROBING_HINTS[short], _REASON_PROBING, True
        if not nvidia_hw:
            return _NON_NVIDIA_HINTS[short], _REASON_NON_NVIDIA, True
        return "", "", False

    def hardware_block() -> tuple[str, str]:
        """NVIDIA 主机的硬件门禁：显存/驱动过关则空，否则给 (hint, reason)。"""
        if driver_unknown:
            return "未能读取 NVIDIA 驱动信息，无法确认 CUDA 12 支持", _REASON_DRIVER_UNKNOWN
        if not is_nvidia:
            return "需 4GB+ 显存且驱动支持 CUDA 12+（显存信息不可读）", _REASON_VRAM_UNKNOWN
        if vram_gb < 4.0:
            return "需 4GB+ 显存且驱动支持 CUDA 12+（显存不足 4GB）", _REASON_VRAM_LOW
        if not cuda_ok:
            return "需 4GB+ 显存且驱动支持 CUDA 12+", _REASON_DRIVER_OLD
        return "", ""

    hw_hint, hw_reason = hardware_block()
    hardware_ok = hw_hint == ""

    # 分支顺序即 §3.4 的口径：待定/非 NVIDIA 的厂商文案 → NVIDIA 硬件门禁（含驱动不可读）
    # → 该条栈自己的运行时/算力判据。写反了就会给 AMD 主机报「CUDA 运行库未安装」。
    fw_hint, fw_reason, fw_short = note("faster_whisper_gpu")
    whisper_ok = hardware_ok and not whisper_blocked
    whisper_ready = whisper_ok and cuda_runtime_installed
    if not fw_short:
        if not hardware_ok:
            fw_hint, fw_reason = hw_hint, hw_reason
        elif whisper_blocked:
            fw_hint = (
                f"此卡算力 sm_{cc_raw} 无 ctranslate2 计算内核，whisper GPU 加速不可用；"
                "转写请用 funasr（N 卡上已在 GPU）或 CPU"
            )
            fw_reason = f"算力 sm_{cc_raw} 低于 ctranslate2 下界 sm_61"
        elif not cuda_runtime_installed:
            fw_hint, fw_reason = "CUDA 运行库未安装（安装后转写可走 GPU）", _REASON_RUNTIME_MISSING
        else:
            fw_hint, fw_reason = "", ""

    tts_hint, tts_reason, tts_short = note("indextts2_gpu")
    indextts_ok = hardware_ok and not torch_blocked
    indextts_ready = indextts_ok and variant == "cuda"
    if not tts_short:
        if not hardware_ok:
            tts_hint, tts_reason = hw_hint, hw_reason
        elif torch_blocked:
            tts_hint = f"此卡算力 sm_{cc_raw} 低于 torch cu128 下界 sm_70，音色克隆走 CPU"
            tts_reason = f"算力 sm_{cc_raw} 低于 torch cu128 下界 sm_70"
        elif variant != "cuda":
            tts_hint = "本地运行环境的 torch 是 CPU 轮：重跑「安装运行环境」可启用 GPU 克隆"
            tts_reason = _REASON_TORCH_CPU_WHEEL
        else:
            tts_hint, tts_reason = "", ""

    fa_hint, fa_reason, fa_short = note("funasr_gpu")
    # funasr 不写静态下限：它可能跑在打包态的 tts-venv（cu128）或 dev 态主进程 torch
    # （构建不同，sm_52 也能实跑在 GPU）——两种实况分别探测，静态线会造假阴性。
    funasr_ok = hardware_ok
    funasr_ready = funasr_ok and (_service_torch_is_cuda() or variant == "cuda")
    if not fa_short:
        if not hardware_ok:
            fa_hint, fa_reason = hw_hint, hw_reason
        elif not funasr_ready:
            fa_hint = "ASR 页安装运行环境后生效（N 卡自动装 CUDA 轮）"
            fa_reason = _REASON_TORCH_CPU_WHEEL
        else:
            fa_hint, fa_reason = "", ""

    sep_hint, sep_reason, sep_short = note("vocal_separation_gpu")
    ort_gpu = bool(separation_ort is not None and separation_ort.get("gpu"))
    separation_ready = hardware_ok and cuda_runtime_installed and ort_gpu
    if not sep_short:
        if not hardware_ok:
            sep_hint, sep_reason = hw_hint, hw_reason
        elif not cuda_runtime_installed:
            sep_hint = "CUDA 运行库未安装（安装后可重跑本地运行环境以启用 GPU 分离）"
            sep_reason = _REASON_RUNTIME_MISSING
        elif separation_ort is None or separation_ort.get("variant") in (None, "unknown"):
            sep_hint = "ONNX Runtime 运行后端未探测：重跑本地运行环境以启用 GPU 分离"
            sep_reason = "ONNX Runtime 后端未探测"
        elif not ort_gpu:
            sep_hint = str(
                (separation_ort or {}).get("reason") or "ONNX Runtime 为 CPU 版，分离走 CPU"
            )
            sep_reason = "ONNX Runtime 为 CPU 后端"
        else:
            sep_hint, sep_reason = "", ""

    visual: dict[str, dict[str, Any]] = {}
    for v_key, floor_gb in (
        ("local_visual_2b", 6.0),
        ("local_visual_4b", 8.0),
        ("local_visual_8b", 16.0),
    ):
        v_hint, v_reason, v_short = note(v_key, local=True)
        v_ok = is_nvidia and vram_gb >= floor_gb
        if not v_short:
            if not is_nvidia:
                v_hint, v_reason = hw_hint, hw_reason
            elif not v_ok:
                v_hint = f"本地视觉模型需 {floor_gb:.0f}GB+ 显存（当前 {vram_gb:.1f}GB）"
                v_reason = f"显存不足 {floor_gb:.0f}GB"
            else:
                v_hint = "需 llama.cpp CUDA 构建资产（资产库提供后生效）"
                v_reason = "视觉模型 CUDA 构建资产未入库"
        visual[v_key] = _cap(v_ok, False, v_hint, v_reason)

    caps = {
        "faster_whisper_gpu": _cap(whisper_ok, whisper_ready, fw_hint, fw_reason),
        "indextts2_gpu": _cap(indextts_ok, indextts_ready, tts_hint, tts_reason),
        "funasr_gpu": _cap(funasr_ok, funasr_ready, fa_hint, fa_reason),
        # 分离的 ok 就是硬件门禁：它没有静态算力下界（ORT 在 sm_52 实测可用，官方下限未核对）
        "vocal_separation_gpu": _cap(hardware_ok, separation_ready, sep_hint, sep_reason),
        **visual,
    }
    return {
        "tier": tier,
        "tier_label": tier_label,
        "vendor": vendor,
        "gpu_name": name,
        "memory_total_mb": memory_total_mb,
        "max_cuda_version": max_cuda_version,
        "cuda_runtime_installed": cuda_runtime_installed,
        "caps": caps,
        "driver_guidance": driver_guidance,
        "recommendation": recommendation,
    }
```

**注意两处判据变更是有意的**：`vocal_separation_gpu.ok` 从 `cuda_ok and vram>=4` 改为 `hardware_ok`（含驱动不可读分支），`funasr_gpu.ok` 同理——非 NVIDIA 主机的 `ok` 必须为 `False`（旧代码里 `none`/`amd` 主机的 `ok` 已是 `False`，此处只是把「驱动读不到」这一种也从 True 里摘出来）；`local_visual_*.ok` 继续用 `is_nvidia`（显存门槛与 CUDA 上限无关）。

- [ ] **Step 4: `api/system.py` 传入变体**

`health()` 的 `device_profile.profile(...)` 调用补一个关键字实参：

```python
            "device_profile": device_profile.profile(
                gpu_snapshot,
                cuda_runtime.status(data_dir)["installed"] if data_dir is not None else False,
                separation_ort=tts_runtime.ort_state(data_dir) if data_dir is not None else None,
                torch_variant=tts_runtime.torch_variant(data_dir) if data_dir is not None else None,
            ),
```

- [ ] **Step 5: 给 `api/system.py` 加测试出口（Step 1 最后一例需要）**

`health` 是 `register()` 的闭包，测试无法直接调。改为模块级函数、`register` 里引用它——顺手把 `data_dir` 变成显式参数：

```python
def health(params: dict[str, Any], data_dir: Any) -> dict[str, Any]:
    """system.health：GPU 快照 + 三处安装态 marker → 设备档位与各引擎能力结论。"""
    ...（现 health 闭包体原样搬来，data_dir 用形参）


def register(..., data_dir: Any = None) -> None:
    ...
    router.register("system.health", lambda params: health(params, data_dir))
```

并把 Step 1 里 `test_health_passes_the_tts_venv_torch_variant` 的 monkeypatch 段替换为规范写法（不再手改模块属性）：

```python
def test_health_passes_the_tts_venv_torch_variant(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.api import system as system_api
    from dramaclip.infra import device_profile as dp
    from dramaclip.infra import gpu as gpu_mod
    from dramaclip.infra.model_manager import cuda_runtime, tts_runtime

    seen: dict[str, Any] = {}

    def fake_profile(snapshot: dict[str, Any], installed: bool, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        seen["installed"] = installed
        return {"tier": "none", "caps": {}}

    monkeypatch.setattr(gpu_mod, "snapshot", lambda force=False: dict(_NONE))
    monkeypatch.setattr(dp, "profile", fake_profile)
    monkeypatch.setattr(cuda_runtime, "status", lambda _d: {"installed": False})
    monkeypatch.setattr(tts_runtime, "ort_state", lambda _d: {"variant": "unknown"})
    monkeypatch.setattr(tts_runtime, "torch_variant", lambda _d: "unknown")

    result = system_api.health({}, tmp_path)

    assert seen["torch_variant"] == "unknown", "profile 必须收到按本 data_dir 读的 torch 变体"
    assert seen["separation_ort"] == {"variant": "unknown"}
    assert result["gpu_info"]["vendor"] == "none"
```

- [ ] **Step 6: 运行本任务与既有档位测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_device_profile_multi_vendor.py tests/infra/test_gpu_and_fallback.py tests/api/test_system_health.py -q`
Expected: PASS。若 `tests/api/test_system_health.py` 不存在（`register` 的既有用例只走 router），把该路径从命令里去掉，并在 `service/tests/api/` 里为 `health()` 新增上面这一例——它是「两处读同一事实」的唯一守卫。

- [ ] **Step 7: 同步 `test_gpu_and_fallback.py` 的两处期望**

`service/tests/infra/test_gpu_and_fallback.py:217` 的 `assert device_profile.tier_of("nvidia", 0) == "low"` 改为：

```python
    # 显存读不到不是「入门档」，是未知：归 none，由驱动/厂商标签各自说清
    assert device_profile.tier_of("nvidia", 0) == "none"
```

`test_profile_caps_and_runtime_layering` 与 `test_profile_sm52_blocks_whisper_but_not_funasr` 的断言保持原样（新实现必须让它们继续绿——`hint` 文案与 `ready` 判据都没放宽）。

- [ ] **Step 8: 提交**

```bash
git status --short service/dramaclip/infra/device_profile.py service/dramaclip/api/system.py service/tests/infra/
git add service/dramaclip/infra/device_profile.py service/dramaclip/api/system.py service/tests/infra/test_device_profile_multi_vendor.py service/tests/infra/test_gpu_and_fallback.py service/tests/api/test_system_health.py
git commit -m "feat: 设备档位按宿主厂商说话——驱动三分支、cap.reason、torch sm_70 下界与真 ready"
```

---

## Task 3: 唯一设备解析入口（新增 `infra/device_resolve.py`）

**Files:**
- Create: `service/dramaclip/infra/device_resolve.py`
- Create: `service/tests/infra/test_device_resolve.py`

**Interfaces:**
- Consumes: Task 1 的 `gpu.snapshot()`；Task 2 的 `device_profile.profile(..., torch_variant=...)` 与 `device_profile.CAPS`；`cuda_runtime.status`、`tts_runtime.ort_state`、`tts_runtime.torch_variant`；`compute.normalize_requested`、`compute.ComputeUnavailableError`。
- Produces:
  - `device_resolve.DeviceResolution`（frozen dataclass，字段 `component/cap/requested/resolved/actual/device/reason/downgraded`）
  - `device_resolve.resolve(component: str, requested: str | None, data_dir: Path) -> DeviceResolution`
  - `device_resolve.ASR_ENGINES: dict[str, str]`、`device_resolve.TTS_ENGINES: dict[str, str]`（引擎名 → component）
  - `device_resolve.resolve_engine(kind: str, engine: str, requested: str | None, data_dir: Path) -> DeviceResolution | None`（`None` = 该引擎没有能力判据，调用方原样透传）
  - Task 4 的接线只读 `.device` 串；错误消息只来自 `cap.reason`/`cap.hint`，不新造文案。

- [ ] **Step 1: 写失败测试**

创建 `service/tests/infra/test_device_resolve.py`：

```python
"""设备解析：意图 + 能力表 → 本次设备。cuda 是承诺，auto 才允许落 CPU。

解析结论只是**预期**：回执的 actual 永远来自 worker/引擎证据（规格 §3.6）。
待定态绝不固化成 CPU——服务刚启动几秒内的快照不能替用户决定走 CPU。
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from dramaclip.infra import compute, device_resolve, device_profile

_COMPONENTS = (
    "asr.faster_whisper",
    "asr.sensevoice",
    "asr.paraformer",
    "tts.indextts2",
    "tts.cosyvoice",
    "tts.cosyvoice3",
)


@pytest.fixture
def fake_profile(monkeypatch: pytest.MonkeyPatch):
    """把能力表变成测试可写的字典；快照与三处安装态读取一并桩掉。

    gpu.snapshot 必须桩成「已就绪」：真探测在测试进程里是待定态，
    所有 auto/cuda 用例会集体走进 pending 分支而测不到判据。
    """
    state: dict[str, dict[str, dict[str, Any]]] = {"caps": {}}

    def _set(caps: dict[str, dict[str, Any]]) -> None:
        state["caps"] = caps

    def _fake(snapshot: dict[str, Any], installed: bool, **kwargs: Any) -> dict[str, Any]:
        return {"caps": state["caps"], "vendor": snapshot.get("vendor", "none")}

    monkeypatch.setattr(device_resolve.gpu, "snapshot", lambda force=False: {"ready": True, "vendor": "nvidia"})
    monkeypatch.setattr(device_profile, "profile", _fake)
    monkeypatch.setattr(device_resolve.cuda_runtime, "status", lambda _d: {"installed": True})
    monkeypatch.setattr(
        device_resolve.tts_runtime, "ort_state", lambda _d: {"variant": "gpu", "gpu": True}
    )
    monkeypatch.setattr(device_resolve.tts_runtime, "torch_variant", lambda _d: "cuda")
    return _set


def _ready(cap_key: str, *, ok: bool = True, reason: str = "") -> dict[str, dict[str, Any]]:
    return {cap_key: {"ok": ok, "ready": True, "hint": "", "reason": reason}}


def _not_ready(cap_key: str, *, ok: bool, reason: str) -> dict[str, dict[str, Any]]:
    return {cap_key: {"ok": ok, "ready": False, "hint": f"整句说明：{reason}", "reason": reason}}


@pytest.mark.parametrize("component", _COMPONENTS)
def test_every_mapped_component_names_a_real_cap(component: str, fake_profile) -> None:
    cap = device_resolve.resolve(component, "auto", Path("data")).cap
    assert cap in device_profile.CAPS


def test_auto_with_ready_cap_resolves_cuda(fake_profile) -> None:
    fake_profile(_ready("indextts2_gpu"))
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cuda", "cuda", "cuda")
    assert out.reason == "" and out.downgraded is False


def test_auto_with_unready_cap_goes_cpu_with_reason(fake_profile) -> None:
    fake_profile(_not_ready("indextts2_gpu", ok=True, reason="本地运行环境的 torch 是 CPU 轮"))
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cpu", "cpu", "cpu")
    assert out.reason == "本地运行环境的 torch 是 CPU 轮"
    # ok=True 而 ready=False：硬件过关、运行时没装好——这才叫「本次被降级」
    assert out.downgraded is True


def test_auto_with_hardware_exclusion_is_not_a_downgrade(fake_profile) -> None:
    fake_profile(_not_ready("indextts2_gpu", ok=False, reason="算力 sm_6.1 低于 torch cu128 下界 sm_70"))
    out = device_resolve.resolve("tts.indextts2", "auto", Path("data"))
    assert out.device == "cpu"
    assert out.downgraded is False, "永久下限不写成「降级」，否则每次日志都在喊降级"


def test_explicit_cpu_is_never_upgraded(fake_profile) -> None:
    fake_profile(_ready("faster_whisper_gpu"))
    out = device_resolve.resolve("asr.faster_whisper", "cpu", Path("data"))
    assert (out.resolved, out.actual, out.device) == ("cpu", "cpu", "cpu")
    assert out.requested == "cpu"


def test_explicit_cuda_raises_before_the_engine_is_built(fake_profile) -> None:
    fake_profile(_not_ready("indextts2_gpu", ok=False, reason="算力 sm_6.1 低于 torch cu128 下界 sm_70"))
    with pytest.raises(compute.ComputeUnavailableError) as info:
        device_resolve.resolve("tts.indextts2", "cuda", Path("data"))
    assert "tts.indextts2" in str(info.value)
    assert "算力 sm_6.1 低于 torch cu128 下界 sm_70" in str(info.value)


def test_pending_snapshot_is_handed_to_the_engine_not_forced_to_cpu(
    fake_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_profile({})
    monkeypatch.setattr(
        device_resolve.gpu,
        "snapshot",
        lambda force=False: {"ready": False, "vendor": "unknown"},
    )
    out = device_resolve.resolve("asr.faster_whisper", "cuda", Path("data"))
    assert out.device == "auto", "探测未完成时 cuda 承诺不能凭空兑现，也不能判 CPU"
    assert out.resolved == "unknown" and out.actual == "unknown"
    assert "探测中" in out.reason
    assert out.downgraded is False


def test_resolution_does_not_sign_the_receipt(fake_profile) -> None:
    """解析给的是**预期**设备，不是运行证据：结构里不许有 fallback，也不带耗时/产物字段。"""
    fake_profile(_ready("funasr_gpu"))
    out = device_resolve.resolve("asr.sensevoice", "auto", Path("data"))
    assert out.component == "asr.sensevoice" and out.cap == "funasr_gpu"
    assert out.reason == ""
    assert not hasattr(out, "fallback"), "回退是运行期事实，解析层无权代签"
    assert {f.name for f in fields(out)} == {
        "component", "cap", "requested", "resolved", "actual", "device", "reason", "downgraded",
    }, "字段膨胀等于开始替回执记账"


def test_unknown_component_is_refused(fake_profile) -> None:
    fake_profile(_ready("funasr_gpu"))
    with pytest.raises(KeyError):
        device_resolve.resolve("asr.whisper_large", "auto", Path("data"))


def test_separation_and_encode_are_not_resolvable(fake_profile) -> None:
    """§3.5/§3.6：分离恒 auto 交给 worker，编码有自己的试编解析器——这里都不许登记。"""
    fake_profile(_ready("vocal_separation_gpu"))
    for component in ("tts.separation", "video.encode", "tts.reference_clean.filter"):
        with pytest.raises(KeyError):
            device_resolve.resolve(component, "auto", Path("data"))


def test_resolve_engine_passes_through_engines_without_a_cap(fake_profile) -> None:
    fake_profile(_ready("indextts2_gpu"))
    assert device_resolve.resolve_engine("tts", "edge", "cuda", Path("data")) is None
    assert device_resolve.resolve_engine("tts", "kokoro", "cuda", Path("data")) is None
    assert device_resolve.resolve_engine("asr", "dashscope_cloud", "cuda", Path("data")) is None
    hit = device_resolve.resolve_engine("tts", "cosyvoice", "auto", Path("data"))
    assert hit is not None and hit.component == "tts.cosyvoice"


def test_unknown_requested_value_is_a_param_error(fake_profile) -> None:
    fake_profile(_ready("funasr_gpu"))
    with pytest.raises(ValueError):
        device_resolve.resolve("asr.sensevoice", "directml", Path("data"))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_device_resolve.py -q`
Expected: FAIL —`ModuleNotFoundError: No module named 'dramaclip.infra.device_resolve'`。

- [ ] **Step 3: 实现解析入口**

创建 `service/dramaclip/infra/device_resolve.py`：

```python
"""唯一设备解析入口：用户意图 + 能力表 → 本次设备（预期，不是运行证据）。

能力表（``device_profile.caps``）判「这台机器现在能不能上 CUDA」，本模块只按
``ok``/``ready``/``reason`` 取数，**不解析 hint 文案**；引擎侧不再各自读设置
（旧状：runtime/factory/pool/preview/selftest 五处各读一次 ``asr.device``/``tts.device``）。

不纳入解析的两类，各有自己的解析器并遵守同一契约「解析 → 运行证据 → ComputeReport」：
- 人声分离：没有设备开关，恒 ``auto`` 交给 worker（worker 的 provider 探测会把
  「缺 CUDA EP / CUDA 试跑失败」的真实原因写进回执；在入口预判 CPU 反而丢掉原因）。
- 视频编码：``encoder.pick_hw_encoder`` 用真实试编决定，下限不可预知，只能试。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import compute, device_profile, gpu
from dramaclip.infra.model_manager import cuda_runtime, tts_runtime

#: 引擎 → component。云端引擎与 kokoro 不在此表：kokoro 没有对应的能力判据，
#: 猜一个 cap 等于替它宣布可用性，原样透传设备串才是诚实的。
ASR_ENGINES: dict[str, str] = {
    "faster_whisper": "asr.faster_whisper",
    "sensevoice": "asr.sensevoice",
    "paraformer": "asr.paraformer",
}
TTS_ENGINES: dict[str, str] = {
    "indextts2": "tts.indextts2",
    "cosyvoice": "tts.cosyvoice",
    "cosyvoice3": "tts.cosyvoice3",
}
#: component → cap。torch cu128 那套运行时同时承担 indextts2 / cosyvoice 系，
#: 共用 ``indextts2_gpu`` 这一个 cap（键名是历史名，实质是「torch 栈 GPU」）。
_COMPONENT_CAPS: dict[str, str] = {
    "asr.faster_whisper": "faster_whisper_gpu",
    "asr.sensevoice": "funasr_gpu",
    "asr.paraformer": "funasr_gpu",
    "tts.indextts2": "indextts2_gpu",
    "tts.cosyvoice": "indextts2_gpu",
    "tts.cosyvoice3": "indextts2_gpu",
}

_PENDING_REASON = "显卡状态探测中，交给引擎自判"


@dataclass(frozen=True)
class DeviceResolution:
    component: str
    cap: str
    requested: str
    resolved: str
    actual: str
    device: str
    reason: str
    downgraded: bool = False


def resolve(component: str, requested: str | None, data_dir: Path) -> DeviceResolution:
    """把 ``requested``（auto/cuda/cpu/None）解析成引擎该收的设备串。

    ``cuda`` 是承诺：cap 不 ready 时立刻抛 ``ComputeUnavailableError``，在拉起模型
    或 worker **之前**失败。``cpu`` 恒 CPU。``auto`` 按 ready 选路，硬件过关但运行时
    未就绪时 ``downgraded=True``。快照待定 → ``device="auto"``，交给引擎自判。
    """
    cap = _COMPONENT_CAPS[component]  # 未登记的组件没有判据：KeyError 比猜一个强
    intent = compute.normalize_requested(requested)
    snapshot = gpu.snapshot()
    if not snapshot.get("ready"):
        return DeviceResolution(
            component=component,
            cap=cap,
            requested=intent,
            resolved="unknown",
            actual="unknown",
            device="auto",
            reason=_PENDING_REASON,
        )
    prof = device_profile.profile(
        snapshot,
        cuda_runtime.status(data_dir)["installed"],
        separation_ort=tts_runtime.ort_state(data_dir),
        torch_variant=tts_runtime.torch_variant(data_dir),
    )
    entry: dict[str, Any] = prof["caps"].get(cap) or {"ok": False, "ready": False, "reason": ""}
    ok = bool(entry["ok"])
    ready = bool(entry["ready"])
    reason = str(entry["reason"] or entry.get("hint") or "")
    if intent == "cuda":
        if not ready:
            raise compute.ComputeUnavailableError(
                f"{component} 请求 cuda，本机能力表判不可用：{reason or '原因未给出'}"
            )
        return DeviceResolution(component, cap, "cuda", "cuda", "cuda", "cuda", "")
    if intent == "cpu":
        return DeviceResolution(component, cap, "cpu", "cpu", "cpu", "cpu", "")
    if ready:
        return DeviceResolution(component, cap, "auto", "cuda", "cuda", "cuda", "")
    return DeviceResolution(
        component, cap, "auto", "cpu", "cpu", "cpu", reason, downgraded=ok
    )


def resolve_engine(
    kind: str, engine: str, requested: str | None, data_dir: Path
) -> DeviceResolution | None:
    """按引擎名解析；``None`` = 该引擎没有能力判据（云端/kokoro），调用方原样透传。"""
    table = ASR_ENGINES if kind == "asr" else TTS_ENGINES
    component = table.get(engine)
    if component is None:
        return None
    return resolve(component, requested, data_dir)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_device_resolve.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add service/dramaclip/infra/device_resolve.py service/tests/infra/test_device_resolve.py
git commit -m "feat: 设备解析收口到 device_resolve——cuda 是承诺，auto 才允许落 CPU"
```

---

## Task 4: 把 resolve 接到构造点（`runtime._build_transcriber` / `tts.factory.create` / 自检直连）

**Files:**
- Modify: `service/dramaclip/engines/analysis/runtime.py:82-121`（`_build_transcriber`）+ `:22-33`（`AnalysisRuntime`）
- Modify: `service/dramaclip/service_app.py:91`
- Modify: `service/dramaclip/engines/tts/factory.py:43-74`（`create`）+ `:77-87`（`capabilities`）
- Modify: `service/dramaclip/infra/model_manager/selftest.py:38-51`（`run_asr`）、`:81-99`（`run_tts`）、`:130-151`（`_build_asr`）
- Modify: `service/dramaclip/api/engines.py:71-93`（`_asr` / `_tts`）
- Modify: `service/dramaclip/api/tts.py:230-255`（`_preview_audio`）、`:308-330`（`_synthesize`）
- Modify: `service/dramaclip/api/tools.py:207-234`（`tts`）、`:248-272`（`_synthesize`）
- Modify: `service/dramaclip/engines/narration/synthesis.py:290-321`（`_EnginePool.__init__`）、`:366-372`
- Modify: `service/dramaclip/engines/narration/pipeline.py:299-331`（`synthesize_narration_texts`）
- Modify: `service/dramaclip/api/narration.py:261-269`（`_voice` 调用点）
- Test: `service/tests/engines/test_device_resolve_wiring.py`（新增）

**Interfaces:**
- Consumes: Task 3 的 `device_resolve.resolve_engine(kind, engine, requested, data_dir)`、`device_resolve.DeviceResolution`、`compute.ComputeUnavailableError`。
- Produces:
  - `runtime._build_transcriber(settings, models_dir, data_dir: Path | None = None)`
  - `runtime.AnalysisRuntime(settings, models_dir, data_dir: Path | None = None)`
  - `factory.create(engine, models_dir=None, *, api_key="", model="", device="auto", data_dir: Path | None = None)`
  - `factory.capabilities(engine, models_dir=None, data_dir: Path | None = None)`
  - `selftest.run_asr(models_dir, spec, *, device="auto", compute_type="auto", data_dir=None)`、`selftest.run_tts(..., *, device="auto", data_dir=None)`、`selftest._build_asr(models_dir, spec, device, compute_type, data_dir=None)`
  - `_synthesize(..., device="auto", data_dir=None)`（api/tts 与 api/tools 两处签名同步）、`_EnginePool(..., device="auto", data_dir=None)`、`synthesize_narration_texts(..., data_dir=None)`
  - 收口点仍只有这三处（规格 §3.6）：其余入口只是把 `context.data_dir` 传下去，不自己判断设备。

**为什么 `data_dir` 默认 `None` 而不是内部取 `resolve_data_dir()`**：`resolve_data_dir()` 会 `mkdir` 五个子目录（`infra/paths.py:24`），把它藏进引擎构造里等于允许任何测试往真实用户目录写。所以 `None` 的语义是**显式的「没有解析入口」**——原样透传意图字符串，由引擎自身的 auto 语义处理；生产入口（api 层）一律传真实 `context.data_dir`。

- [ ] **Step 1: 写失败测试**

创建 `service/tests/engines/test_device_resolve_wiring.py`：

```python
"""设备解析接线：解析发生在构造之前，引擎收到的是解析后的设备。

本文件只验**接线**（判据本身在 `tests/infra/test_device_resolve.py`）：
- `_build_transcriber` / `factory.create` 传给引擎的 `device` 来自解析结论，不是设置原值；
- 显式 `cuda` 撞上不可用的 cap 时必须**在构造引擎之前**炸——模型加载、worker 拉起
  都不该发生（规格 §3.6：cuda 是承诺）；
- 云端引擎与没有 cap 的引擎（kokoro）不进解析表：透传，不替它们宣布可用性。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis import runtime
from dramaclip.engines.analysis import transcriber as asr_mod
from dramaclip.engines.narration import synthesis as synthesis_mod
from dramaclip.engines.tts import factory
from dramaclip.engines.tts.engines import cosyvoice as cosyvoice_mod
from dramaclip.engines.tts.engines import indextts2 as indextts2_mod
from dramaclip.engines.tts.engines import kokoro as kokoro_mod
from dramaclip.infra import compute, config, device_resolve
from dramaclip.infra.model_manager import registry

_LOCAL_ASR = ("faster_whisper", "sensevoice", "paraformer")
_LOCAL_TTS = ("indextts2", "cosyvoice", "cosyvoice3")
_CAP = {
    "asr.faster_whisper": "faster_whisper_gpu",
    "asr.sensevoice": "funasr_gpu",
    "asr.paraformer": "funasr_gpu",
    "tts.indextts2": "indextts2_gpu",
    "tts.cosyvoice": "indextts2_gpu",
    "tts.cosyvoice3": "indextts2_gpu",
}


class _Recorder:
    """假解析器：按 `blocked` 集合决定抛错，按 `device` 返回解析结论。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.blocked: set[str] = set()
        self.device = "cpu"

    def __call__(
        self, kind: str, engine: str, requested: str | None, data_dir: Path
    ) -> device_resolve.DeviceResolution | None:
        self.calls.append(
            {"kind": kind, "engine": engine, "requested": requested, "data_dir": data_dir}
        )
        component = (device_resolve.ASR_ENGINES if kind == "asr" else device_resolve.TTS_ENGINES).get(engine)
        if component is None:
            return None
        if requested == "cuda" and engine in self.blocked:
            raise compute.ComputeUnavailableError(f"{component} 请求 cuda，本机能力表判不可用：测试原因")
        return device_resolve.DeviceResolution(
            component=component,
            cap=_CAP[component],
            requested=requested or "auto",
            resolved=self.device,
            actual=self.device,
            device=self.device,
            reason="",
        )


class _StubEngine:
    """替身引擎：只记构造参数，绝不加载模型。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class _ExplodingEngine:
    """被构造即失败：用来证明炸点在执行构造之前。"""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("解析失败时不允许构造引擎")


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(device_resolve, "resolve_engine", rec)
    return rec


@pytest.fixture
def asr_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FasterWhisperEngine", "SenseVoiceEngine", "ParaformerEngine"):
        monkeypatch.setattr(runtime, name, _StubEngine, raising=False)
        monkeypatch.setattr(asr_mod, name, _StubEngine, raising=False)


@pytest.fixture
def tts_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indextts2_mod, "IndexTts2Engine", _StubEngine)
    monkeypatch.setattr(cosyvoice_mod, "CosyVoiceEngine", _StubEngine)
    monkeypatch.setattr(kokoro_mod, "KokoroEngine", _StubEngine)


def _settings(**overrides: str) -> config.Settings:
    return {**config.DEFAULTS, **overrides}


def _asr_spec(engine: str) -> registry.ModelSpec:
    return next(s for s in registry.builtin_specs() if s.kind == "asr" and s.engine == engine)


def _tts_spec(engine: str) -> registry.ModelSpec:
    return next(s for s in registry.builtin_specs() if s.kind == "tts" and s.engine == engine)


def test_asr_engines_receive_resolved_device_not_the_intent(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    """设置写 auto、解析给 cpu：引擎必须收到 cpu——收到 auto 等于解析没接上。"""
    resolver.device = "cpu"
    for engine in _LOCAL_ASR:
        built = runtime._build_transcriber(
            _settings(**{"asr.engine": engine, "asr.device": "auto"}),
            tmp_path,
            tmp_path / "data",
        )
        assert built.kwargs["device"] == "cpu"
    call = resolver.calls[-1]
    assert (call["kind"], call["engine"], call["requested"]) == ("asr", _LOCAL_ASR[-1], "auto")
    assert call["data_dir"] == tmp_path / "data"


def test_asr_cuda_blocked_fails_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("FasterWhisperEngine", "SenseVoiceEngine", "ParaformerEngine"):
        monkeypatch.setattr(runtime, name, _ExplodingEngine, raising=False)
    resolver.blocked = set(_LOCAL_ASR)
    for engine in _LOCAL_ASR:
        with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
            runtime._build_transcriber(
                _settings(**{"asr.engine": engine, "asr.device": "cuda"}),
                tmp_path,
                tmp_path / "data",
            )


def test_asr_without_data_dir_passes_intent_through(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    """没有解析入口 = 透传（`resolve_data_dir()` 会 mkdir，不许藏在引擎构造里）。"""
    built = runtime._build_transcriber(
        _settings(**{"asr.engine": "sensevoice", "asr.device": "cuda"}), tmp_path
    )
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls == []


def test_asr_cloud_engine_is_never_resolved(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "DashscopeCloudAsrEngine", _StubEngine, raising=False)
    runtime._build_transcriber(
        _settings(**{"asr.engine": "dashscope_cloud", "asr.device": "cuda"}),
        tmp_path,
        tmp_path / "data",
    )
    assert resolver.calls == []


def test_tts_local_engines_receive_resolved_device(
    tmp_path: Path, resolver: _Recorder, tts_stubs: None
) -> None:
    resolver.device = "cpu"
    for engine in _LOCAL_TTS:
        built = factory.create(
            engine, tmp_path, device="auto", data_dir=tmp_path / "data"
        )
        assert built.kwargs["device"] == "cpu"
        assert resolver.calls[-1]["engine"] == engine


def test_tts_cuda_blocked_fails_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indextts2_mod, "IndexTts2Engine", _ExplodingEngine)
    resolver.blocked = {"indextts2"}
    with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
        factory.create("indextts2", tmp_path, device="cuda", data_dir=tmp_path / "data")


def test_kokoro_has_no_cap_so_device_passes_through(
    tmp_path: Path, resolver: _Recorder, tts_stubs: None
) -> None:
    """kokoro 不在解析表：猜一个 cap 等于替它宣布可用性，透传才是诚实的。"""
    built = factory.create("kokoro", tmp_path, device="cuda", data_dir=tmp_path / "data")
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls[-1]["engine"] == "kokoro"


def test_edge_is_never_resolved(tmp_path: Path, resolver: _Recorder) -> None:
    factory.create("edge", tmp_path, device="cuda", data_dir=tmp_path / "data")
    assert resolver.calls == []


def test_engine_pool_forwards_data_dir(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """narration 池的显式引擎在构造时就得带上解析入口。"""
    monkeypatch.setattr(synthesis_mod, "create_tts", _StubEngine)
    resolver.device = "cpu"
    pool = synthesis_mod._EnginePool(
        "indextts2", tmp_path, None, device="auto", data_dir=tmp_path / "data"
    )
    assert pool._instances["indextts2"] is not None
    assert resolver.calls[-1]["data_dir"] == tmp_path / "data"


def test_selftest_build_asr_resolves_before_construction(
    tmp_path: Path, resolver: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dramaclip.infra.model_manager import selftest

    monkeypatch.setattr(asr_mod, "SenseVoiceEngine", _ExplodingEngine)
    resolver.blocked = {"sensevoice"}
    with pytest.raises(compute.ComputeUnavailableError, match="测试原因"):
        selftest._build_asr(
            tmp_path, _asr_spec("sensevoice"), "cuda", "auto", data_dir=tmp_path / "data"
        )


def test_selftest_build_asr_without_data_dir_passes_through(
    tmp_path: Path, resolver: _Recorder, asr_stubs: None
) -> None:
    from dramaclip.infra.model_manager import selftest

    built = selftest._build_asr(tmp_path, _asr_spec("sensevoice"), "cuda", "auto")
    assert built.kwargs["device"] == "cuda"
    assert resolver.calls == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/test_device_resolve_wiring.py -q`
Expected: FAIL——`_build_transcriber()` 收到第 3 个位置参数直接 `TypeError`，`factory.create()` / `_EnginePool()` / `_build_asr()` 因不认识 `data_dir` 关键字同样报错。

- [ ] **Step 3: 改 `runtime.py`**

`AnalysisRuntime` 存下 `data_dir` 并透传（`:22-33`）：

```python
class AnalysisRuntime:
    """transcriber 等引擎的懒加载单例容器（线程安全由构建锁保证）。"""

    def __init__(self, settings: config.Settings, models_dir: Path, data_dir: Path | None = None) -> None:
        self._settings = settings
        self._models_dir = models_dir
        self._data_dir = data_dir
        self._transcriber: AsrEngine | None = None

    def transcriber(self) -> AsrEngine:
        if self._transcriber is None:
            self._transcriber = _build_transcriber(
                self._settings, self._models_dir, self._data_dir
            )
        return self._transcriber
```

`_build_transcriber`：签名加第三参，在云端分支 return **之后**解析（云端引擎不进表），三处 `settings.get("asr.device", "auto")` 全部换成解析结果：

```python
def _build_transcriber(
    settings: config.Settings, models_dir: Path, data_dir: Path | None = None
) -> AsrEngine:
    engine = settings.get("asr.engine", "faster_whisper")
    if engine not in supported():
        available = " / ".join(sorted(supported()))
        raise ValueError(f"未知 ASR 引擎: {engine}（可用: {available}）")
    if engine == "dashscope_cloud":
        ...  # 原样：云端引擎忽略本地设备请求
        return DashscopeCloudAsrEngine(...)
    device = resolve_asr_device(engine, settings.get("asr.device", "auto"), data_dir)
    if engine == "paraformer":
        diarize = _resolve_diarization(
            settings, engine=engine, supports=ParaformerEngine.supports_diarization
        )
        return ParaformerEngine(
            models_dir=models_dir,
            vad_model_dir=models_dir / "asr" / "fsmn-vad" if diarize else None,
            spk_model_dir=models_dir / "asr" / "campplus" if diarize else None,
            num_speakers=config.get_int(settings, "asr.num_speakers"),
            device=device,
        )
    # 剩下两个引擎没有说话人通道：auto 关、false 关，显式 true 在核验里炸
    _resolve_diarization(settings, engine=engine, supports=False)
    if engine == "sensevoice":
        return SenseVoiceEngine(models_dir=models_dir, device=device)
    model_size = settings.get("asr.model", "base")
    return FasterWhisperEngine(
        model_size,
        device=device,
        models_dir=models_dir / "asr" / "faster-whisper",
        compute_type=settings.get("asr.compute_type", "auto"),
    )


def resolve_asr_device(engine: str, requested: str | None, data_dir: Path | None) -> str:
    """设备解析的唯一入口是 `device_resolve`；这里只决定「有没有解析入口」。

    `data_dir is None` 原样透传意图：`resolve_data_dir()` 会 mkdir，不该藏在引擎构造里
    （测试会因此往真实用户目录写）。自检（`selftest._build_asr`）调同一个函数，判据
    只有这一份。`compute_type` 不在解析范围——它是 ctranslate2 的量化档位
    （int8/float16），CPU 上同样有意义。
    """
    if data_dir is None:
        return requested or "auto"
    resolution = device_resolve.resolve_engine("asr", engine, requested, data_dir)
    return resolution.device if resolution is not None else (requested or "auto")
```

顶部 import 增加 `from dramaclip.infra import device_resolve`。

- [ ] **Step 4: 改 `factory.py`**

```python
def create(
    engine: str,
    models_dir: Path | None = None,
    *,
    api_key: str = "",
    model: str = "",
    device: str = "auto",
    data_dir: Path | None = None,
) -> TtsEngine:
    device = _resolve_device(engine, device, data_dir)
    if engine == "edge":
        ...  # 以下分支原样，仍用 device
```

```python
def _resolve_device(engine: str, device: str, data_dir: Path | None) -> str:
    """TTS 侧的设备收口：与 `_build_transcriber` 同一套语义。

    云端（edge/cosyvoice_cloud）与 kokoro 不在 `TTS_ENGINES` 表里，返回 `None` 即透传——
    kokoro 没有能力判据，替它猜一个 cap 等于凭空宣布可用性。
    """
    if data_dir is None:
        return device
    resolution = device_resolve.resolve_engine("tts", engine, device, data_dir)
    return resolution.device if resolution is not None else device
```

`capabilities()` 同步加参数（api/engines 的 caps 探测与工厂共用同一判据；显式 `cuda` 撞上
不可用 cap 时 `ComputeUnavailableError` 落进既有 try/except，变成卡上的 reason 而不是炸掉整页）：

```python
def capabilities(
    engine: str, models_dir: Path | None = None, data_dir: Path | None = None
) -> EngineCaps:
    try:
        return create(engine, models_dir, data_dir=data_dir).capabilities()
    except Exception as exc:  # noqa: BLE001
        return EngineCaps(available=False, reason=f"能力探测失败：{type(exc).__name__}: {exc}")
```

顶部 import 增加 `from dramaclip.infra import device_resolve`。

- [ ] **Step 5: 改 `selftest.py` 与 `api/engines.py`**

`run_asr` / `run_tts` / `_build_asr` 各加 `data_dir: Path | None = None`（关键字参数，位置调用兼容），并把解析交给引擎构造点：

```python
def _build_asr(
    models_dir: Path,
    spec: ModelSpec,
    device: str,
    compute_type: str,
    data_dir: Path | None = None,
) -> Any:
    from dramaclip.engines.analysis.runtime import resolve_asr_device
    from dramaclip.engines.analysis.transcriber import (
        FasterWhisperEngine,
        ParaformerEngine,
        SenseVoiceEngine,
    )

    device = resolve_asr_device(spec.engine, device, data_dir)
    if spec.engine == "faster_whisper":
        ...  # 其余原样
```

> 自检调 `runtime.resolve_asr_device` 而不是复制一份判断：「自检能过、正式转写却是另一条
> 设备路」正是规格 §1 里那类假读数。

`run_asr` 内的调用改为 `_build_asr(models_dir, spec, device, compute_type, data_dir)`；
`run_tts:99` 改为 `factory.create(spec.engine, models_dir, device=device, data_dir=data_dir)`。

`api/engines.py`：`_asr`/`_tts` 把真实 data_dir 交下去（这是规格里的「自检直连」收口点，解析本身在引擎构造处发生）：

```python
    return selftest_mod.run_asr(
        models_dir, spec, device=device, compute_type=compute_type, data_dir=context.data_dir
    )
```

```python
    result = selftest_mod.run_tts(
        models_dir, context.work_dir, spec, voice, device=device, data_dir=context.data_dir
    )
    caps = factory.capabilities(spec.engine, models_dir, data_dir=context.data_dir)
```

- [ ] **Step 6: 改 api 侧合成入口（tts / tools）**

`api/tts.py`：`_preview_audio` 取 `device` 后原样传，`_synthesize` 增加 `data_dir` 并交进工厂。

```python
    return _synthesize(
        engine,
        voice,
        text,
        models_dir,
        root,
        key,
        api_key=api_key,
        model=model,
        device=device,
        data_dir=context.data_dir,
    )
```

```python
def _synthesize(
    engine: str,
    voice: str,
    text: str,
    models_dir: Path,
    root: Path,
    key: str,
    api_key: str = "",
    model: str = "",
    device: str = "auto",
    data_dir: Path | None = None,
) -> tuple[Path, ComputeReport | None]:
    ...
        synthesizer = create_tts(
            engine,
            models_dir,
            api_key=api_key,
            model=model,
            device=device,
            data_dir=data_dir,
        )
```

> 显式 `cuda` 撞上不可用 cap 时，`ComputeUnavailableError` 被既有的
> `except Exception` 包成 `RpcDomainError(_ERR_TTS_SYNTH, "试听合成失败（引擎=…）：…")`，
> 原因原文可见——不静默换引擎（试听纪律的既有口径不变）。

`api/tools.py`：`tts()` 传 `data_dir=context.data_dir`，本地 `_synthesize` 包装器加同名关键字参数并透传给 `tts_api._synthesize`。

- [ ] **Step 7: 改 narration 链路（pipeline → pool → 工厂）**

`_EnginePool.__init__` 增加 `data_dir: Path | None = None`，存 `self._data_dir`，两处
`create_tts(...)` 都带上 `data_dir=self._data_dir`。`synthesize_narration_texts` 增加
keyword-only 参数 `data_dir: Path | None = None` 并传给池。`api/narration.py:261` 传
`data_dir=context.data_dir`。

```python
def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
    *,
    source_durations: dict[str, float],
    log: LogFn | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    data_dir: Path | None = None,
) -> PlanData:
    ...
    pool = _EnginePool(
        engine_setting,
        models_dir,
        log,
        api_key=settings.get("tts.api_key", ""),
        model=settings.get("tts.model", ""),
        device=str(settings.get("tts.device") or "auto"),
        data_dir=data_dir,
    )
```

> 为什么不从 `models_dir.parent` 反推 data_dir：`models_dir` 是调用方给的（api 侧是
> `context.data_dir / "models"`，测试里常是 `tmp_path`），`.parent` 猜出来的目录去读
> marker 会把「测试目录没装运行环境」读成「本机没装」——那是假阴性。

- [ ] **Step 8: 改 `service_app.py`**

```python
            analysis_runtime=AnalysisRuntime(settings, data_dir / "models", data_dir),
```

- [ ] **Step 9: 运行确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/test_device_resolve_wiring.py tests/engines/analysis/test_runtime.py tests/engines/test_tts_factory.py tests/infra/model_manager/test_selftest_build.py tests/api/test_engines_selftest.py tests/api/test_engines_tts_caps.py tests/api/test_tts_preview.py tests/api/test_tts_preview_compute.py tests/api/test_selftest_compute.py -q`
Expected: PASS。

> 实测订正（执行时踩到，写成事实而非断言）：既有用例里 **5 处替身签名会挡住新参数**，
> 必须同步改（本任务原先假设「一条不改地绿」是错的）：
> `tests/engines/narration/test_engine_fallback.py` 的 `fake_create`、
> `tests/api/test_tts_preview.py` 的两处 `_create`、`tests/api/test_engines_tts_caps.py`
> 的三处 `factory.create` 替身都要接 `data_dir`；`tests/api/test_tts_preview_compute.py:71`
> 的假 context 缺 `data_dir` 字段（真 AppContext 有）；
> `tests/api/test_engines_selftest.py` 的 `_build_asr` recorder 按位置解包 4 个参数，
> 第 5 个参数进来后 `ValueError: too many values to unpack`——顺手断言 `data_dir == tmp_path`，
> 这条反而变强了。其余替身确实 `**_a/**_k` 吸收参数。

Run: `cd service && ../.venv/Scripts/python -m pytest tests -q`
Expected: 与基线同数（1704 passed / 1 skipped）。

> 实测订正（Task 4 执行时）：全量跑的是 **1778 例、全点、0 跳过、exit 0**。多出的 74
> 例来自 P1-P3 与批次四 Task 1-3 的新增用例，1704 那个数是批次四之前的基线，别再拿它
> 对表。消失的那 1 个跳过不是丢用例：全仓只有两处条件跳过
> （`test_segment_resume` 的「随包 ffmpeg 不存在」、`test_funasr_device_truth` 的
> 「本机 torch 带 CUDA」），0 个 `s` 说明两处都不触发、两个用例实际跑了。
> 另：`pytest ... | tail` 拿到的退出码是 `tail` 的，必须
> `> file 2>&1; echo "EXIT=$?"` 才是真退出码。

- [ ] **Step 10: 提交**

```bash
git add service/dramaclip/engines/analysis/runtime.py service/dramaclip/service_app.py service/dramaclip/engines/tts/factory.py service/dramaclip/infra/model_manager/selftest.py service/dramaclip/api/engines.py service/dramaclip/api/tts.py service/dramaclip/api/tools.py service/dramaclip/engines/narration/synthesis.py service/dramaclip/engines/narration/pipeline.py service/dramaclip/api/narration.py service/tests/engines/test_device_resolve_wiring.py
git commit -m "feat: 设备解析接到构造点——cuda 在拉起模型前失败，解析入口只此三处"
```

> 执行时改道（业主批准）：Task 1-3 的三笔提交先落了，但它们依赖的地基没入账——
> `infra/compute.py`、迁移 024、`tts_runtime.ort_state` 全在工作区未跟踪/未提交，
> 干净签出 HEAD 直接 `ModuleNotFoundError`。而 Task 4/5/6 的改动与 P1-P3 未入账的
> 改动落在同一批文件里（`selftest.py` 同时含 P1 的自检回执与 Task 4 的 `data_dir`，
> `encoder.py` 同时含 P1 的 `compute_sink` 与 Task 5 的 AMF 候选序），按文件粒度
> 不可分。所以本任务与 Task 5/6 的独立提交合并进一笔「基础账」，避免造出一笔已知红的
> 中间提交；下面的 Task 5/6 提交步同理，不再单列。

---

## Task 5: 视频硬编候选序加 AMF（`encoder.py` + `compute.py` 注释）

**Files:**
- Modify: `service/dramaclip/engines/exporter/encoder.py:450`（`_HW_CANDIDATES_BY_PLATFORM`）
- Modify: `service/dramaclip/engines/exporter/encoder.py:470-480`（`_video_codec_params`）
- Modify: `service/dramaclip/engines/exporter/encoder.py:562`（`_HW_ENCODERS`）
- Modify: `service/dramaclip/infra/compute.py:1-8`（仅模块注释）
- Test: `service/tests/engines/exporter/test_hw_probe.py`

**Interfaces:**
- Consumes: 既有的 `_hw_candidates()` / `_hw_probe_args()` / `_run_cut()` / `pick_hw_encoder()` / `_fallback_eligible()` 全部不变形。
- Produces: `h264_amf` 成为 win32 第二候选、`_HW_ENCODERS` 的一员；`_video_codec_params("h264_amf")` 是 AMF 参数的**唯一定义处**（正式段编码与探针共用）。
- 不改：`_compute_requested()`（`encoder.py:741`——任何非 `auto`/`cpu` 值已映射为 `cuda`，AMF 天然落进去）、`pick_hw_encoder()` 的缓存与哨兵逻辑、`darwin`/`linux` 候选序（macOS 另立规格）、段级回退与整片 libx264 统一重跑的机制。

> 规格 §4.3 写的 `_is_hw_encoder()` 在代码里**不存在**，硬编判定用的是 `_HW_ENCODERS` 这个
> frozenset（`_fallback_eligible()` 读它）。本任务对着 `_HW_ENCODERS` 与 `_fallback_eligible()`
> 断言，规格文字在 Task 11 一并订正——不为了对上一句话而新造一个只有测试在用的包装函数。

- [ ] **Step 1: 写失败测试**

在 `service/tests/engines/exporter/test_hw_probe.py` 里**替换** `test_candidate_order_by_platform`（`:42-45`）并追加以下用例。替换不是放宽：断言从「两项」变成「三项且顺序固定」，任何一项丢失或错位都会红。

```python
def test_candidate_order_by_platform() -> None:
    """win32 三厂商按 NVIDIA→AMD→Intel 排：N 卡第一次命中，AMD 第二次，核显兜底。"""
    assert encoder._hw_candidates("win32") == ["h264_nvenc", "h264_amf", "h264_qsv"]
    assert encoder._hw_candidates("darwin") == ["h264_videotoolbox"]
    assert encoder._hw_candidates("linux") == ["h264_nvenc", "h264_qsv"]
```

把 `:65` 的参数化列表补上 `"h264_amf"`（探针与正式编码同形状这条纪律对新候选同样生效）：

```python
@pytest.mark.parametrize("codec", ["h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"])
```

追加：

```python
def test_amf_params_align_with_nvenc_quality() -> None:
    """cqp 22 对齐 NVENC 的 vbr/cq 22 与 QSV 的 global_quality 22；B 帧常规略降。"""
    assert encoder._video_codec_params("h264_amf") == [
        "-usage", "transcoding",
        "-quality", "quality",
        "-rc", "cqp",
        "-qp_i", "22", "-qp_p", "22", "-qp_b", "24",
    ]


def test_amf_selected_when_nvenc_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """AMD 主机：nvenc 黑帧真试编失败后继续试 AMF 并命中，qsv 不再试。"""
    monkeypatch.setattr(
        encoder,
        "_hw_candidates",
        lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"],
    )
    seen_args, _ = _stub_run_cut(monkeypatch, fail={"h264_nvenc"})

    assert encoder.pick_hw_encoder() == "h264_amf"
    assert len(seen_args) == 2, "命中即停：不该再试第三个候选"


def test_amf_failure_falls_through_to_qsv(monkeypatch: pytest.MonkeyPatch) -> None:
    """AMF 在 NVIDIA 机器上失败属预期：继续往下走，不影响最终选中 QSV。"""
    monkeypatch.setattr(
        encoder,
        "_hw_candidates",
        lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"],
    )
    seen_args, _ = _stub_run_cut(monkeypatch, fail={"h264_nvenc", "h264_amf"})

    assert encoder.pick_hw_encoder() == "h264_qsv"
    assert len(seen_args) == 3


def test_all_three_win32_candidates_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        encoder,
        "_hw_candidates",
        lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"],
    )
    seen_args, _ = _stub_run_cut(
        monkeypatch, fail={"h264_nvenc", "h264_amf", "h264_qsv"}
    )

    assert encoder.pick_hw_encoder() is None
    assert len(seen_args) == 3, "全失败要逐个试过才有资格说没有硬编"


def test_amf_is_a_hw_encoder_for_segment_fallback() -> None:
    """段级回退与整片统一重跑的判定必须认 AMF，否则 AMF 段失败不会触发 libx264 重跑。"""
    assert "h264_amf" in encoder._HW_ENCODERS
    args = encoder.cut_segment_args(
        "src.mp4", "seg.mp4", start=0, end=1, audio="original",
        tts_audio=None, rng=random.Random(0), video_codec="h264_amf",
    )
    exc = runner.FfmpegError("AMF 会话数满", kind="codec")
    assert encoder._fallback_eligible(exc, args) is True
    assert encoder._fallback_eligible(exc, encoder._args_with_codec(args, "libx264")) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_hw_probe.py -q`
Expected: FAIL——候选序少 AMF、`_video_codec_params` 返回 libx264 默认参数、`_HW_ENCODERS` 不含 amf。

- [ ] **Step 3: 改 `encoder.py`**

候选序（`:450`）：

```python
_HW_CANDIDATES_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    # win32 三厂商：N 卡第一次命中；AMD 主机 nvenc 黑帧失败后第二次命中 AMF；
    # Intel 核显最后兜底。全失败才 libx264（顺序理由见规格 §4.1）。
    "win32": ("h264_nvenc", "h264_amf", "h264_qsv"),
    "darwin": ("h264_videotoolbox",),
}
```

质量参数（在 qsv 分支之后插入 AMF 分支）：

```python
    if video_codec == "h264_amf":
        # cqp 22 对齐 NVENC 的 vbr/cq 22 与 QSV 的 global_quality 22；usage=transcoding
        # 对文件导出而非低延迟场景。参数只在这一处定义，探针与正式段共用。
        return [
            "-usage", "transcoding",
            "-quality", "quality",
            "-rc", "cqp",
            "-qp_i", "22", "-qp_p", "22", "-qp_b", "24",
        ]
```

段级回退判定表（`:562`）：

```python
_HW_ENCODERS = frozenset({"h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"})
```

- [ ] **Step 4: 改 `compute.py` 模块注释**

只补词汇表，无行为改动（`:4-5`）：

```python
`actual` 允许视频编码器名（nvenc/amf/qsv/libx264），不局限在设备三元组；视频编码
```

- [ ] **Step 5: 运行确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter -q`
Expected: PASS，含既有段级回退与统一重跑用例（它们按 `_HW_ENCODERS` 参数化，新候选进表后必须一起绿）。

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/engines/exporter/encoder.py service/dramaclip/infra/compute.py service/tests/engines/exporter/test_hw_probe.py
git commit -m "feat: win32 硬编候选序加 AMF（NVENC→AMF→QSV），AMF 段纳入回退判定"
```

---

## Task 6: 验真脚本改多厂商选路（`scripts/verify_gpu_coverage.py`）

**Files:**
- Modify: `scripts/verify_gpu_coverage.py:47`（`_HW_ENCODERS`）
- Modify: `scripts/verify_gpu_coverage.py:439-447`（`_nvenc_probe` → `_select_hw_encoder`）
- Modify: `scripts/verify_gpu_coverage.py:546-559`（两个 cuda 检查）
- Modify: `scripts/verify_gpu_coverage.py:597-602`（`_environment()` 增加 `host_gpu`）
- Test: `service/tests/test_verify_gpu_coverage.py`

**Interfaces:**
- Consumes: `encoder._hw_candidates()`、`encoder._hw_probe_args()`、`encoder._run_cut()`、`gpu.detect()`。
- Produces:
  - `_select_hw_encoder() -> tuple[str, str]`：`(第一个真试编通过的编码器, 被跳过的候选原因串)`；全失败抛 `Unsupported`，reason 逐项列出。
  - `_environment()["host_gpu"]`：`{vendor, name, driver_version, adapters:[{name, vendor, driver_version}]}`，不含任何用户素材路径。
- 组件名保持 `video.encode.cuda` / `video.ai_label.cuda` 不变——发布门禁的既有 `--require` 键，改名将让门禁静默失配（「本轮没有产出该组件的结果」）。

> 候选序与参数**只读 encoder 的同一处函数**（规格 §5.2）：脚本里不再出现 `"h264_nvenc"` 字面量，
> 也不另写一张表。这是 §1 根因「第二份真相源」在验收侧的复发点。

- [ ] **Step 1: 写失败测试**

在 `service/tests/test_verify_gpu_coverage.py` 追加（沿用既有 `mod` fixture——它用 importlib 加载脚本）：

```python
def test_hw_encoders_include_amf(mod) -> None:
    assert "h264_amf" in mod._HW_ENCODERS


def test_judge_actual_accepts_amf_for_cuda(mod) -> None:
    """video.* 的 requested=cuda 语义是「请求硬件编码」：actual 说出到底是谁。"""
    assert mod.judge_actual("video.encode", "cuda", "h264_amf") == ""
    assert mod.judge_actual("video.encode", "cuda", "h264_nvenc") == ""
    assert mod.judge_actual("video.encode", "cuda", "h264_qsv") == ""
    assert mod.judge_actual("video.encode", "cuda", "libx264")


def test_select_hw_encoder_returns_first_working_candidate(mod, monkeypatch) -> None:
    from dramaclip.engines.exporter import encoder

    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"]
    )

    def fake_run_cut(args, cancel=None, **kwargs):
        if "h264_nvenc" in args:
            raise RuntimeError("NVENC: 驱动残缺")

    monkeypatch.setattr(encoder, "_run_cut", fake_run_cut)
    codec, skipped = mod._select_hw_encoder()
    assert codec == "h264_amf"
    assert "h264_nvenc" in skipped, "被跳过的候选要留原因，不然 AMD 主机看不出 NVENC 为什么不算数"


def test_select_hw_encoder_all_fail_lists_every_candidate(mod, monkeypatch) -> None:
    from dramaclip.engines.exporter import encoder

    monkeypatch.setattr(
        encoder, "_hw_candidates", lambda platform=None: ["h264_nvenc", "h264_amf", "h264_qsv"]
    )
    seen: list[str] = []

    def fake_run_cut(args, cancel=None, **kwargs):
        seen.append(args[args.index("-c:v") + 1])
        raise RuntimeError("没有硬编")

    monkeypatch.setattr(encoder, "_run_cut", fake_run_cut)
    with pytest.raises(mod.Unsupported, match="h264_qsv") as caught:
        mod._select_hw_encoder()
    assert seen == ["h264_nvenc", "h264_amf", "h264_qsv"], "unsupported 必须逐项试过"
    assert "h264_nvenc" in str(caught.value) and "没有硬编" in str(caught.value)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/test_verify_gpu_coverage.py -q`
Expected: FAIL——`_HW_ENCODERS` 无 amf、`judge_actual` 判 AMF 违规、`_select_hw_encoder` 不存在（`AttributeError`）。

- [ ] **Step 3: 改脚本**

`:47`：

```python
_HW_ENCODERS = frozenset({"h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"})
```

`:439-447` 整段替换（删掉 `_nvenc_probe` 的硬编码 NVENC）：

```python
def _select_hw_encoder() -> tuple[str, str]:
    """按 encoder 的候选序逐个真试编，返回（首个通过者, 跳过项原因）。

    候选序与探针形状都读 encoder 的同一处函数：脚本另写一张表就会出现在
    「产品能导出、验收说 unsupported」的两套结论（规格 §5.2）。全失败抛
    `Unsupported`——本机没有硬编不是产品失败，但必须逐项说清为什么不算。
    """
    from dramaclip.engines.exporter import encoder

    skipped: list[str] = []
    for codec in encoder._hw_candidates():
        try:
            encoder._run_cut(encoder._hw_probe_args(codec), timeout_s=30)
        except Exception as exc:  # noqa: BLE001 - 真试编失败即该候选在本机不可用
            skipped.append(f"{codec}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        return codec, "；".join(skipped)
    raise Unsupported(
        "本机没有任何硬编候选通过真试编：" + ("；".join(skipped) or "候选序为空")
    )
```

`:546-559` 两个 cuda 检查改为先选编码器再拿它跑真实 1s 段：

```python
def _video_encode_cuda(ctx: Context) -> CheckFn:
    def run() -> tuple[str, str]:
        codec, skipped = _select_hw_encoder()
        return _video_encode(ctx, codec), skipped

    return run


def _video_ai_label_cuda(ctx: Context) -> CheckFn:
    def run() -> tuple[str, str]:
        codec, skipped = _select_hw_encoder()
        actual, note = _video_ai_label(ctx, codec)
        return actual, f"{note}｜候选回落：{skipped}" if skipped else note

    return run
```

`:597-602` `_environment()` 在 `platform/python/interpreter` 之后补宿主事实：

```python
    try:
        from dramaclip.infra import gpu

        host = gpu.detect()
        info["host_gpu"] = {
            "vendor": host.get("vendor"),
            "name": host.get("name"),
            "driver_version": host.get("driver_version"),
            "adapters": [
                {
                    "name": a.get("name"),
                    "vendor": a.get("vendor"),
                    "driver_version": a.get("driver_version"),
                }
                for a in (host.get("adapters") or [])
            ],
        }
    except Exception as exc:  # noqa: BLE001 - 宿主探测失败不是验收失败
        info["host_gpu"] = f"unavailable: {type(exc).__name__}"
```

- [ ] **Step 4: 运行确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/test_verify_gpu_coverage.py -q`
Expected: PASS，输出无 warning。

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter tests/test_verify_gpu_coverage.py -q`
Expected: PASS（两侧 `_HW_ENCODERS` 词汇表一致）。

- [ ] **Step 5: 提交**

```bash
git add scripts/verify_gpu_coverage.py service/tests/test_verify_gpu_coverage.py
git commit -m "feat: 验真脚本按 encoder 候选序选硬编并记录宿主显卡事实（不再硬编码 NVENC）"
```

---

## Task 7: 分离设备解耦 + 清洗留痕入库（`auto_voice` / `api.tts` / `api.export` / `JobStore`）

**Files:**
- Modify: `service/dramaclip/engines/tts/reference_clean.py`（新增 `filter_report()`）
- Modify: `service/dramaclip/engines/tts/auto_voice.py`（去掉 `device` 参数、滤镜回执）
- Modify: `service/dramaclip/infra/jobs.py:111-116` 附近（新增 `set_ref_id`）
- Modify: `service/dramaclip/api/tts.py:47-75`（`auto_voice`）、`:76-125`（`clean_reference`）
- Modify: `service/dramaclip/api/export.py:84-92`（`ExportRun`）、`:664-692`（receipt 合并）、`:736-768`（`_ensure_voiced`）、`:771-831`（`_ensure_clone_voice`）
- Modify: `protocol/ts/index.ts:706`（`TtsAutoVoiceResult`）、`:728`（`TtsCleanReferenceResult`）各加 `job_id`
- Modify: `protocol/schemas/tts.json`（同两个方法的 `result.required` + `properties`）
- Test: `service/tests/engines/tts/test_auto_voice_clean.py`、`service/tests/api/test_tts_clean_reference.py`、`service/tests/api/test_export_voice_preflight.py`、`service/tests/infra/test_jobs.py`

**Interfaces:**
- Consumes: `vocal_separation.clean_reference(models_dir, src, *, device="auto")`（参数形状不变，规格 §3.5 只改「谁决定传什么」）、`JobStore.create/mark_running/set_compute/mark_completed/mark_failed`、`exports_repo.set_compute`。
- Produces:
  - `reference_clean.filter_report(reason: str) -> ComputeReport`（component `tts.reference_clean.filter`）
  - `auto_voice.extract_auto_voice(conn, data_dir, episodes)`（**没有** `device` 参数）、返回 dict 的 `compute` 在两条路径下都是非空回执
  - `JobStore.set_ref_id(job_id: str, ref_id: str) -> None`
  - `ExportRun.voice_reports: list[dict[str, Any]]`（frozen dataclass 的 `field(default_factory=list)`）
  - `jobs.type` 新值 `"voice_clean"`（无 CHECK 约束，无需迁移）

**降级链的落点（规格 §3.5）**：`CUDA 分离 → CPU 分离 → 滤镜`。第二档不需要新代码——`separation_worker` 的 `auto` 路径已经做了「CUDA 试跑失败→整段 CPU 重跑并写 fallback 原因」（`workers/separation_worker.py:192-215`）。第一档之所以今天跳不到第二档，是因为调用方把 `tts.device` 当成显式承诺传了进去：显式 `cuda` 一失败就抛，`auto_voice` 的 `except` 直接落到滤镜。所以本任务的改动是**删掉继承**，链就通了。

> 滤镜回执为什么不能写 `fallback=True`：`ComputeReport` 的不变量要求 fallback 必须是
> `requested=auto + resolved=cuda + actual=cpu`（`infra/compute.py:44-52`），而滤镜链从头到尾
> 没试过 GPU，写 fallback 就是造假账。真实语义是 `requested=auto`、`resolved=cpu`、
> `actual=cpu`，原因写在 `reason` 里。

- [ ] **Step 1: 写失败测试（滤镜一档）**

`service/tests/engines/tts/test_auto_voice_clean.py`——把 `:32-53` 的 `test_extract_uses_separation_and_reports_compute` 与 `:56-77` 的 `test_extract_filter_fallback_is_visible` **整段替换**（不是放宽：断言从「继承 tts.device」翻转为「绝不继承」，从「滤镜没有回执」翻转为「滤镜必须有回执」）：

```python
def test_extract_always_starts_separation_at_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tts.device 只承诺 torch 那条栈：分离恒 auto，由 worker 自己探 CUDA EP。

    继承 tts.device 会造出两个方向都错的结论（规格 §3.5）：为躲 IndexTTS 报错把
    tts.device 设成 CPU 的主机顺手关掉可用的 GPU 分离；设成 CUDA 而 ORT 是 CPU 轮的
    主机则让分离硬失败并直接掉到滤镜——CUDA 一失败就跳滤镜那条路必须不可达。
    """
    seen: dict[str, object] = {}
    report = ComputeReport(
        component="tts.separation", requested="auto", resolved="cpu", actual="cpu",
        reason="CUDA EP 缺失",
    )

    def fake_separation(_models: Path, _src: Path, **kwargs: Any) -> SeparationResult:
        seen.update(kwargs)
        out = tmp_path / "clean.wav"
        out.write_bytes(b"clean")
        return SeparationResult(path=out, compute=report)

    monkeypatch.setattr(vocal_separation, "clean_reference", fake_separation)

    result = _run_extract(tmp_path, monkeypatch)

    assert seen["device"] == "auto"
    assert result["cleaned_with"] == "separation"
    assert result["compute"]["actual"] == "cpu"
    assert result["compute"]["reason"] == "CUDA EP 缺失"


def test_extract_signature_has_no_device() -> None:
    """`device` 参数整个删掉：留着就是给「顺手传 tts.device」留门。"""
    params = inspect.signature(auto_voice.extract_auto_voice).parameters
    assert "device" not in params


def test_extract_filter_fallback_reports_cpu_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """滤镜兜底也要有回执：component 说方法，reason 说分离为什么没用。"""
    def fail_separation(_models: Path, _src: Path, **_kwargs: Any) -> SeparationResult:
        raise RuntimeError("TTS 运行环境未安装")

    def fake_filter(src: Path) -> Path:
        out = src.with_name("filtered.wav")
        out.write_bytes(b"filtered")
        return out

    monkeypatch.setattr(vocal_separation, "clean_reference", fail_separation)
    monkeypatch.setattr(reference_clean, "clean_reference", fake_filter)

    result = _run_extract(tmp_path, monkeypatch)

    assert result["cleaned_with"] == "filter"
    assert "TTS 运行环境未安装" in result["clean_reason"]
    report = result["compute"]
    assert report["component"] == "tts.reference_clean.filter"
    assert (report["requested"], report["resolved"], report["actual"]) == ("auto", "cpu", "cpu")
    assert report["fallback"] is False, "滤镜从没试过 GPU，写 fallback 就是造假账"
    assert "TTS 运行环境未安装" in report["reason"]
```

文件顶部补 `import inspect`，并把 `_run_extract` 的调用改为不再传 `device`（`:31` 保持 `auto_voice._extract_locked(None, tmp_path, [])`）。

- [ ] **Step 2: 运行确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/tts/test_auto_voice_clean.py -q`
Expected: FAIL——`clean_reference` 仍收到调用方透传的 device、滤镜路径 `compute is None`、`extract_auto_voice` 仍有 `device` 形参。

- [ ] **Step 3: 改 `reference_clean.py` 与 `auto_voice.py`**

`reference_clean.py`（`cleaned_path` 之后新增）：

```python
def filter_report(reason: str) -> ComputeReport:
    """滤镜清洗的算力回执：CPU 上的确定性操作，没有「试过 GPU 再落 CPU」可言。

    `fallback` 恒 False 是 `ComputeReport` 的不变量逼出来的写法——滤镜从没碰过 GPU，
    写 fallback 就成了假账；「为什么用滤镜」全部写在 `reason` 里。
    """
    return ComputeReport(
        component="tts.reference_clean.filter",
        requested="auto",
        resolved="cpu",
        actual="cpu",
        reason=reason,
    )
```

顶部补 `from dramaclip.infra.compute import ComputeReport`。

`auto_voice.py`：删掉 `device` 形参（`extract_auto_voice`、`_extract_locked` 各一处），分离调用不再传设备，滤镜分支补回执：

```python
    models_dir = data_dir / "models"
    # 分离设备恒 auto：tts.device 只承诺 torch 那条栈（规格 §3.5）。worker 的 auto
    # 路径自带「CUDA 试跑失败→整段 CPU 重跑并写明原因」，所以降级链是
    # CUDA 分离 → CPU 分离 → 滤镜，滤镜只留给 CPU 分离也失败的情况。
    # 写成显式 device="auto" 而不是省略参数：调用点把承诺说出来，测试才抓得住
    # （`**kwargs` 收不到被调方的默认值，省略参数的那条断言永远红），且被调方
    # 哪天改默认也不会悄悄换路。
    compute: ComputeReport | None = None
    clean_reason = ""
    try:
        separated = vocal_separation.clean_reference(models_dir, raw_path, device="auto")
        final, compute, cleaned_with = separated.path, separated.compute, "separation"
    except Exception as exc:  # noqa: BLE001 - CPU 分离也失败才落到滤镜
        final = reference_clean.clean_reference(raw_path)
        cleaned_with = "filter"
        clean_reason = f"{type(exc).__name__}: {exc}"
        compute = reference_clean.filter_report(
            f"人声分离不可用（{clean_reason}），已用 ffmpeg 滤镜链清洗"
        )
```

`from dramaclip.infra.compute import ComputeReport` 补进 imports；返回 dict 的 `"compute": compute.to_dict() if compute is not None else None` 保持原形状。

- [ ] **Step 4: `JobStore.set_ref_id`**

在 `set_compute` 之后追加（创建时还不知道关联对象的异步任务补写用）：

```python
    def set_ref_id(self, job_id: str, ref_id: str) -> None:
        """补写 ref_id：产物路径要到洗完才知道（自动提取的音色文件名带时间戳）。"""
        self._conn.execute(
            "UPDATE jobs SET ref_id = ?, updated_at = ? WHERE id = ?",
            (ref_id, _now_ms(), job_id),
        )
        self._conn.commit()
```

`service/tests/infra/test_jobs.py` 追加：

```python
def test_set_ref_id_points_row_at_the_artifact(conn: sqlite3.Connection) -> None:
    store = jobs.JobStore(conn)
    job_id = store.create("voice_clean")
    store.set_ref_id(job_id, "C:/data/voices/auto-ref-1020.wav")
    assert store.get(job_id)["ref_id"] == "C:/data/voices/auto-ref-1020.wav"
```

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_jobs.py tests/engines/tts/test_auto_voice_clean.py -q`
Expected: PASS。

- [ ] **Step 5: 改 `api/tts.py` 两个入口（清洗留痕）**

`clean_reference`：模式校验提前到建行之**前**（参数错误不该留一条失败任务行），分离不再取 `tts.device`，fast 档也带回执，成功/失败都落账。

```python
def clean_reference(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """参考音频清洗：mode=separate（MDX-Net 人声分离，默认）| fast（ffmpeg 滤镜链）。

    清洗是「改善参考」不是门禁：产物落 <stem>.cleaned.wav 与源同目录，返回产物
    质检报告由前端展示——用不用清洗产物仍由用户决定（B6 同款：报告不拦路）。
    本次用了哪种方法、跑在哪块算力上写进 `jobs.compute`（规格 §3.5：账在库，
    通知流不作真相源），任务行 `ref_id` 指向产物。
    """
    raw = str(params.get("path") or "").strip()
    if raw == "":
        raise RpcDomainError(_ERR_TTS_PARAM, "缺少参考音频路径（path）")
    src = Path(raw)
    if not src.is_file():
        raise RpcDomainError(_ERR_TTS_PARAM, f"参考音频不存在：{raw}")
    mode = str(params.get("mode") or "separate").strip()
    if mode not in {"fast", "separate"}:
        raise RpcDomainError(_ERR_TTS_PARAM, f"未知清洗模式「{mode}」（separate | fast）")
    job_id = context.job_store.create("voice_clean", str(reference_clean.cleaned_path(src)))
    context.job_store.mark_running(job_id)
    try:
        if mode == "fast":
            out = reference_clean.clean_reference(src)
            report = reference_clean.filter_report("用户选择快速滤镜清洗")
        else:
            # 显式 device="auto"：tts.device 只承诺 torch 那条栈，分离自己按 auto 解析
            separated = vocal_separation.clean_reference(
                context.data_dir / "models", src, device="auto"
            )
            out, report = separated.path, separated.compute
    except Exception as exc:  # noqa: BLE001 - 失败原因必须原样带出，不静默换档
        message = f"清洗失败：{type(exc).__name__}: {exc}"
        context.job_store.mark_failed(job_id, message)
        raise RpcDomainError(_ERR_TTS_CLEAN, message) from exc
    context.job_store.set_compute(job_id, [report.to_dict()])
    context.job_store.mark_completed(job_id)
    quality = reference_qc.inspect_reference(out)
    return {
        "job_id": job_id,
        "path": str(out),
        "compute": report.to_dict(),
        "quality": {
            "grade": quality.grade,
            "metrics": quality.metrics,
            "reasons": list(quality.reasons),
            "suggestions": list(quality.suggestions),
        },
    }
```

> 原来那个 `except RpcDomainError: raise` 单独分支被合进统一 `except`：失败任务行必须
> 带上原因，所以两类异常都要先写账再上抛，只是上抛时不再包一层 `RpcDomainError`。

`auto_voice`：删掉 `device=` 传参，建行→补 ref_id→落账同一套姿势。

```python
    job_id = context.job_store.create("voice_clean")
    context.job_store.mark_running(job_id)
    try:
        picked = auto_voice_mod.extract_auto_voice(context.conn, context.data_dir, episode_rows)
    except Exception as exc:  # noqa: BLE001 - 失败原因进任务行，界面才有的可看
        context.job_store.mark_failed(job_id, f"自动提取参考音色失败：{type(exc).__name__}: {exc}")
        raise
    context.job_store.set_ref_id(job_id, str(picked["path"]))
    compute = picked.get("compute")
    if compute is not None:
        context.job_store.set_compute(job_id, [compute])
    context.job_store.mark_completed(job_id)
```

返回值增加 `"job_id": job_id`，其余键原样。`ValueError`（剧集里没有可用段）按失败任务行落账后原样上抛——调用方仍会看到原因，不静默。

- [ ] **Step 6: 改 `api/export.py`（预检报告并入导出的账）**

`ExportRun` 加一个字段（`from dataclasses import dataclass, field`）：

```python
@dataclass(frozen=True)
class ExportRun:
    """一次导出渲染的不变输入（export_id 之外全部只读，渲染期间不会改写）。
    """

    export_id: str
    project_id: str
    plan_row: dict[str, Any]
    plan_data: PlanData
    cancel_event: threading.Event
    #: 渲染前阶段（自动音色提取/清洗）的算力回执：与 `video.encode` 并入同一条
    #: `export_jobs.compute` 数组，不另建任务行（规格 §3.5）。
    voice_reports: list[dict[str, Any]] = field(default_factory=list)
```

`_run_export`（`:862-871`）先建列表、传进去、再随 `ExportRun` 交给渲染：

```python
        tts_needed = _needs_voice(run.plan_data)
        voice_reports: list[dict[str, Any]] = []
        voiced = ExportRun(
            export_id=run.export_id,
            project_id=run.project_id,
            plan_row=run.plan_row,
            plan_data=_ensure_voiced(
                context, run.plan_row, run.plan_data,
                report=report if tts_needed else None,
                voice_reports=voice_reports,
            ),
            cancel_event=run.cancel_event,
            voice_reports=voice_reports,
        )
```

`_ensure_voiced` 增加 `voice_reports: list[dict[str, Any]] | None = None` 形参并透传给 `_ensure_clone_voice(context, plan_row, project_id, episodes_repo, settings, voice_reports)`；`_ensure_clone_voice` 在提取成功后收回执：

```python
        result = auto_voice.extract_auto_voice(
            context.conn, context.data_dir, [{"id": row["id"], "source_path": row["source_path"]}]
        )
        if voice_reports is not None and result.get("compute") is not None:
            voice_reports.append(dict(result["compute"]))
```

`render_export` 的 receipt 组装（`:689-692`）——清洗在前、编码在后，读账的人按时间顺序看：

```python
    receipt = [*run.voice_reports, *(item.to_dict() for item in reports)]
    exports_repo.set_compute(context.conn, export_id, receipt)
```

> `set_compute` 的覆盖语义不变（一次导出只写一次账）；合并发生在内存里，不新增仓储方法、
> 不加迁移。`jobs.compute` 与 `export_jobs.compute` 继续同写同一份数组。

- [ ] **Step 7: 替换三处旧断言**

`service/tests/api/test_tts_clean_reference.py`：

- `test_separate_mode_honors_explicit_device_setting`（`:123-143`）替换为 `test_separate_mode_ignores_tts_device_setting`——把 `context.settings = {"tts.device": "cuda"}`，断言 `seen["device"] == "auto"` 且返回的 `compute` 是 worker 原报（`tts.separation`）。**方向翻转的断言**：旧用例证明设置能传下去，新用例证明传不下去。
- `test_fast_mode_does_not_report_compute`（`:145-158`）替换为 `test_fast_mode_reports_filter_compute`——`assert result["compute"]["component"] == "tts.reference_clean.filter"`、`actual == "cpu"`、`reason == "用户选择快速滤镜清洗"`。
- 两个用例都补断言：`context.job_store` 里那条 `voice_clean` 行终态与 `compute` 非空（用 `_context()` 里已有的 fake job store 记录调用；若 `_context` 还没有 job_store 替身，补一个记录 `create/mark_running/set_compute/mark_completed/mark_failed` 的 `SimpleNamespace` 假件）。
- 失败路径新增 `test_failed_clean_keeps_a_failed_row`：让 `vocal_separation.clean_reference` 抛 `RuntimeError("模型下载失败")`，断言返回错误码 `_ERR_TTS_CLEAN` 且任务行 `mark_failed` 的原因含「模型下载失败」。

`service/tests/api/test_export_voice_preflight.py`：

- 两个 `fake_extract` 桩的签名已是 `**_kwargs`，删掉 `device=` 传参后仍兼容；**不改那两个既有桩**（它们各自断言复用与引擎 key，硬塞 `compute` 是噪音）——新增 `_stub_extract` 替身记录收到的 kwargs，返回体带 `compute`，供下面两条用例用。
- 新增 `test_clone_voice_receipt_lands_in_export_ledger`：`_ensure_clone_voice(..., voice_reports=[])` 调用后，列表里就是那条 `tts.separation` 回执。
- 断言 `_ensure_clone_voice` 不再把 `tts.device` 传给提取：`settings` 含 `"tts.device": "cuda"` 时 `fake_extract` 收到的 kwargs 里没有 `device`（`test_clone_voice_preflight_does_not_inherit_tts_device`）。
- 新增 `test_preflight_report_lands_in_export_compute`（实落名 `test_render_export_ledgers_the_voice_receipt_before_the_encode_one`，写在 `service/tests/api/test_export_compute_persist.py`）：**没有按原计划 monkeypatch `exports_repo.set_compute`**——那个文件已有把 `encoder.export_plan` 换成假件、走 `memory_db` 真写表的现成夹具，直接 `ExportRun(voice_reports=[...])` 然后读 `exports_repo.get(...)["compute"]`，断言数组就是 `["tts.separation", "video.encode"]`。断言落在库里的行上，比断言桩被调用更硬。

- [ ] **Step 8: 运行确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/tts tests/api/test_tts_clean_reference.py tests/api/test_export_voice_preflight.py tests/infra/test_jobs.py tests/api/test_tts_preview.py tests/api/test_export_compute_persist.py -q`
Expected: PASS（实落 151 passed / 0 skipped，EXIT=0）。

Run: `cd service && ../.venv/Scripts/python -m pytest tests -q`
Expected: 无失败。**「skipped 仍为 1」作废**（Task 4 Step 9 已订正：本树两条条件跳过都不触发，基线 1778 passed / 0 skipped）。

> 执行时发现（不在本任务范围，未动）：`api/tts.py` 的手动提取入口 `auto_voice` 把音色**硬写进 `tts.voice.indextts2`**
> （`:64`、`:84`，契约 summary 同口径），而本任务的导出预检 `_ensure_clone_voice` 已按 `tts.voice.<engine>` 分键。
> 后果：引擎设为 cosyvoice 时点「自动提取」，音色落在 indextts2 的 key 上，cosyvoice 仍无参考、导出预检会再提取一次。
> 这是 §3.5 之外的第二处「引擎各自的 key」漏项，需业主裁定是否单开一笔修。

- [ ] **Step 9: 协议两处跟上新增的 `job_id`**

`核对` 阶段确认的漏项：`tts.clean_reference` / `tts.auto_voice` 的返回体在**两处**有声明（`protocol/ts/index.ts` 与 `protocol/schemas/tts.json`），本步给它们各加一个键。契约测试（`service/tests/transport/test_contract_sync.py`、`desktop/src/__tests__/contract.test.ts`）只比对方法名集合，字段级不红——所以必须手工同步，不能指望测试兜住。

`protocol/ts/index.ts`（`:706` 与 `:728` 两个 interface 各加首行字段）：

```ts
export interface TtsAutoVoiceResult {
  /** 本次提取的 voice_clean 任务行 id：回执在库里，不在 toast 里。 */
  readonly job_id: string;
  readonly path: string;
```

```ts
export interface TtsCleanReferenceResult {
  /** 本次清洗的 voice_clean 任务行 id（jobs.compute 落的这条）。 */
  readonly job_id: string;
  readonly path: string;
```

`protocol/schemas/tts.json`：`tts.clean_reference` 的 `result` 与 `tts.auto_voice` 的 `result`，各自把 `"job_id"` 加进 `required` 数组首位，并在 `properties` 里加：

```json
"job_id": {"type": "string", "description": "voice_clean 任务行 id；本次清洗/提取的算力回执落在这条 jobs 行"}
```

渲染层调用方（`desktop/src/services/client.ts:305-308`）与 `TtsTab.tsx` 仍只读 `path`/`quality`，返回体是**加键不是换形状**，不需要同步改 UI；typecheck 会证明这一点。

- [ ] **Step 10: 提交**

```bash
git add service/dramaclip/engines/tts/reference_clean.py service/dramaclip/engines/tts/auto_voice.py service/dramaclip/infra/jobs.py service/dramaclip/api/tts.py service/dramaclip/api/export.py protocol/ts/index.ts protocol/schemas/tts.json service/tests/engines/tts/test_auto_voice_clean.py service/tests/api/test_tts_clean_reference.py service/tests/api/test_export_voice_preflight.py service/tests/infra/test_jobs.py
git commit -m "feat: 人声分离恒 auto 并把清洗回执落进算力账本（CUDA→CPU→滤镜 三档降级链）"
```

---

## Task 8: 协议与设备选项（`protocol/ts/index.ts` + `machineFit.ts` + 新增 `deviceOptions.ts`）

**Files:**
- Modify: `protocol/ts/index.ts:47-87`（`GpuVendor` / `GpuAdapter` / `GpuInfo.adapters` / `DeviceCap.reason` / `DeviceCaps`）
- Modify: `desktop/src/features/engines/machineFit.ts:11-16`（`MachineSpecs`）、`:92-99`（`specsFromHealth`）
- Create: `desktop/src/features/engines/deviceOptions.ts`
- Modify: `desktop/src/features/engines/AsrTab.tsx:39-47`（`PARAMS` 的设备项）、`:176-243`（`ActiveCard`）、`:244-259`（`paramProps`）
- Modify: `desktop/src/features/engines/TtsTab.tsx:59-67`（`TTS_PARAMS`）、`:318-336`（设备行渲染）
- Test: `desktop/src/features/engines/__tests__/deviceOptions.test.ts`（新增）

**Interfaces:**
- Consumes: Task 2 后端 `profile()` 产出的 `caps[*].reason`；Task 1 的 `gpu_info.adapters`。
- Produces:
  - `type GpuVendor = 'nvidia' | 'amd' | 'intel' | 'other' | 'none' | 'unknown'`
  - `interface GpuAdapter { name; vendor: GpuVendor; driver_version }`
  - `interface DeviceCap { ok; ready; hint; reason }`、`type DeviceCaps = Record<string, DeviceCap>`
  - `MachineSpecs.gpu?: GpuInfo` / `.caps?: DeviceCaps`（`specsFromHealth` 原样带下）
  - `deviceOptions(args: { engine; saved; gpu?; caps? }): readonly DeviceOption[]`
  - Task 9 的文案分支消费同一套类型，不再自己声明字面量联合。

**判据口径（规格 §6.2）**：选项可用性读 `cap.ready`，**不读 vendor**——N 卡也可能不满足某条栈的下限（GTX 10 的 torch 栈），而 AMD/Intel 主机的 NVIDIA cap 早已是 false。前端不解析 `hint`/`reason` 文案做控制流，只把 `reason` 当标签文字展示。

- [ ] **Step 1: 写失败测试**

创建 `desktop/src/features/engines/__tests__/deviceOptions.test.ts`：

```ts
/** 设备选项：CUDA 是承诺，界面只给会被后端 resolve 接受的值。 */
import { describe, expect, it } from 'vitest';
import type { DeviceCaps, GpuInfo } from '@dramaclip/protocol';
import { deviceOptions } from '../deviceOptions';

const NVIDIA_READY: GpuInfo = {
  ready: true, vendor: 'nvidia', name: 'RTX 4060', driver_version: '572.10',
  max_cuda_version: '12.8', memory_total_mb: 8188, compute_cap: '8.9',
};
const AMD_READY: GpuInfo = {
  ready: true, vendor: 'amd', name: 'Radeon RX 6600', driver_version: '31.0.21006.1',
  max_cuda_version: '', memory_total_mb: 8188, compute_cap: '',
};

function capsOf(entry: Partial<DeviceCap_>): DeviceCaps {
  return { indextts2_gpu: { ok: true, ready: false, hint: '', reason: '', ...entry } };
}

type DeviceCap_ = DeviceCaps[string];

describe('deviceOptions', () => {
  it('cap ready → 给可用的 CUDA', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY,
      caps: capsOf({ ready: true }),
    });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'cuda']);
    expect(options.find((o) => o.value === 'cuda')?.disabled).toBeFalsy();
  });

  it('cap 不 ready → 不给 CUDA（读 cap 不读厂商：AMD 与老 N 卡同走这支）', () => {
    for (const gpu of [AMD_READY, NVIDIA_READY]) {
      const options = deviceOptions({ engine: 'indextts2', saved: 'auto', gpu, caps: capsOf({ ready: false, ok: false }) });
      expect(options.map((o) => o.value)).toEqual(['auto', 'cpu']);
    }
  });

  it('已保存 cuda 但本机不 ready → 该项仍在，disabled 且带原因', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'cuda', gpu: AMD_READY,
      caps: capsOf({ ready: false, ok: false, reason: '转写加速仅支持 NVIDIA CUDA' }),
    });
    const cuda = options.find((o) => o.value === 'cuda');
    expect(cuda?.disabled).toBe(true);
    expect(cuda?.label).toBe('CUDA（转写加速仅支持 NVIDIA CUDA）');
  });

  it('原因缺失时不渲染空括号', () => {
    const options = deviceOptions({ engine: 'indextts2', saved: 'cuda', gpu: AMD_READY, caps: capsOf({ ready: false }) });
    expect(options.find((o) => o.value === 'cuda')?.label).toBe('CUDA（本机不可用）');
  });

  it('显卡待探测 → 保留 CUDA：探测中不等于不可用', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: { ...NVIDIA_READY, ready: false },
      caps: capsOf({ ready: false }),
    });
    expect(options.some((o) => o.value === 'cuda')).toBe(true);
  });

  it('caps 缺失（旧服务）→ 保留 CUDA，不做假阴性', () => {
    const options = deviceOptions({ engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY });
    expect(options.some((o) => o.value === 'cuda')).toBe(true);
  });

  it('引擎没有 cap（kokoro / edge）→ 不替它宣布可用性，原样给三档', () => {
    const options = deviceOptions({ engine: 'kokoro', saved: 'auto', gpu: AMD_READY, caps: capsOf({ ready: false }) });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'cuda']);
  });

  it('ASR 两个引擎读各自的 cap：funasr 与 whisper 下限不同', () => {
    const caps: DeviceCaps = {
      faster_whisper_gpu: { ok: false, ready: false, hint: '', reason: '算力低于 ctranslate2 下限' },
      indextts2_gpu: { ok: true, ready: true, hint: '', reason: '' },
    };
    expect(deviceOptions({ engine: 'faster_whisper', saved: 'auto', gpu: NVIDIA_READY, caps }).map((o) => o.value)).toEqual(['auto', 'cpu']);
    expect(deviceOptions({ engine: 'sensevoice', saved: 'auto', gpu: NVIDIA_READY, caps }).some((o) => o.value === 'cuda')).toBe(true);
  });
});
```

> `sensevoice` 在 `caps` 里没有 `funasr_gpu` 那一项 → 走「没有判据」分支，仍给 CUDA。
> 这正是最后一要验的：**缺席 ≠ 不可用**（`unknown ≠ ok` 的界面侧同条纪律）。

Run: `cd desktop && npm test -- deviceOptions`
Expected: FAIL（模块不存在）。

- [ ] **Step 2: 改协议类型**

`protocol/ts/index.ts`：

```ts
/** 宿主显卡厂商类别（`infra/gpu.py` classify_vendor 的取值集合）。 */
export type GpuVendor = 'nvidia' | 'amd' | 'intel' | 'other' | 'none' | 'unknown';

/** 单张物理显卡（虚拟显示适配器已在后端剔除）。 */
export interface GpuAdapter {
  readonly name: string;
  readonly vendor: GpuVendor;
  readonly driver_version: string;
}

/** 健康检查扩展：GPU 探测结果（未就绪时 ready=false，服务端后台补测）。 */
export interface GpuInfo {
  readonly ready: boolean;
  readonly vendor: GpuVendor;
  readonly name: string;
  readonly driver_version: string;
  readonly max_cuda_version: string;
  /** 总显存 MiB（未检出为 0）。 */
  readonly memory_total_mb: number;
  /** 算力档 compute capability（如 "5.2"；老驱动查不到为空串）。 */
  readonly compute_cap: string;
  /** 本机全部物理显卡（旧服务不带此项）。 */
  readonly adapters?: readonly GpuAdapter[];
}

/** 单项 GPU 能力结论：ok=硬件够；ready=连运行时也装好即开即用。 */
export interface DeviceCap {
  readonly ok: boolean;
  readonly ready: boolean;
  readonly hint: string;
  /** 机器可读的不可用原因（界面只展示，不解析做控制流）。 */
  readonly reason: string;
}

export type DeviceCaps = Record<string, DeviceCap>;
```

`DeviceProfile.vendor: string` → `GpuVendor`，`caps: Record<string, DeviceCap>` → `DeviceCaps`。

> `GpuInfo.vendor` 从 `string` 收紧成联合：后端 Task 1 起只会吐这六个值，收紧后
> Task 9 的 switch 漏分支会在 `npm run typecheck` 就红，而不是留到运行时静默走 else。

- [ ] **Step 3: `machineFit.ts` 带下宿主事实**

```ts
export interface MachineSpecs {
  readonly ramTotalGb?: number;
  readonly ramFreeGb?: number;
  readonly diskFreeGb?: number;
  /** 宿主显卡事实：设备选项与人声分离提示读它，不读后端文案。 */
  readonly gpu?: GpuInfo;
  /** `health.device_profile.caps` 原样带下：选项可用性只读 ready。 */
  readonly caps?: DeviceCaps;
}
```

```ts
export function specsFromHealth(health: HealthResult | null | undefined): MachineSpecs {
  if (!health) return {};
  return {
    ramTotalGb: health.ram_total_gb,
    ramFreeGb: health.ram_free_gb,
    diskFreeGb: health.disk_free_gb,
    gpu: health.gpu_info,
    caps: health.device_profile?.caps,
  };
}
```

顶部 import 改 `import type { DeviceCaps, GpuInfo, HealthResult } from '@dramaclip/protocol';`。

- [ ] **Step 4: 新增 `deviceOptions.ts`**

```ts
/** ASR / TTS 的「运行设备」选项：可用性读后端算好的 cap，不读厂商、不解析文案。
 *
 * CUDA 是承诺（`device_resolve` 会拒绝不 ready 的 cuda），所以界面只提供会被接受的
 * 值。两类缺席必须保留 CUDA 而不是藏掉：显卡还在探测中、该引擎没有能力判据
 * （kokoro 一类）——「不知道」渲染成「不可用」就是假阴性（`unknown ≠ ok`）。
 */
import type { DeviceCaps, GpuInfo } from '@dramaclip/protocol';

export interface DeviceOption {
  readonly label: string;
  readonly value: string;
  readonly disabled?: boolean;
}

/** 引擎 → cap 名：与后端 `device_resolve._COMPONENT_CAPS` 同一批键。
 * cosyvoice 系与 indextts2 共用 `indextts2_gpu`——那个键实质是「torch cu128 栈」。 */
const ENGINE_CAP: Readonly<Record<string, string>> = {
  faster_whisper: 'faster_whisper_gpu',
  sensevoice: 'funasr_gpu',
  paraformer: 'funasr_gpu',
  indextts2: 'indextts2_gpu',
  cosyvoice: 'indextts2_gpu',
  cosyvoice3: 'indextts2_gpu',
};

const CUDA_LABEL = 'CUDA（NVIDIA）';

export function deviceOptions(args: {
  readonly engine: string;
  readonly saved: string;
  readonly gpu?: GpuInfo;
  readonly caps?: DeviceCaps;
}): readonly DeviceOption[] {
  const base: readonly DeviceOption[] = [
    { label: '自动（检测 GPU）', value: 'auto' },
    { label: 'CPU', value: 'cpu' },
  ];
  if (args.gpu === undefined || !args.gpu.ready) {
    return [...base, { label: CUDA_LABEL, value: 'cuda' }];
  }
  const cap = args.caps?.[ENGINE_CAP[args.engine] ?? ''];
  if (cap === undefined || cap.ready) {
    return [...base, { label: CUDA_LABEL, value: 'cuda' }];
  }
  if (args.saved !== 'cuda') return base;
  // 陈旧设置可见、可改走，而不是静默吞掉或渲染成空白
  return [...base, { label: `CUDA（${cap.reason !== '' ? cap.reason : '本机不可用'}）`, value: 'cuda', disabled: true }];
}
```

- [ ] **Step 5: 两个 tab 按 machine + 引擎生成设备选项**

`AsrTab.tsx`：`PARAMS` 里删掉 `asr.device` 那一项（`label`/`options` 移到组件内），`paramProps` 改为收设备选项：

```ts
function paramProps(
  settings: DomainTabProps['settings'],
  onSave: DomainTabProps['onSave'],
  keys: readonly string[],
  device: { label: string; options: DefaultOptionType[] } | null,
): ActiveCardProps['props'] {
  const rows = PARAMS.filter((param) => keys.includes(param.key)).map((param) => ({
    label: param.label,
    value: (
      <SettingSelect
        value={settings[param.key] ?? ''}
        options={param.options}
        onChange={(value: string) => {
          onSave({ [param.key]: value });
        }}
      />
    ),
  }));
  if (device === null || !keys.includes('asr.device')) return rows;
  return [
    {
      label: '运行设备',
      value: (
        <SettingSelect
          value={settings['asr.device'] ?? ''}
          options={device.options}
          onChange={(value: string) => {
            onSave({ 'asr.device': value });
          }}
        />
      ),
    },
    ...rows,
  ];
}
```

`ActiveCard` 增加 `machine: MachineSpecs` 与 `engine: string` 两个 prop（AsrTab 的调用处把 `machine` 与当前引擎名传进来），在 `card.props` 组装处：

```ts
      ...paramProps(
        settings,
        onSave,
        ['asr.device', 'asr.language', 'asr.diarization'],
        deviceSelectProps({ engine, saved: settings['asr.device'] ?? 'auto', machine }),
      ),
```

`TtsTab.tsx`：删掉 `TTS_PARAMS` 里 `tts.device` 的 `options` 常量（保留 `TTS_PARAMS` 若无其它项则整表退役，改由 `deviceSelectProps` 直接产出那一行），并把渲染分支换成同一函数：

```ts
      ...(engine === 'edge' || engine === 'cosyvoice_cloud'
        ? []
        : [{
            label: '运行设备',
            value: (
              <SettingSelect
                value={settings['tts.device'] ?? ''}
                options={deviceSelectProps({ engine, saved: settings['tts.device'] ?? 'auto', machine }).options}
                onChange={(value: string) => {
                  onSave({ 'tts.device': value });
                }}
              />
            ),
          }]),
```

`deviceOptions.ts` 末尾补一个把结果摊平成 antd 选项的出口，两 tab 共用（避免第二处映射写法）：

```ts
/** antd 形状：两个 tab 共用，选项生成只住在 `deviceOptions` 这一处。 */
export function deviceSelectProps(args: {
  readonly engine: string;
  readonly saved: string;
  readonly machine: MachineSpecs;
}): { readonly options: readonly DeviceOption[] } {
  return {
    options: deviceOptions({
      engine: args.engine,
      saved: args.saved,
      gpu: args.machine.gpu,
      caps: args.machine.caps,
    }),
  };
}
```

Run: `cd desktop && npm test -- deviceOptions && npm run typecheck`
Expected: 测试 PASS；`npm run typecheck` 会指出 Task 9 才修的文案分支与 fixture 类型缺口——本任务内只要求 `deviceOptions.test.ts` 绿，其余红在 Step 6 一并收。

- [ ] **Step 6: 补既有 fixture 的新必填字段**

`desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx` 的 `NVIDIA_PROFILE.caps` 两项各补 `reason: ''`（`DeviceCap` 新增必填）。全仓 grep `faster_whisper_gpu:` 找出其余 fixture 一并补，别漏。

- [ ] **Step 7: 提交**

```bash
git add protocol/ts/index.ts desktop/src/features/engines/machineFit.ts desktop/src/features/engines/deviceOptions.ts desktop/src/features/engines/AsrTab.tsx desktop/src/features/engines/TtsTab.tsx desktop/src/features/engines/__tests__/deviceOptions.test.ts desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx
git commit -m "feat: 设备选项按后端 cap.ready 生成（CUDA 是承诺，探测中与无判据不做假阴性）"
```

---

## Task 9: 界面文案按宿主厂商说话（`GpuCard` / `StatusBar` / `MachinePanel` / `SeparationBackendNote`，删 `gpuSummary`）

**Files:**
- Modify: `desktop/src/features/engines/GpuCard.tsx:11-38`
- Modify: `desktop/src/components/layout/StatusBar.tsx:17-22`
- Modify: `desktop/src/features/engines/MachinePanel.tsx:58`、`:103-155`、`:194-215`、`:245-248`
- Modify: `desktop/src/features/engines/TtsTab.tsx:320`、`:347-387`
- Modify: `desktop/src/features/engines/useGpuInfo.ts:49-61`（删 `gpuSummary`）
- Test: `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx`、新增 `GpuCard.test.tsx`、
  新增 `desktop/src/components/layout/__tests__/StatusBar.test.tsx`、
  新增 `desktop/src/features/engines/__tests__/SeparationBackendNote.test.tsx`（实落补的两件，见 Step 2 订正）

**Interfaces:**
- Consumes: Task 8 的 `GpuVendor`、`MachineSpecs.gpu`。
- Produces: 无新导出（纯文案分支）。`useGpuInfo` 只剩 `{ info, refresh }`。

**纪律**：分支只读 `gpu.vendor` / `gpu.ready` / `gpu.name` / `gpu.driver_version` 这些**宿主事实**；`ortGpu.reason` 只展示、不再当控制流（§1 根因 4 的教训——按文案字符串分支，后端改一个字界面就悄悄换路）。

- [ ] **Step 1: 写失败测试**

新增 `desktop/src/features/engines/__tests__/GpuCard.test.tsx`（沿用 `MachinePanelEnv.test.tsx` 的 `systemApi.health` mock 姿势，`runtimeApi.status` mock 成 `{ cublas: false, cudnn: false, installed: true }` 以免混入下载行）：

```tsx
/** GPU 卡文案按宿主厂商分支：AMD/Intel 主机不该再被告知「未检测到 NVIDIA 显卡」。 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import { GpuCard } from '../GpuCard';

function card(vendor: GpuInfo['vendor'], name: string, device = 'auto'): void {
  render(
    <GpuCard
      info={{
        ready: true, vendor, name, driver_version: '31.0.1',
        max_cuda_version: '', memory_total_mb: 8192, compute_cap: '',
      }}
      device={device}
      onRefresh={() => undefined}
    />,
  );
}

describe('GpuCard 厂商分支', () => {
  afterEach(cleanup);

  it('amd → 说清转写走 CPU，但 AMF 硬件编码可用', async () => {
    card('amd', 'Radeon RX 6600');
    expect(await screen.findByText(/未检测到 NVIDIA 显卡 · 转写将以 CPU 运行/)).toBeTruthy();
    expect(screen.getByText(/Radeon RX 6600 · 驱动 31.0.1 · 视频导出可用 AMD 硬件编码（AMF，导出时真试编）/)).toBeTruthy();
  });

  it('intel → 文案给 QSV', async () => {
    card('intel', 'UHD Graphics 630');
    expect(screen.getByText(/视频导出可用 Intel 硬件编码（QSV，导出时真试编）/)).toBeTruthy();
  });

  it('other → 不点名厂商，只说真试编', async () => {
    card('other', 'Microsoft Basic Display Adapter');
    expect(screen.getByText(/视频导出将真试编可用的硬件编码器/)).toBeTruthy();
  });

  it('none → 没有卡：型号行不编造名字', async () => {
    card('none', '');
    expect(await screen.findByText(/未检测到独立显卡 · 转写将以 CPU 运行/)).toBeTruthy();
    expect(screen.getByText(/ASR\/TTS 加速需要 NVIDIA CUDA；视频导出将真试编，全不可用回退 libx264/)).toBeTruthy();
  });
});
```

> `GpuCard` 的实际 props 以文件现状为准（`info` + `device` + 刷新回调）；若签名不同，按
> 现状对齐再写测试——**不许为了测试改组件的对外面**。

`MachinePanelEnv.test.tsx` 的两处按新矩阵改写（替换不是放宽：从「gpu_info 缺席」变成「显式给一张 AMD 卡 / 显式给 none」，覆盖更严）：

```tsx
const AMD_HEALTH: HealthResult = {
  ...NVIDIA_HEALTH,
  gpu_info: {
    ready: true, vendor: 'amd', name: 'Radeon RX 6600', driver_version: '31.0.21006.1',
    max_cuda_version: '', memory_total_mb: 8188, compute_cap: '',
  },
};

it('AMD 主机 + 缺 CUDA 运行库 → 说清加速需要 N 卡，当前走 CPU', async () => {
  vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
  renderPanel(AMD_HEALTH);
  expect(await screen.findByText(/CUDA 运行库：未安装 · 转写加速需要 NVIDIA CUDA，无需安装，当前走 CPU/)).toBeTruthy();
});

it('显卡探测中（gpu_info 缺席）→ 不冒充「未检测到独立显卡」', async () => {
  vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
  renderPanel(NO_GPU_HEALTH);
  expect(await screen.findByText(/CUDA 运行库：未安装 · 显卡状态探测中，暂按 CPU 运行/)).toBeTruthy();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd desktop && npx vitest run src/features/engines/__tests__/GpuCard.test.tsx src/features/engines/__tests__/MachinePanelEnv.test.tsx`
Expected: FAIL——非 nvidia 主机仍显示「未检测到 NVIDIA 显卡」，AMD/Intel 的编码行缺失。

> 实落订正：
> 1. **`--reporter=basic` 在本仓 vitest 版本不可用**（直接报 `ESM syntax in a file loaded as CommonJS`），
>    跑默认 reporter 再 `grep '×'` 取用例名；`npm test -- <名称>` 的过滤姿势同理不成立，用文件路径。
> 2. 上面这条命令的期望实落 **13 红**（GpuCard 4 + MachinePanelEnv 9），红的全是新用例，既有 6 条不连坐。
> 3. 计划只点两个测试文件，**实际补到四个**：`StatusBar.tsx` 的 `gpuLabel` 是纯函数但不是纯文案——
>    「无独立显卡」那句在状态栏常驻，AMD 主机天天看得到，不测等于改了一半。
>    `SeparationBackendNote` 同因（Step 6 换的是控制流），故新增
>    `desktop/src/components/layout/__tests__/StatusBar.test.tsx`（4 条）与
>    `desktop/src/features/engines/__tests__/SeparationBackendNote.test.tsx`（5 条），
>    后者需要把组件从 `TtsTab.tsx` 导出（只加 `export`，对外面零改动）。

- [ ] **Step 3: `GpuCard.tsx`**

```ts
function statusOf(info: GpuInfo | null, device: string): { text: string; color: string } {
  if (!info?.ready) {
    return { text: '检测中…', color: tokens.textTertiary };
  }
  if (info.vendor !== 'nvidia') {
    // none 才是「没有独立显卡」；amd/intel/other 有卡，只是不满足 CUDA 这一条
    return info.vendor === 'none'
      ? { text: '未检测到独立显卡 · 转写将以 CPU 运行', color: tokens.textSecondary }
      : { text: '未检测到 NVIDIA 显卡 · 转写将以 CPU 运行', color: tokens.textSecondary };
  }
  ...  // 现有两句原样
}

function metaOf(info: GpuInfo | null): string {
  if (!info?.ready) return '';
  if (info.vendor !== 'nvidia') {
    if (info.vendor === 'none') {
      return 'ASR/TTS 加速需要 NVIDIA CUDA；视频导出将真试编，全不可用回退 libx264';
    }
    const parts = [info.name, info.driver_version !== '' ? `驱动 ${info.driver_version}` : ''];
    const encode =
      info.vendor === 'amd'
        ? '视频导出可用 AMD 硬件编码（AMF，导出时真试编）'
        : info.vendor === 'intel'
          ? '视频导出可用 Intel 硬件编码（QSV，导出时真试编）'
          : '视频导出将真试编可用的硬件编码器';
    return `${parts.filter((part) => part !== '').join(' · ')} · ${encode}`;
  }
  ...  // 现有 NVIDIA 分支原样
}
```

CUDA 运行库下载行的条件（`:87`）不变——仍只在 `vendor === 'nvidia'` 时出现。

- [ ] **Step 4: `StatusBar.tsx`**

```ts
function gpuLabel(info: GpuInfo | undefined): string {
  if (!info?.ready) return '待检测';
  if (info.vendor === 'none') return '未检测到独立显卡 · CPU 模式';
  if (info.vendor !== 'nvidia') {
    return `${info.name !== '' ? info.name : '独立显卡'} · 驱动 ${info.driver_version || '未知'}`;
  }
  const short = info.name.replace(/^NVIDIA\s+/i, '');
  return `${short !== '' ? short : 'NVIDIA'} · 驱动 ${info.driver_version || '未知'}`;
}
```

- [ ] **Step 5: `MachinePanel.tsx`**

`gpuIsNvidia: boolean` 换成厂商本身（一行四支的文案需要它，布尔会把 amd/none/探测中压成一个值）：

```tsx
        gpuVendor={gpu?.ready === true ? gpu.vendor : 'unknown'}
```

```ts
function cudaText(status: EnvStatus, vendor: GpuVendor): string {
  if (status === 'probing') return '状态未知 · 探测中';
  if (status === 'missing') return '未安装 · 本机没有该运行环境';
  if (status === 'installed') {
    if (vendor === 'nvidia') return '已安装 · 转写可走 GPU 加速';
    if (vendor === 'none') return '已安装 · 未检测到独立显卡，不会启用';
    if (vendor === 'unknown') return '已安装 · 显卡状态探测中';
    return '已安装 · 本机无 NVIDIA 显卡，不会启用';
  }
  if (vendor === 'nvidia') return '未安装 · 转写走 CPU，可在本页「转写加速（GPU）」卡下载';
  if (vendor === 'none') return '未安装 · 未检测到独立显卡，无需安装，转写走 CPU';
  if (vendor === 'unknown') return '未安装 · 显卡状态探测中，暂按 CPU 运行';
  return '未安装 · 转写加速需要 NVIDIA CUDA，无需安装，当前走 CPU';
}
```

> 前两个 `status` 分支（`probing` / `missing`）与现有实现同值，只是把 vendor 判读挪到
> 文案之后：**探测失败仍不许冒充「未安装」**（既有纪律，`EnvStatus` 三态不变）。
> `status` 的实际取值名以文件现状为准（`:148-155` 附近），按现状对齐分支、不新增状态。

> 实落订正：`EnvStatus` 的现状取值是 `loading | installed | missing | unknown`，
> 上面片段的 `probing` 这一支在本仓根本不存在——按现状对齐成
> `loading → '检测中…'`、`unknown → '状态未知 · 探测失败，稍后刷新页面重试'`（两句原样保留，
> 「探测失败不冒充未安装」的既有测试 `MachinePanelEnv.test.tsx:探测失败` 仍绿），
> `missing` 落到函数末尾的厂商四支。

显卡格与判定尾句：

```ts
    {
      label: '显卡',
      value: !gpu?.ready
        ? '显卡待检测…'
        : gpu.vendor === 'none'
          ? '未检测到独立显卡 · 走 CPU'
          : gpu.vendor === 'nvidia'
            ? `${gpu.name}${gpu.memory_total_mb > 0 ? ` · ${String(Math.round(gpu.memory_total_mb / 1024))}GB` : ''}${gpu.max_cuda_version !== '' ? ` · CUDA ${gpu.max_cuda_version}` : ''}`
            : gpu.name !== ''
              ? `${gpu.name} · 驱动 ${gpu.driver_version}`
              : '独立显卡 · 驱动未读到',
    },
```

```ts
  const tail =
    verdict.verdict === 'ok'
      ? '；本地引擎均为 CPU 可跑，视频导出会真试编选择硬件编码器（NVENC / AMF / QSV）'
      : `——${verdict.reason}`;
```

> 计划外同批（`MachinePanel.tsx:281-296` 的 `TierLine`，不在本 Task 声明的行范围内，但它与本 Task
> 同一个文件、同一个病）：`readyOf` 原本是 `key === 'indextts2_gpu' ? cap.ok && ttsReady : cap.ready`
> ——那句注释「后端探针只到安装态」已经过期，Task 2 之后后端 `indextts2_gpu.ready` 就是执行级实况
> （`indextts_ok and variant == 'cuda'`）。前端再拼一次 `localRuntimeApi.status().installed`
> 是第二真相源，而且拼的是**安装态**：tts-venv 装上了但 torch 是 CPU 轮时，后端说 `ready=false`、
> 前端仍点亮「GPU 加速已生效：音色克隆」——绿灯假账，比原来的灰灯误导更糟。
> 改成 `readyOf = (key) => caps[key]?.ready === true`，`ttsReady` prop 一并删（调用处少一个参数）。
> 两条用例钉住方向：装好 + `ready=false` → 只进「硬件满足但待运行时」；未装 + `ready=true` → 照后端亮灯。
>
> 同处另有一笔**未动、待裁定**：`TierLine` 的 `blocked`（「此卡不支持」那串）仍按
> `cap.hint === ''` 判有无原因，并硬排除 `indextts2_gpu` / `funasr_gpu`。Task 2 之后 `ok=false`
> 已经是纯硬件/算力下界结论（M4000 的 `indextts2_gpu` 就是 `ok=false` + sm_70 下界原因），
> 这两个排除项会把真不支持说成没支持——正是 `:303-305` 注释要防的那类误导，方向还反了。
> 改它要连 `hint`→`reason` 的取数一起换（`reason` 才是给程序读的那半句），不在本 Task 的文案面里。

- [ ] **Step 6: `SeparationBackendNote` 读宿主事实**

props 加 `machine: MachineSpecs`（渲染处 `:320` 传 `machine={machine}`），删掉文案解析那一行：

```ts
  // 宿主事实决定「重跑安装」有没有意义：非 NVIDIA 主机装了也不会启用 CUDA EP。
  const hostMayHaveCuda =
    machine.gpu === undefined || !machine.gpu.ready || machine.gpu.vendor === 'nvidia' || machine.gpu.vendor === 'unknown';
  const retry = ortGpu === null || (!ortGpu.gpu && hostMayHaveCuda);
```

其余分支与文案原样（`ortGpu.reason` 仍原样展示，只是不再进控制流）。本格与设备选项互不干涉：选项按 cap 隐藏 CUDA 时，分离仍按 `ort_state` 的实际后端走。

- [ ] **Step 7: 删 `gpuSummary`**

`useGpuInfo.ts:49-61` 整段删除（已确认无调用方）。留着的后果是第三份 GPU 文案真相源——将来改文案的人只改两处，第三处悄悄漂移。

- [ ] **Step 8: 运行确认通过**

Run: `cd desktop && npm test && npm run typecheck && npm run lint`
Expected: 全绿。`typecheck` 是 `GpuVendor` 收紧的受益处：任何漏了 `unknown` 分支的 switch 会在这里红。

> 实落：`npm test` **82 files / 655 tests 全绿**（Task 8 后基线 78/626，本 Task +4 文件 +29 用例），
> `npm run typecheck` EXIT=0，`npm run lint` 只剩 HEAD 既有的 2 错
> （`EnginesImport.test.tsx:32`、`enginesDeepLink.test.tsx:22` 两条空箭头函数，两文件与本批无关、
> 未改动）与 7 条既有 `react-refresh` warning。
> 顺手修掉 Task 8 遗留的一条：`deviceOptions.ts:39` 的 `args.gpu === undefined || !args.gpu.ready`
> 被 `prefer-optional-chain` 判冗余——那是上一笔提交只跑 test/typecheck、没跑 lint 漏下的。

- [ ] **Step 9: 提交**

```bash
git add desktop/src/features/engines/GpuCard.tsx desktop/src/components/layout/StatusBar.tsx desktop/src/features/engines/MachinePanel.tsx desktop/src/features/engines/TtsTab.tsx desktop/src/features/engines/useGpuInfo.ts desktop/src/features/engines/deviceOptions.ts desktop/src/features/engines/__tests__/GpuCard.test.tsx desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx desktop/src/features/engines/__tests__/SeparationBackendNote.test.tsx desktop/src/components/layout/__tests__/StatusBar.test.tsx docs/superpowers/plans/2026-10-20-windows-multi-vendor-gpu.md
git commit -m "feat: GPU 文案按厂商三分支（AMF/QSV 各说各的），分离提示改读宿主事实并删除 gpuSummary"
```

## Task 10: 队列页认识 `voice_clean`，设置页摆出三厂商硬编

**Files:**
- Modify: `desktop/src/features/jobs/jobMeta.ts:10-21`（`JOB_TYPE_LABELS`）
- Modify: `desktop/src/features/jobs/jobMeta.ts:31`（`ENGINE_TYPES`）
- Modify: `desktop/src/features/jobs/jobMeta.ts:57-70`（`jobSubject` + 新增 `fileNameOf`）
- Modify: `desktop/src/features/settings/sections.ts:129-139`（`export.encoder`）
- Test: `desktop/src/features/jobs/__tests__/jobMeta.test.ts`
- Test: `desktop/src/features/settings/__tests__/sections.test.ts`

**Interfaces:**
- Consumes: Task 7 写出的 `jobs` 行——`type='voice_clean'`、`ref_id` = 清洗产物路径（`<name>.cleaned.wav`）。
- Produces: 无下游代码消费；`jobTypeLabel` / `jobRoute` / `jobSubject` 是队列抽屉与 `StatusBar` 的唯一翻译源，`export.encoder` 选项值直接进 `settings`，由 `api/export.py:654` 原样透给 ffmpeg。

**为什么这两处必须同批**：Task 7 一旦上线，队列里就出现 `type='voice_clean'` 的行——`JOB_TYPE_LABELS` 缺项会原样透出英文类型名（业主口径「漏中文」缺陷），`jobSubject` 走到末尾 `shortId(ref)` 会把 `D:\voices\柯蓉.cleaned` 的前 8 个字符当主体名，等于给用户看乱码。设置页缺 AMF/QSV 则是「后端会选、界面不说」的第二真相源。

- [ ] **Step 1: 写失败测试（jobMeta）**

在 `desktop/src/features/jobs/__tests__/jobMeta.test.ts` 的 `describe('类型词与路由')` 内追加，并把该 describe 里既有那条 `it('九种线上类型都有中文词；未知类型原样透出')` 的用例名改成 `十种`（新增一类后旧名即假账）：

```ts
  it('参考清洗：落点在引擎页，主体是产物文件名而不是短 id 前缀', () => {
    expect(jobTypeLabel('voice_clean')).toBe('参考清洗');
    expect(jobRoute(job({ type: 'voice_clean', ref_id: 'D:\\voices\\柯蓉.cleaned.wav' }))).toBe('/engines');
    expect(jobSubject(job({ type: 'voice_clean', ref_id: 'D:\\voices\\柯蓉.cleaned.wav' }), EMPTY_NAMES)).toBe(
      '柯蓉.cleaned.wav',
    );
    expect(jobSubject(job({ type: 'voice_clean', ref_id: '/data/voices/柯蓉.cleaned.wav' }), EMPTY_NAMES)).toBe(
      '柯蓉.cleaned.wav'
    );
    expect(jobSubject(job({ type: 'voice_clean', ref_id: '' }), EMPTY_NAMES)).toBe('参考清洗');
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd desktop && npm test -- jobMeta`
Expected: FAIL——`jobTypeLabel('voice_clean')` 得到 `'voice_clean'`（缺标签），`jobRoute` 得到 `null`（不在 `ENGINE_TYPES`），`jobSubject` 得到 `'D:\voice'`（走了 `shortId`）。三种失败都得出现，缺一说明测试没钉住要修的东西。

- [ ] **Step 3: 写实现（jobMeta）**

`JOB_TYPE_LABELS` 补一行（放在 `export_selfcheck` 之后，与 create 调用点同区）：

```ts
  voice_clean: '参考清洗',
```

`ENGINE_TYPES` 加成员并改掉注释——它现在装的不只是「环境安装类」：

```ts
/** 落点在引擎页的类型：ref 是固定串或产物路径，不含项目语境，因此只能聚合到 /engines。 */
const ENGINE_TYPES: ReadonlySet<string> = new Set([
  'model_download',
  'model_import',
  'cuda_runtime',
  'indextts_runtime',
  'voice_clean',
]);
```

新增私有函数并在 `jobSubject` 的 `return shortId(ref)` 之前插入分支：

```ts
/** 清洗产物是文件路径：取末段文件名展示，截前缀当短 id 等于给用户看乱码。 */
function fileNameOf(path: string): string {
  return path.split(/[/\\]/).filter((part) => part !== '').at(-1) ?? '参考清洗';
}
```

```ts
  if (job.type === 'voice_clean') return fileNameOf(ref);
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd desktop && npm test -- jobMeta`
Expected: PASS（含既有 12 条：`jobRoute` 那条断言了 `semantic` 与 `ref_id: null` 返回 `null`，本步没动这两类语义）。

- [ ] **Step 5: 写失败测试（sections）**

在 `desktop/src/features/settings/__tests__/sections.test.ts` 末尾追加。`KNOWN_KEYS` 不需改——键 `export.encoder` 已在册，本步只动选项值，服务端 `config.py:93` 默认值仍是 `auto`：

```ts
describe('视频编码选项（规格 §4.4：值必须是 ffmpeg 真编码器名，帮助文案承诺同一套）', () => {
  it('五个选项：自动 → NVENC → AMF → QSV → libx264', () => {
    const field = section('export').fields.find((f) => f.key === 'export.encoder');
    expect(field?.options?.({})).toEqual([
      { label: '自动（推荐）', value: 'auto' },
      { label: 'NVIDIA GPU（NVENC）', value: 'h264_nvenc' },
      { label: 'AMD GPU（AMF）', value: 'h264_amf' },
      { label: 'Intel 核显（QSV）', value: 'h264_qsv' },
      { label: '纯 CPU（libx264）', value: 'libx264' },
    ]);
  });

  it('帮助文案承诺 AMF / QSV，且不出现 DirectML（业主裁决：不做非 CUDA 的 AI 加速）', () => {
    const field = section('export').fields.find((f) => f.key === 'export.encoder');
    expect(field?.help).toContain('AMF');
    expect(field?.help).toContain('QSV');
    expect(field?.help).not.toContain('DirectML');
  });
});
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd desktop && npm test -- sections`
Expected: FAIL——选项数组缺 `h264_amf` / `h264_qsv` 两项；`help` 不含 `AMF`。

- [ ] **Step 7: 写实现（sections）**

`export.encoder` 字段整体替换为：

```ts
    {
      key: 'export.encoder',
      label: '视频编码',
      type: 'select',
      help: '自动=按平台真试编选择硬编（NVENC / AMF / QSV / VideoToolbox），全不可用才 libx264；固定编码器不探测，失败会按段级回退并在回执中写明',
      options: () => [
        { label: '自动（推荐）', value: 'auto' },
        { label: 'NVIDIA GPU（NVENC）', value: 'h264_nvenc' },
        { label: 'AMD GPU（AMF）', value: 'h264_amf' },
        { label: 'Intel 核显（QSV）', value: 'h264_qsv' },
        { label: '纯 CPU（libx264）', value: 'libx264' },
      ],
    },
```

不做厂商门控：设置页此时未必有 `system.health` 快照，且「固定一个本机没有的编码器 → 段级回退 + 回执写明」是规格 §4.3 承诺的可见降级链，不是缺陷。

- [ ] **Step 8: 跑测试确认通过 + 类型检查**

Run: `cd desktop && npm test -- sections && npm run typecheck`
Expected: PASS，typecheck 无输出。

- [ ] **Step 9: 提交**

```bash
git add desktop/src/features/jobs/jobMeta.ts desktop/src/features/jobs/__tests__/jobMeta.test.ts desktop/src/features/settings/sections.ts desktop/src/features/settings/__tests__/sections.test.ts
git commit -m "feat: 队列页认识参考清洗行、设置页摆出 AMF/QSV——路径型 ref 取文件名当主体，不再截短 id"
```

---

## Task 11: 全量验证、真机核对与规格订正

**Files:**
- Modify: `docs/superpowers/specs/2026-10-20-windows-multi-vendor-gpu-design.md:284`（`_is_hw_encoder` 订正）

**Interfaces:**
- Consumes: Task 1–10 的全部产出。
- Produces: 无代码产出——本任务是放行条件。

**核对已确认的事实（写在这里，避免执行者重新怀疑）**：`service/dramaclip/engines/exporter/encoder.py` 里**没有** `_is_hw_encoder()`，硬编判定是 `_HW_ENCODERS` 集合（:562）与 `:585` 的 `-c:v` 成员检查；Task 5 已按真名实现。规格 §4.3/§7.1 那句括注是作者凭印象写的，必须订正而不是让实现去追一个不存在的函数。

- [ ] **Step 1: 后端全量测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests > ../.final-pytest.txt 2>&1; echo "PYTEST_EXIT=$?"`
Expected: 基线是 **1704 passed, 1 skipped**（本会话 Step 0 实测），本批净增：Task 1 `test_gpu_multi_vendor.py`、Task 2 `test_device_profile.py`、Task 4 `test_device_resolve_wiring.py`、Task 6 `test_verify_gpu_coverage.py` 新增用例；Task 7 替换 4 处旧断言（不新增计数）。**不许用管道 `tail` 取退出码**——管道退出码是 `tail` 的，会给出假绿。
若出现顺序相关失败：先按 systematic-debugging Phase 1 定位（本仓 `test_analysis` 有已知隔离污染史），不要靠重跑碰运气。

- [ ] **Step 2: 后端静态检查**

Run: `cd service && ../.venv/Scripts/python -m ruff check dramaclip tests`
Expected: `All checks passed!`。基线此处**尚有 2 个既有错误**（10-19 二次会诊记录在案）：如果只剩那 2 个且与本批文件无关，如实记下行号继续；本批新增文件必须 0 错。

- [ ] **Step 3: 前端全量**

Run: `cd desktop && npm test && npm run typecheck && npm run lint`
Expected: vitest 全绿（本批净增 `deviceOptions.test.ts` 9 条、`GpuCard.test.tsx`、`MachinePanelEnv` 改写）；typecheck 与 lint 无输出。

- [ ] **Step 4: 协议两端一致**

Run: `cd protocol && ../service/../.venv/Scripts/python -c "import pathlib,sys;print('skip')"` — 不用；改为人工核对两处清单：
  - `protocol/ts/index.ts` 的 `GpuInfo` / `DeviceCap` / `DeviceProfile` 字段，与 `service/dramaclip/api/system.py` `health()` 实际下发的键逐一对齐（多则无用、少则前端读到 `undefined`）。
  - `protocol/ts/index.ts` 注释里的 cap 键名，与 `device_profile.py` `caps` 的键（`faster_whisper_gpu` / `indextts2_gpu` / `funasr_gpu` / `vocal_separation_gpu` / `local_visual_2b|4b|8b`）一致，且 `deviceOptions.ts` 的 `ENGINE_CAP` 映射只引用这些名字。**注意没有 `video_encode` 这一档**：视频硬件编码按规格 §4.3 只由真试编决定，不进能力表，任何地方凭想象加一个 `video_encode` cap 就是造第二个真相源。
Expected: 三处同源，无第二套拼写。

- [ ] **Step 5: 真机验真脚本（开发机只作回归）**

Run: `cd service && ../.venv/Scripts/python ../scripts/verify_gpu_coverage.py --require video.encode.cuda=pass --require video.ai_label.cuda=pass`
Expected: 退出码 0，JSON 里 `host_gpu` 记录三适配器（Quadro M4000 / RX 5500 XT / 虚拟显示）与过滤后的 primary。
**判读纪律**：这台机器的 sm_52 只证明「老卡不回退成 CPU 假成功」，不证明厂商覆盖；AMD/QSV 分支的放行证据必须是**另一台宿主**的真机跑，拿不到就在结论里写「AMD/QSV 未经真机验证」，绝不以开发机绿冒充。

- [ ] **Step 6: UI 自查（业主口径：不能只跑测试就说界面好了）**

起 `cd desktop && npm run dev`，在开发机上逐屏看：① 引擎页设备下拉——本机 `faster_whisper_gpu.ready` 为假时 CUDA 项的表现（已存 cuda → 置灰可见；未存 → 不出现在选项里）；② `GpuCard` 与 `StatusBar` 文案与 `gpu.vendor` 一致；③ 队列抽屉里一条 `voice_clean` 行的类型词与主体（跑一次参考音频清洗即产生）；④ 设置页视频编码五项。截图不作为缺陷判据——按 `dev-environment-gotchas` 记录的截图方式，且文字类问题以 DOM 文本为准。

- [ ] **Step 7: 规格订正**

`docs/superpowers/specs/2026-10-20-windows-multi-vendor-gpu-design.md` 第 284 行末尾的括注 `（\`_is_hw_encoder\`）` 改为反映真实实现：

```markdown
- `_HW_ENCODERS` 增加 `h264_amf`，使段级回退与整片 libx264 统一重跑的判定同样覆盖 AMF（判定即 `_HW_ENCODERS` 成员检查，`encoder.py:585` 读 `-c:v` 后的 codec）。
```

同批另订两处规格与代码对不上的地方（都是本会话 `核对` 阶段实测出来的，不改则下一位读者会照着假合同写）：

1. §7.1 表格 `test_hw_probe.py` 行的 `_is_hw_encoder("h264_amf") is True`——函数不存在，改为断言 `h264_amf in _HW_ENCODERS` 与 `_fallback_eligible([...,'h264_amf',...])`。
2. §11「前端/协议」文件清单补 `protocol/schemas/tts.json`（Task 7 实际要改它，规格漏列）。

- [ ] **Step 8: 提交规格订正**

```bash
git add docs/superpowers/specs/2026-10-20-windows-multi-vendor-gpu-design.md
git commit -m "docs: 规格订正硬编判定真实实现与协议清单——_is_hw_encoder 不存在，schemas/tts.json 补入涉及文件"
```

- [ ] **Step 9: 结论口径（写进最终回复，不写文件）**

必须分别交代、不许合并成一句「都好了」：① NVIDIA CUDA 三栈（ASR / TTS / 分离）各自的 `actual` 证据；② 非 NVIDIA 主机的 CPU 回执与文案；③ 视频硬编本次只到「候选序 + 真试编」，AMF/QSV 是否经真机；④ CPU 线路是否同批验证；⑤ 未验证项点名留给下一批（macOS、§9 待裁定项）。




