"""
CosyVoice3 Sidecar 入口（DramaClip 隔离模式）

运行在独立 Python 环境中（推荐使用专属 venv），与主 DramaClip 进程隔离。

协议：长度前缀 JSON（与 subprocess_tts_backend.py 完全一致）

当前为骨架实现，后续会逐步完善：
- 延迟加载 CosyVoice 模型（ready 时不加载模型）
- 支持 synthesize + 参考音频 / instruct / zero-shot 等
- 进度上报
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from typing import Optional

# 保持与父进程一致的常量
MAX_FRAME_BYTES = 64 * 1024 * 1024


def _send(stream, obj: dict) -> None:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise IOError(f"帧过大: {len(body)}")
    stream.write(struct.pack("!I", len(body)))
    stream.write(body)
    stream.flush()


def _recv(stream):
    header = stream.read(4)
    if len(header) < 4:
        return None
    (n,) = struct.unpack("!I", header)
    if n > MAX_FRAME_BYTES:
        raise IOError(f"帧过大: {n}")
    body = bytearray()
    while len(body) < n:
        chunk = stream.read(n - len(body))
        if not chunk:
            raise IOError("短读")
        body.extend(chunk)
    return json.loads(bytes(body).decode("utf-8"))


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    # 立即发送 ready（模型延迟加载）
    _send(stdout, {
        "op": "ready",
        "engine": "cosyvoice",
        "sample_rate": 22050,   # Fun-CosyVoice3 当前常见采样率
        "version": "subprocess-v1"
    })

    # 延迟加载模型
    _cosyvoice_model = None
    _current_model_dir = None
    _sample_rate = 22050

    def _find_and_load_model(requested_dir: Optional[str] = None):
        nonlocal _cosyvoice_model, _current_model_dir, _sample_rate

        if _cosyvoice_model is not None:
            return

        # Resolve project root for absolute fallback paths
        _project_root = Path(__file__).resolve().parent.parent.parent.parent.parent

        candidates = []
        if requested_dir:
            candidates.append(requested_dir)
        candidates.extend([
            str(_project_root / "pretrained_models" / "Fun-CosyVoice3-0.5B-2512"),
            str(_project_root / "pretrained_models" / "FunAudioLLM--Fun-CosyVoice3-0.5B-2512"),
        ])

        model_dir = None
        for p in candidates:
            if p and Path(p).exists():
                model_dir = p
                break

        if not model_dir:
            raise RuntimeError("未找到 CosyVoice3 模型。请先在模型管理中下载 FunAudioLLM/Fun-CosyVoice3-0.5B-2512")

        # 兼容 yaml 文件名
        p = Path(model_dir)
        if (p / "cosyvoice3.yaml").exists() and not (p / "cosyvoice.yaml").exists():
            try:
                import shutil
                shutil.copy(p / "cosyvoice3.yaml", p / "cosyvoice.yaml")
            except Exception:
                pass

        print(f"[cosyvoice-sidecar] 正在加载模型: {model_dir}", file=sys.stderr)
        _send(stdout, {"op": "progress", "stage": "loading_model", "percent": 10, "message": "开始加载 CosyVoice 模型..."})

        try:
            from cosyvoice.cli.cosyvoice import AutoModel
            _cosyvoice_model = AutoModel(model_dir=model_dir)
            if hasattr(_cosyvoice_model, "sample_rate"):
                _sample_rate = _cosyvoice_model.sample_rate
            _current_model_dir = model_dir
            print("[cosyvoice-sidecar] AutoModel 加载成功", file=sys.stderr)
            _send(stdout, {"op": "progress", "stage": "loading_model", "percent": 90, "message": "模型加载完成"})
        except Exception as e1:
            print(f"[cosyvoice-sidecar] AutoModel 失败，尝试 CosyVoice 类: {e1}", file=sys.stderr)
            from cosyvoice.cli.cosyvoice import CosyVoice
            _cosyvoice_model = CosyVoice(model_dir)
            _current_model_dir = model_dir
            print("[cosyvoice-sidecar] CosyVoice 类加载成功", file=sys.stderr)
            _send(stdout, {"op": "progress", "stage": "loading_model", "percent": 90, "message": "模型加载完成"})

    while True:
        try:
            msg = _recv(stdin)
            if msg is None:
                break

            op = msg.get("op")

            if op == "ping":
                _send(stdout, {"op": "pong"})

            elif op == "synthesize":
                text = msg.get("text", "")
                ref_audio = msg.get("ref_audio")
                ref_text = msg.get("ref_text")
                instruct = msg.get("instruct")
                speed = float(msg.get("speed", 1.0))
                requested_model_dir = msg.get("model_dir")

                try:
                    _find_and_load_model(requested_model_dir)
                except Exception as load_err:
                    _send(stdout, {
                        "op": "error",
                        "stage": "model_load",
                        "message": str(load_err)
                    })
                    continue

                # 执行推理
                try:
                    import numpy as np

                    safe_speed = max(0.5, min(2.0, speed))

                    if ref_audio and ref_text:
                        results = _cosyvoice_model.inference_zero_shot(text, ref_text, ref_audio, speed=safe_speed)
                    elif instruct:
                        results = _cosyvoice_model.inference_instruct2(text, instruct, ref_audio or "", speed=safe_speed)
                    else:
                        results = _cosyvoice_model.inference_sft(text, "中文女", speed=safe_speed)

                    pieces = []
                    for chunk in results:
                        wav = chunk.get("tts_speech")
                        if wav is None:
                            continue
                        if isinstance(wav, np.ndarray):
                            wav = np.asarray(wav, dtype=np.float32)
                        pieces.append(wav)

                    if not pieces:
                        raise RuntimeError("模型未返回有效音频")

                    audio = np.concatenate(pieces, axis=0)
                    pcm = (audio * 32767).astype("int16").tobytes()
                    pcm_b64 = base64.b64encode(pcm).decode("ascii")

                    _send(stdout, {
                        "op": "audio",
                        "audio_pcm_b64": pcm_b64,
                        "sample_rate": _sample_rate,
                        "n_samples": len(audio),
                        "text": text[:80] + "..." if len(text) > 80 else text
                    })

                except Exception as infer_err:
                    tb = traceback.format_exc()
                    _send(stdout, {
                        "op": "error",
                        "stage": "inference",
                        "message": f"CosyVoice 推理失败: {infer_err}",
                        "traceback": tb
                    })

            elif op == "shutdown":
                _send(stdout, {"op": "ok", "message": "shutting down"})
                return 0

            else:
                _send(stdout, {
                    "op": "error",
                    "stage": "dispatch",
                    "message": f"unknown op: {op}"
                })

        except Exception as e:
            tb = traceback.format_exc()
            try:
                _send(stdout, {
                    "op": "error",
                    "stage": "runtime",
                    "message": str(e),
                    "traceback": tb
                })
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
