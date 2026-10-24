"""acestep 配乐生成 worker：在隔离 venv（music-venv，Python 3.11 + torch 2.7.1 + acestep）内运行。

协议（stdout 逐行 JSON，stdin 同；与 kokoro_worker 同构）：
  就绪行: {"ready": true, "requested": ..., "device": "cuda"|"cpu",
           "fallback": bool, "reason": "", "lm": bool}
  请求:   {"id": "...", "kwargs": {"caption": ..., "duration_s": 120, "bpm": 110,
                                   "out_dir": "路径"}}
  应答:   {"id": "...", "ok": true, "path": "产物wav", "device": "cuda"}
      或  {"id": "...", "ok": false, "error": "..."}

venv 进程不能 import dramaclip——本文件自包含。核心拆成 ``setup()`` /
``generate_one()`` 两个纯函数：协议循环只是薄壳，主进程 inproc 路径
（engines/music/engine.py）经 importlib 直接加载本文件复用同一份逻辑。

上游对接（acestep 1.5，MIT）：``AceStepHandler.initialize_service`` 按
``ACESTEP_CHECKPOINTS_DIR`` 下的注册名子目录装载（acestep-v15-sft / vae /
Qwen3-Embedding-0.6B / 可选 acestep-5Hz-lm-0.6B）——目录由主进程以 Windows
junction 预先映射（engine._ensure_checkpoints_view），worker 只认 config 给的根。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# 上游在 VAE 缺省档按 <checkpoints>/vae 找官方解码器；text encoder 目录名同样
# 被上游硬编码。LM 不装时 thinking 组全关，纯 DiT 路径出曲。
_DIT_NAME = "acestep-v15-sft"
_LM_NAME = "acestep-5Hz-lm-0.6B"

#: SFT（非 turbo）的扩散步数：上游口径 turbo=8、base 系 32–100，取下限保速度
_INFERENCE_STEPS = 32


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


def setup(cfg: dict[str, Any]) -> dict[str, Any]:
    """装载模型（一次常驻）。返回会话上下文：handler/llm/device/lm 开关。"""
    checkpoints = Path(str(cfg["checkpoints"]))
    requested = str(cfg.get("device") or "auto")

    # 环境变量必须在 import acestep 之前就位（上游模块级读一次）
    os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(checkpoints)
    os.environ.setdefault("ACESTEP_PROJECT_ROOT", str(checkpoints.parent))
    os.environ["TORCHAUDIO_USE_BACKEND"] = "ffmpeg"
    os.environ["ACESTEP_DISABLE_TQDM"] = "1"

    from acestep.handler import AceStepHandler  # noqa: PLC0415
    from acestep.inference import GenerationConfig, GenerationParams, generate_music  # noqa: PLC0415,F401
    from acestep.llm_inference import LLMHandler  # noqa: PLC0415

    device, probe_reason = _probe_device(requested)
    no_cuda = probe_reason.startswith("torch.cuda.is_available")
    fallback = bool(probe_reason) and requested != "cpu" and not no_cuda
    reason = probe_reason if fallback else ""
    if requested == "cuda" and device != "cuda":
        raise RuntimeError(f"请求 CUDA 但探针失败：{probe_reason or '未知原因'}")

    handler = AceStepHandler()
    _msg, ok = handler.initialize_service(
        project_root=str(checkpoints.parent),
        config_path=_DIT_NAME,
        device=device,
        vae_checkpoint=None,  # 缺省 official = <checkpoints>/vae（junction 已映射）
    )
    if not ok:
        raise RuntimeError(f"ACE-Step 装载失败：{_msg}")

    lm_ready = False
    lm = LLMHandler()
    if (checkpoints / _LM_NAME / "model.safetensors").is_file():
        try:
            _lm_msg, lm_ok = lm.initialize(
                checkpoint_dir=str(checkpoints),
                lm_model_path=_LM_NAME,
                backend="pt",
                device=device,
            )
            lm_ready = bool(lm_ok)
        except Exception as exc:  # noqa: BLE001 - LM 失败降级纯 DiT 出曲，不炸会话
            print(f">> LM 初始化失败，降级纯 DiT：{str(exc)[:160]}", file=sys.stderr)
    return {
        "handler": handler,
        "llm": lm,
        "llm_ready": lm_ready,
        "device": device,
        "requested": requested,
        "fallback": fallback,
        "reason": reason,
    }


def generate_one(ctx: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """单曲生成：caption+时长+bpm → wav 落盘。返回 {"path", "device"}。"""
    from acestep.inference import GenerationConfig, GenerationParams, generate_music  # noqa: PLC0415

    lm_ready = bool(ctx.get("llm_ready"))
    out_dir = Path(str(kwargs["out_dir"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    params = GenerationParams(
        caption=str(kwargs["caption"]),
        lyrics="[Instrumental]",
        instrumental=True,
        duration=float(kwargs["duration_s"]),
        bpm=(int(kwargs["bpm"]) if kwargs.get("bpm") else None),
        vocal_language="unknown",
        inference_steps=_INFERENCE_STEPS,
        thinking=lm_ready,
        use_cot_metas=lm_ready,
        use_cot_caption=lm_ready,
        use_cot_language=lm_ready,
    )
    config = GenerationConfig(batch_size=1, audio_format="wav", use_random_seed=True)
    result = generate_music(
        ctx["handler"], ctx["llm"], params, config, save_dir=str(out_dir),
    )
    if not result.success:
        raise RuntimeError(str(result.error or "生成失败（上游未给出原因）"))
    for audio in result.audios:
        path = str(audio.get("path") or "")
        if path and Path(path).is_file():
            return {"path": path, "device": str(ctx.get("device") or "")}
    raise RuntimeError("生成完成但没有产物文件（上游 audios 为空）")


def main() -> int:
    cfg = json.loads(sys.argv[1])
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def _emit(obj: dict[str, Any]) -> None:
        os.write(real_stdout, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    try:
        ctx = setup(cfg)
    except Exception as exc:  # noqa: BLE001 - 依赖/模型缺失要说清，而不是静默退进程
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    _emit({
        "ready": True,
        "requested": ctx.get("requested"),
        "device": ctx.get("device"),
        "fallback": ctx.get("fallback"),
        "reason": ctx.get("reason"),
        "lm": ctx.get("llm_ready"),
    })
    request: dict[str, Any] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            produced = generate_one(ctx, request["kwargs"])
            _emit({"id": request.get("id"), "ok": True, **produced})
        except Exception as exc:  # noqa: BLE001 - 单次生成失败按应答回传，不炸 worker
            _emit({
                "id": request.get("id"),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
