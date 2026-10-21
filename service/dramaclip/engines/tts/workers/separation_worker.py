"""人声分离 worker：在隔离 venv（tts-venv，audio-separator）内运行。

与 cosyvoice_worker / indextts_worker 的常驻协议不同，这是一次性进程：一次清洗
一条参考音频，跑完即退（模型加载 + 分离在 CPU 上约 30s，用户点击级操作不值得
常驻占显存/内存）。协议是一行 JSON 到 stdout：
  {"ok": true, "out": "<干声路径>", "requested": "...", "resolved": "...",
   "actual": "cuda|cpu", "fallback": false, "reason": "", "providers": [...]}
或 {"ok": false, "error": "..."}。诊断日志全部走库内 logger→stderr——stdout 是
协议通道，混进日志就是坏帧。

CUDA DLL 注入必须在 import onnxruntime / audio_separator **之前**：PATH 会被
子进程继承，add_dll_directory 不会，所以由 worker 自己对 cuda_runtime 的
cuBLAS/cuDNN/cuDART/cuFFT 目录做两件事。--probe 只建一个极小 ONNX CUDA session，
供安装期验真；它不加载分离模型。

模型是单文件 MDX-Net（UVR_MDXNET_KARA_2.onnx，约 50MB）：模型文件由主进程负责
就位（含 gh-proxy 多源下载，见 vocal_separation.py），worker 只认 --models 里的
本地文件，不做任何下载——下载策略换掉时 worker 不用跟着改。

产物取 (Vocals) 干声（BGM/音效进 (Instrumental)，正是要剥掉的部分），落盘为
44.1kHz 立体声 wav；克隆引擎侧用 librosa/torchaudio 读参考时自带单声道化与
重采样，这里不再二次加工、不偷采样率。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

#: 与主进程 vocal_separation.MODEL_FILENAME 必须一致：两边各写一份是刻意的——
#: worker 在隔离 venv 里 import 不到主服务包，跨进程共享只能靠约定。
MODEL_FILENAME = "UVR_MDXNET_KARA_2.onnx"
_CUDA_SUBDIRS = ("cublas", "cudnn", "cudart", "cufft")
#: add_dll_directory 的句柄一旦被 GC 就失效：必须留引用到进程结束。
_DLL_HANDLES: list[Any] = []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="src")
    parser.add_argument("--out", dest="out")
    parser.add_argument("--models", dest="models")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cuda-dll-dir", dest="cuda_dll_dir", default="")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()

    cuda_root = Path(args.cuda_dll_dir) if args.cuda_dll_dir else None
    _inject_cuda_dlls(cuda_root, torch_lib=_torch_lib())

    if args.probe:
        payload = probe_cuda()
        _emit(payload)
        return 0 if payload.get("ok") else 1
    if not (args.src and args.out and args.models):
        parser.error("--in/--out/--models are required unless --probe is used")
    try:
        payload = separate(
            Path(args.src), Path(args.out), Path(args.models),
            device=args.device, cuda_dll_dir=cuda_root,
        )
    except Exception as exc:  # noqa: BLE001 - 任何失败都要变成一行协议应答，不能裸崩
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    _emit(payload)
    return 0


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _torch_lib() -> Path | None:
    """GPU 变体 torch 自带的 cuDNN 9 族（新版 ORT 用）；CPU 轮下目录不存在。"""
    candidate = Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib"
    return candidate if candidate.is_dir() else None


def _add_dll_dir(path: Path) -> None:
    add = getattr(os, "add_dll_directory", None)
    if add is not None:
        _DLL_HANDLES.append(add(str(path)))


def _inject_cuda_dlls(cuda_root: Path | None, *, torch_lib: Path | None) -> list[Path]:
    """把 CUDA DLL 目录同时放进 PATH 与 add_dll_directory；只注入存在的目录。"""
    if sys.platform != "win32":
        return []
    dirs: list[Path] = []
    if cuda_root is not None:
        for name in _CUDA_SUBDIRS:
            candidate = cuda_root / name
            if candidate.is_dir():
                dirs.append(candidate)
    if torch_lib is not None and torch_lib.is_dir():
        dirs.append(torch_lib)
    if not dirs:
        return []
    for directory in dirs:
        _add_dll_dir(directory)
    os.environ["PATH"] = (
        os.pathsep.join(str(d) for d in dirs) + os.pathsep + os.environ.get("PATH", "")
    )
    return dirs


def _provider_plan(device: str, available: list[str]) -> tuple[list[str], str]:
    """requested 与实际 provider 计划：cpu 永不碰 CUDA，显式 cuda 无 EP 直接失败。"""
    requested = device.strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"未知算力请求: {device!r}（可用: auto / cpu / cuda）")
    if requested == "cpu":
        return ["CPUExecutionProvider"], "cpu"
    if "CUDAExecutionProvider" not in available:
        if requested == "cuda":
            raise RuntimeError(
                "onnxruntime 没有 CUDAExecutionProvider（装的是 CPU 轮或 CUDA DLL 缺失）"
            )
        return ["CPUExecutionProvider"], "cpu"
    return ["CUDAExecutionProvider"], "cuda"


@contextmanager
def _record_sessions(ort: Any) -> Iterator[list[list[str]]]:
    """捕获 audio_separator 内部创建的 session：实际 provider 只能从 session 读。"""
    original = ort.InferenceSession
    captured: list[list[str]] = []

    class _RecordingSession(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            captured.append(list(self.get_providers()))

    ort.InferenceSession = _RecordingSession
    try:
        yield captured
    finally:
        ort.InferenceSession = original


def _run_attempt(
    src: Path, out: Path, models_dir: Path, providers: list[str]
) -> list[str]:
    """跑一次分离，返回实际 session provider；产物原子改名到 out。"""
    import onnxruntime as ort
    from audio_separator.separator import Separator

    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".sep-", dir=work))
    try:
        separator = Separator(
            model_file_dir=str(models_dir), output_dir=str(temp), output_format="WAV"
        )
        # 构造后、load_model 前覆盖：audio_separator 只按 torch.cuda 选默认 provider，
        # 而本 venv 的 torch 可能是 CPU 轮（ORT GPU 与 torch 变体是两回事）。
        separator.onnx_execution_provider = providers
        with _record_sessions(ort) as sessions:
            separator.load_model(MODEL_FILENAME)
            stems = separator.separate(str(src))
        actual = sessions[-1] if sessions else []
        vocals = _vocals_of(stems)
        if vocals is None:
            raise RuntimeError(f"分离产物里没有 (Vocals) 干声：{stems}")
        os.replace(temp / vocals, out)
        return actual
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def separate(
    src: Path,
    out: Path,
    models_dir: Path,
    *,
    device: str = "auto",
    cuda_dll_dir: Path | None = None,
) -> dict[str, object]:
    """按设备请求分离；auto 才允许 CUDA 失败后 CPU 完整重跑一次。"""
    import onnxruntime as ort

    requested = device.strip().lower()
    available = list(ort.get_available_providers())
    providers, resolved = _provider_plan(requested, available)
    reason = "" if resolved == "cuda" or requested != "auto" else (
        "onnxruntime 没有 CUDAExecutionProvider（CPU 轮）"
    )
    if resolved == "cuda":
        try:
            actual_providers = _run_attempt(src, out, models_dir, providers)
            if "CUDAExecutionProvider" not in actual_providers:
                raise RuntimeError(
                    f"CUDA session 未启用（实际 provider: {actual_providers}）"
                )
        except Exception as exc:  # noqa: BLE001 - auto 的第二次机会，原因要写进回执
            if requested != "auto":
                raise
            actual_providers = _run_attempt(src, out, models_dir, ["CPUExecutionProvider"])
            return _payload(
                out, requested, resolved, "cpu", actual_providers,
                fallback=True, reason=f"{type(exc).__name__}: {exc}",
            )
        return _payload(out, requested, resolved, "cuda", actual_providers)

    actual_providers = _run_attempt(src, out, models_dir, providers)
    return _payload(
        out, requested, resolved, "cpu", actual_providers, reason=reason,
    )


def _payload(
    out: Path,
    requested: str,
    resolved: str,
    actual: str,
    providers: list[str],
    *,
    fallback: bool = False,
    reason: str = "",
) -> dict[str, object]:
    return {
        "ok": True,
        "out": str(out),
        "requested": requested,
        "resolved": resolved,
        "actual": actual,
        "fallback": fallback,
        "reason": reason,
        "providers": providers,
    }


def probe_cuda() -> dict[str, object]:
    """极小 ONNX Add session 真跑一次：只认 session 的 providers，不看安装态。"""
    try:
        import numpy as np
        import onnxruntime as ort
        from onnx import TensorProto, helper

        available = list(ort.get_available_providers())
        if "CUDAExecutionProvider" not in available:
            return {
                "ok": False,
                "error": "onnxruntime 没有 CUDAExecutionProvider（CPU 轮）",
                "available": available,
                "version": ort.__version__,
            }
        node = helper.make_node("Add", ["a", "b"], ["c"])
        graph = helper.make_graph(
            [node], "probe",
            [
                helper.make_tensor_value_info("a", TensorProto.FLOAT, [1]),
                helper.make_tensor_value_info("b", TensorProto.FLOAT, [1]),
            ],
            [helper.make_tensor_value_info("c", TensorProto.FLOAT, [1])],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        # onnx 1.22 默认 IR 13 超出 ORT 1.18 的上限 10；探针模型显式降到 8。
        model.ir_version = 8
        session = ort.InferenceSession(
            model.SerializeToString(), providers=["CUDAExecutionProvider"]
        )
        providers = list(session.get_providers())
        if "CUDAExecutionProvider" not in providers:
            return {
                "ok": False,
                "error": f"session 未启用 CUDA（实际: {providers}）",
                "available": available,
                "version": ort.__version__,
            }
        result = session.run(
            None,
            {
                "a": np.array([2.0], dtype="float32"),
                "b": np.array([3.0], dtype="float32"),
            },
        )
        return {
            "ok": True,
            "providers": providers,
            "version": ort.__version__,
            "result": float(result[0][0]),
        }
    except Exception as exc:  # noqa: BLE001 - 安装期探针失败要带原文，不裸崩
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _vocals_of(stems: list[str]) -> str | None:
    return next((stem for stem in stems if "(Vocals)" in stem), None)


if __name__ == "__main__":
    sys.exit(main())
