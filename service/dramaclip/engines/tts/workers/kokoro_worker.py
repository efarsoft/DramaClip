"""kokoro TTS worker：在隔离 venv（tts-venv，Python 3.11 + torch + kokoro）内运行。

协议（stdout 逐行 JSON，stdin 同；与 indextts_worker 同构）：
  就绪行: {"ready": true, "requested": ..., "device": "cuda"|"cpu",
           "fallback": bool, "reason": "回退原因（无回退为空）"}
  请求:   {"id": "...", "kwargs": {"pieces": ["块1", ...], "voice_pt": "路径", "out": "路径"}}
  应答:   {"id": "...", "ok": true} 或 {"id": "...", "ok": false, "error": "..."}

切块在主进程做（text_split.split_long_text 单一真相），worker 收整块列表逐块
推理后 numpy 拼接落单文件——venv 进程不能 import dramaclip，worker 必须自包含。
模型加载一次常驻；长文本的内存与耗时靠块边界可控（与主进程旧实现同语义）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_SAMPLE_RATE = 24000


def _probe_device(requested: str) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", ""
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda", ""
    except Exception as exc:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理
        torch.cuda.empty_cache()
        return "cpu", f"{type(exc).__name__}: {exc}"


def main() -> int:
    cfg = json.loads(sys.argv[1])
    model_dir = Path(cfg["model_dir"])
    requested = str(cfg.get("device") or "auto")
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def _emit(obj: dict[str, Any]) -> None:
        os.write(real_stdout, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    try:
        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415
        import torch  # noqa: PLC0415
        from kokoro import KPipeline  # noqa: PLC0415
        from kokoro.model import KModel  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - 依赖缺失要说清，而不是静默退进程
        _emit({"ready": False, "error": f"依赖导入失败：{type(exc).__name__}: {exc}"})
        return 1

    device, probe_reason = _probe_device(requested)
    no_cuda = probe_reason.startswith("torch.cuda.is_available")
    fallback = bool(probe_reason) and requested != "cpu" and not no_cuda
    reason = probe_reason if fallback else ""
    if requested == "cuda" and device != "cuda":
        _emit({"ready": False, "error": f"请求 CUDA 但探针失败：{probe_reason or '未知原因'}"})
        return 1

    def _load(target: str) -> Any:
        model = KModel(
            config=str(model_dir / "config.json"),
            model=str(model_dir / "kokoro-v1_1-zh.pth"),
        )
        return model.to(torch.device(target)).eval()

    try:
        kmodel = _load(device)
    except Exception as exc:  # noqa: BLE001 - 构造期 CUDA 故障按请求语义分叉
        if device != "cuda" or requested == "cuda":
            _emit({"ready": False, "error": f"模型加载失败：{type(exc).__name__}: {exc}"})
            return 1
        print(f">> CUDA 加载失败回退 CPU：{str(exc)[:160]}", file=sys.stderr)
        device, fallback = "cpu", True
        reason = f"{type(exc).__name__}: {exc}"
        try:
            kmodel = _load(device)
        except Exception as cpu_exc:  # noqa: BLE001 - CPU 也起不来就是真失败
            _emit({"ready": False, "error": f"CPU 加载也失败：{type(cpu_exc).__name__}: {cpu_exc}"})
            return 1

    pipeline = KPipeline(lang_code="z", model=kmodel)
    _emit({
        "ready": True, "requested": requested, "device": device,
        "fallback": fallback, "reason": reason,
    })
    request: dict[str, Any] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            kwargs = request["kwargs"]
            pieces = [str(p) for p in kwargs["pieces"]] or [""]
            segments: list[Any] = []
            for piece in pieces:
                for _gs, _ps, audio in pipeline(piece, voice=str(kwargs["voice_pt"])):
                    segments.append(np.asarray(audio))
            audio_np = np.concatenate(segments) if segments else np.zeros(0, dtype="float32")
            out = Path(str(kwargs["out"]))
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), audio_np, _SAMPLE_RATE)
            _emit({"id": request.get("id"), "ok": True})
        except Exception as exc:  # noqa: BLE001 - 单次合成失败按应答回传，不炸 worker
            _emit({
                "id": request.get("id"),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
