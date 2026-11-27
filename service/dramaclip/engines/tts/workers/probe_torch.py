"""torch 设备探针单源：真探针而非 is_available（funasr/kokoro/indextts 的共享实现）。

为什么单源：老卡（如 Pascal cc5.2）会被认出但新 CUDA 栈无内核，载入大模型才崩——
先跑一次最小运算，失败按线回退。此前这份探针在 funasr/kokoro/indextts 三个 worker
与 kokoro 引擎侧各持一份整段克隆，改探针语义要四处同步（2026-11-19 gpu 词汇裁决
对齐 auto→xpu 时就是挨个手抄的）。

导入走双路：引擎侧（主进程/进程内路径）走包导入，mypy/IDE 可解析；worker 由 venv
python 按路径执行（sys.path[0]=本目录），且冻结态 worker .py 以 --add-data 落盘而
包源码不在盘上——worker 进程里 ``import dramaclip`` 必然 ImportError，落同目录
兄弟模块。两条路指向同一个物理文件，行为一致；worker venv 的「自包含」不变式不受
影响（从不依赖包导入成功）。

cosyvoice/acestep 两份探针**没有**并进来：它们在 auto/gpu 请求下只试 cuda 线
（cosyvoice 的 xpu 是单线早退风格），与本模块的「全链 cuda → xpu」语义不同——
是有意为之还是漏对齐未查证，合并等于悄悄改设备选择行为，留待真机验证后另行处理。
"""

from __future__ import annotations

import sys


def probe_device(
    requested: str,
    *,
    cuda_label: str = "cuda",
    stderr_note: bool = False,
) -> tuple[str, str]:
    """返回 (实际设备, 原因)。gpu/auto 按厂商优先级试全链（cuda → xpu）；
    cpu 恒 CPU；单后端请求只试该线。

    ``cuda_label``：funasr 用 "cuda:0"（模型移位要整卡名），其余统一 "cuda"。
    ``stderr_note``：funasr/indextts 原行为在 CUDA 探针失败时附一行 stderr 提示，
    保持逐份忠实不静默改日志。
    """
    if requested == "cpu":
        return "cpu", ""
    import torch  # noqa: PLC0415 - 探针只在真要试卡时才碰 torch

    if requested.startswith("xpu"):
        lines: tuple[str, ...] = ("xpu",)
    elif requested in ("auto", "gpu"):
        lines = ("cuda", "xpu")
    else:
        lines = ("cuda",)
    reasons: list[str] = []
    for line in lines:
        if line == "cuda":
            if not torch.cuda.is_available():
                reasons.append("torch.cuda.is_available() = False")
                continue
            try:
                (torch.ones(4, device="cuda") * 2).sum().item()
                return cuda_label, ""
            except Exception as exc:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理
                torch.cuda.empty_cache()
                if stderr_note:
                    print(">> CUDA 探针失败，回退 CPU", file=sys.stderr)
                reasons.append(f"{type(exc).__name__}: {exc}")
        else:
            if not torch.xpu.is_available():
                reasons.append("torch.xpu.is_available() = False")
                continue
            try:
                (torch.ones(4, device="xpu") * 2).sum().item()
                return "xpu", ""
            except Exception as exc:  # noqa: BLE001 - XPU 算子/驱动缺口如实回退 CPU
                reasons.append(f"{type(exc).__name__}: {exc}")
    return "cpu", "；".join(reasons)
