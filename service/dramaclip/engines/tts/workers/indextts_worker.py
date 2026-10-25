"""IndexTTS-2.5 合成 worker：在隔离 venv（Python 3.11 + torch 2.8 + transformers 4.52）内运行。

协议（stdout 逐行 JSON，stdin 同）：
  就绪行: {"ready": true, "requested": ..., "device": "cuda"|"cpu",
           "fallback": bool, "reason": "回退原因（无回退为空）"}
  请求:   {"id": "段id", "text": "...", "voice": "参考音频路径", "out": "输出wav路径", "lang": "zh"}
  应答:   {"id": "...", "ok": true} 或 {"id": "...", "ok": false, "error": "..."}

一次加载全模型（CPU 上加载约 20s、GPU 更久），进程常驻按行合成——逐段重建进程在
CPU 档（单段 100s+）完全不可接受。stderr 只走进度条/警告，不参与协议。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: IndexTTS 源码落位（tts_runtime.py 安装时解包），由桥进程经环境变量下发。
#: 上游 pyproject 的 TOML 扩展写法 pip/uv 都解析不了，不走 pip 安装——与
#: cosyvoice_worker 的 sys.path 方案同构。


def _bootstrap_sys_path() -> None:
    src = os.environ.get("DRAMACLIP_INDEXTTS_SRC")
    if src and Path(src).is_dir() and src not in sys.path:
        sys.path.insert(0, src)


def _probe_device(requested: str) -> tuple[str, str]:
    """真探针而非 is_available：老卡（如 Pascal cc5.2）会被认出但新 CUDA 栈无内核，
    载入大模型才崩——这里先跑一次最小 CUDA 运算，失败即转 CPU。"""
    if requested == "cpu":
        return "cpu", ""
    import torch  # noqa: PLC0415

    if requested.startswith("xpu"):
        if not torch.xpu.is_available():
            return "cpu", "torch.xpu.is_available() = False"
        try:
            (torch.ones(4, device="xpu") * 2).sum().item()
            return "xpu", ""
        except Exception as exc:  # noqa: BLE001 - XPU 算子/驱动缺口如实回退 CPU
            return "cpu", f"{type(exc).__name__}: {exc}"
    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda", ""
    except Exception as exc:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理，诚实回 CPU
        torch.cuda.empty_cache()
        print(">> CUDA 探针失败，回退 CPU", file=sys.stderr)
        return "cpu", f"{type(exc).__name__}: {exc}"


def main() -> int:
    model_dir = sys.argv[1]
    requested = sys.argv[2] if len(sys.argv) > 2 else "auto"

    # 库的进度信息（">> GPT weights restored..." 等 print）走 stdout 会污染 JSON 协议——
    # 在 import 任何 indextts 模块前把 fd 1 换成 stderr，协议行用真正的 stdout 写。
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    proto = os.fdopen(real_stdout, "w", encoding="utf-8")

    def send(obj: dict[str, object]) -> None:
        proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proto.flush()

    _bootstrap_sys_path()
    device, probe_reason = _probe_device(requested)
    no_cuda = probe_reason.startswith("torch.cuda.is_available")
    fallback = bool(probe_reason) and requested != "cpu" and not no_cuda
    reason = probe_reason if fallback else ""
    if requested == "cuda" and device != "cuda":
        send({"ready": False, "error": f"请求 CUDA 但探针失败：{probe_reason or '未知原因'}"})
        return 1

    from indextts.infer_v2_5 import IndexTTS2  # noqa: PLC0415

    try:
        tts = IndexTTS2(
            cfg_path=f"{model_dir}\\config.yaml",
            model_dir=model_dir,
            device=device,
        )
    except Exception as exc:  # noqa: BLE001 - 构造期 CUDA 故障按请求语义分叉
        if device != "cuda" or requested == "cuda":
            send({"ready": False, "error": f"模型加载失败：{type(exc).__name__}: {exc}"})
            return 1
        print(f">> CUDA 加载失败回退 CPU：{str(exc)[:160]}", file=sys.stderr)
        device, fallback = "cpu", True
        reason = f"{type(exc).__name__}: {exc}"
        try:
            tts = IndexTTS2(
                cfg_path=f"{model_dir}\\config.yaml",
                model_dir=model_dir,
                device=device,
            )
        except Exception as cpu_exc:  # noqa: BLE001 - CPU 也起不来就是真失败
            send({"ready": False, "error": f"CPU 加载也失败：{type(cpu_exc).__name__}: {cpu_exc}"})
            return 1

    send({
        "ready": True, "requested": requested, "device": device,
        "fallback": fallback, "reason": reason,
    })

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            tts.infer(job["voice"], job["text"], job["out"], lang=job.get("lang", "zh"))
            reply = {"id": job["id"], "ok": True}
        except Exception as exc:  # noqa: BLE001 - 逐段失败只回错误，进程不死（后续段继续）
            reply = {"id": job.get("id", "?"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        send(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
