"""funasr ASR worker：在隔离 venv（tts-venv，Python 3.11 + torch + funasr）内运行。

协议（stdout 逐行 JSON，stdin 同；与 indextts_worker 同构）：
  就绪行: {"ready": true, "device": "cuda"|"cpu"}
  请求:   {"id": "...", "kwargs": {"input": "wav路径", ...funasr generate 参数}}
  应答:   {"id": "...", "ok": true, "raw": [...]} 或 {"id": "...", "ok": false, "error": "..."}

一次加载模型常驻——paraformer+vad+CAM++ 加载分钟级，逐请求重建进程完全不可
接受；进程生命周期由主进程桥（transcriber._FunasrWorker）持有，service_app
退出时统一 shutdown。库的进度/警告 print 走 stdout 会污染 JSON 协议，import
funasr 前把 fd 1 换成 stderr，协议行用保存的真 stdout 写（indextts_worker 同
一招）。构造参数经 argv[1] 传 JSON（模型目录含空格也安全）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

_CUDA_PROBLEM = re.compile(r"cublas|cudnn|cudart|cuda|gpu|int8 compute type", re.I)

# 与主进程 transcriber._PUNC_FALSE_ALARM 同一条假警报（paraformer 挂 spk 不挂
# punc 时 funasr 每次请求打一条 error）——worker 里没有那套 logger 过滤，这里
# 按同款原文过滤，stderr 只留真警告。
_PUNC_FALSE_ALARM = "Missing punc_model, which is required by spk_model."


def _probe_device(device: str) -> tuple[str, str]:
    """返回 (实际设备, 原因)。显式 cuda 的探针失败由调用方直接判失败。"""
    if device == "cpu":
        return "cpu", ""
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda:0", ""
    except Exception as exc:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理，诚实回 CPU
        torch.cuda.empty_cache()
        print(">> CUDA 探针失败，回退 CPU", file=sys.stderr)
        return "cpu", f"{type(exc).__name__}: {exc}"


def _model_device(model: Any) -> str | None:
    """模型真实落点：参数设备是物理证据，funasr 解析后的 kwargs.device 是退路。

    与 transcriber._model_device 同一判据（worker 进程不能 import dramaclip）。
    """
    inner = getattr(model, "model", model)
    parameters = getattr(inner, "parameters", None)
    if callable(parameters):
        try:
            first = next(parameters())
        except (StopIteration, TypeError):
            first = None
        kind = getattr(getattr(first, "device", None), "type", None)
        if kind in {"cuda", "cpu"}:
            return str(kind)
    resolved = getattr(model, "kwargs", None)
    if isinstance(resolved, dict):
        value = str(resolved.get("device") or "")
        if value:
            return "cuda" if value.startswith("cuda") else "cpu"
    return None


def _build_kwargs(cfg: dict[str, Any], device: str) -> dict[str, Any]:
    """与主进程两引擎的 _ensure_model 同一套构造语义（镜像实现，别分叉）。"""
    if cfg["engine"] == "sensevoice":
        model = cfg.get("model") or "iic/SenseVoiceSmall"
        return {"model": model, "device": device}
    model = cfg.get("model") or (
        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    )
    kwargs: dict[str, Any] = {"model": model, "disable_update": True, "device": device}
    spk_dir = cfg.get("spk_model_dir")
    if spk_dir:
        vad_dir = cfg.get("vad_model_dir")
        # funasr 的 diarization 必须挂 vad_model（嵌入按语音区间提取）；spk_mode
        # 显式走 vad_segment（punc_segment 要标点模型，不装会先打 error 再自改）。
        kwargs["vad_model"] = str(vad_dir) if vad_dir else "fsmn-vad"
        spk = Path(spk_dir)
        if spk.is_dir():
            kwargs["spk_model"] = str(spk)
            weight = spk / "campplus_cn_common.bin"
            if weight.is_file():
                # funasr 本地目录加载把权重名硬编码成 model.pt；CAM++ 的实名经
                # 组件通道 init_param 指路，不能放顶层（会把权重喂给主模型）。
                kwargs["spk_kwargs"] = {"init_param": str(weight)}
        else:
            kwargs["spk_model"] = "cam++"
        kwargs["spk_mode"] = "vad_segment"
    return kwargs


def _plain(value: Any) -> Any:
    """funasr 返回值里的 ndarray/对象 → JSON 可序列化（时间戳数组是 ndarray 常客）。"""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    tolist = getattr(value, "tolist", None)
    if tolist is not None:
        return _plain(tolist())
    return str(value)


def main() -> int:
    cfg = json.loads(sys.argv[1])
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def _emit(obj: dict[str, Any]) -> None:
        os.write(real_stdout, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    logging.getLogger("funasr").addFilter(_PuncFilter())

    from funasr import AutoModel  # noqa: PLC0415 - 本文件只在 venv 内运行

    requested = str(cfg.get("device") or "auto")
    device, probe_reason = _probe_device(requested)
    if requested == "cuda" and device != "cuda:0":
        _emit({"ready": False, "error": f"请求 CUDA 但探针失败：{probe_reason}"})
        return 1
    # 机器没有 CUDA 不算「试过 GPU 后失败」：fallback 只在真探针失败时为真。
    no_cuda = probe_reason.startswith("torch.cuda.is_available")
    fallback = bool(probe_reason) and requested != "cpu" and not no_cuda
    reason = probe_reason if fallback else ""
    kwargs = _build_kwargs(cfg, device)
    try:
        model = AutoModel(**kwargs)
    except Exception as exc:  # noqa: BLE001 - CUDA 类失败按请求语义处理
        if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
            raise
        if requested == "cuda":
            _emit({"ready": False, "error": f"CUDA 加载失败：{type(exc).__name__}: {exc}"})
            return 1
        print(f">> CUDA 加载失败回退 CPU: {str(exc)[:160]}", file=sys.stderr)
        device = "cpu"
        fallback = True
        reason = f"{type(exc).__name__}: {exc}"
        kwargs["device"] = device
        model = AutoModel(**kwargs)

    actual = _model_device(model)
    if actual is not None:
        if requested == "cpu" and actual != "cpu":
            _emit({"ready": False, "error": f"请求 CPU 但 funasr 把模型落在 {actual}"})
            return 1
        if device.startswith("cuda") and actual != "cuda":
            if requested == "cuda":
                _emit({
                    "ready": False,
                    "error": f"请求 CUDA 但 funasr 把模型落在 {actual}（静默回退）",
                })
                return 1
            fallback = True
            reason = f"funasr 把模型落在 {actual}"
        device = actual

    _emit({
        "ready": True,
        "device": device,
        "requested": requested,
        "fallback": fallback,
        "reason": reason,
    })
    request: dict[str, Any] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            raw = model.generate(**request["kwargs"])
            _emit({"id": request.get("id"), "ok": True, "raw": _plain(raw)})
        except Exception as exc:  # noqa: BLE001 - 单次转写失败按应答回传，不炸 worker
            _emit({
                "id": request.get("id"),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return 0


class _PuncFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _PUNC_FALSE_ALARM not in record.getMessage()


if __name__ == "__main__":
    raise SystemExit(main())
