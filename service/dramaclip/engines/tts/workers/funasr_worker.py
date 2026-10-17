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


def _probe_device(device: str) -> str:
    """auto → 真探针（最小 CUDA 运算）：老卡被认出但新 CUDA 栈无内核，载入大模型才崩。"""
    if device not in ("", "auto"):
        return "cuda:0" if device == "cuda" else device
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return "cpu"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda:0"
    except Exception:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理，诚实回 CPU
        torch.cuda.empty_cache()
        print(">> CUDA 探针失败，回退 CPU", file=sys.stderr)
        return "cpu"


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

    logging.getLogger("funasr").addFilter(_PuncFilter())

    from funasr import AutoModel  # noqa: PLC0415 - 本文件只在 venv 内运行

    device = _probe_device(str(cfg.get("device") or "auto"))
    kwargs = _build_kwargs(cfg, device)
    try:
        model = AutoModel(**kwargs)
    except Exception as exc:  # noqa: BLE001 - CUDA 类失败回退 CPU 重试一次（同主进程语义）
        if device != "cpu" and _CUDA_PROBLEM.search(str(exc)):
            print(f">> CUDA 加载失败回退 CPU: {str(exc)[:160]}", file=sys.stderr)
            device = "cpu"
            kwargs["device"] = device
            model = AutoModel(**kwargs)
        else:
            raise

    def _emit(obj: dict[str, Any]) -> None:
        os.write(real_stdout, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    _emit({"ready": True, "device": device})
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
