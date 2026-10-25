"""本地智能运行时引导：uv 拉起独立 venv（Python 3.11 + torch + 双栈 TTS + funasr + kokoro）。

主服务（Python 3.13）与各上游的约束不可调和——运行时是数据目录下的独立
venv，由 uv 引导创建（uv 自动下载独立 CPython，用户机器零 Python 依赖）。
四族能力**共用这一个 venv**（E-2 裁决：torch 单份不重复下载，存量已装机
零迁移）：IndexTTS/CosyVoice（双栈 TTS）、funasr（本地 ASR）、kokoro（本地
TTS）。transformers 定 4.52.1（IndexTTS 的 vendored 内部 API 硬需要；CosyVoice
上游@074ca6dc 自己 pin 的 4.51.3 与之同代，跑在近原生版本上，cosyvoice_worker
的 transformers-5 适配补丁在该版本下自动跳过；kokoro 只用 AlbertConfig 稳定
API，4.x 可用——自检兜底）。产物路径：
  - engines/tts/engines/indextts2.py 探测 runtimes/tts-venv
  - engines/tts/engines/cosyvoice.py 探测同一路径
  - engines/analysis/transcriber.py 的 funasr worker 探测同一路径（E2-2）
  - engines/tts/engines/kokoro.py 的 kokoro worker 探测同一路径（E2-3）
  - CosyVoice 上游源码落 runtimes/cosyvoice-src（sys.path 引入，非 pip 包）

流程（阶段→进度）：uv.exe 下载(0-5) → venv 创建含独立 Python(5-15) →
torch(15-45, GPU 探测定 cu128/CPU 变体) → 双栈依赖(45-60) → 分析依赖组
funasr(60-66) → kokoro 依赖组(66-70) → 人声分离 ORT(70-75，装后真探测) →
源码 zip（IndexTTS + CosyVoice + Matcha-TTS + PyWorld）(75-95) → import
自检（四族各一遍）(95-100)。全程多镜像容错，可取消，可重入（已存在阶段跳过；
新增依赖组按 import 探针补装）。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tarfile
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.infra import gpu
from dramaclip.infra.model_manager import cuda_runtime
from dramaclip.infra.model_manager.fetch import download_file

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_UV_VERSION = "0.8.4"
_UV_SOURCES = [
    f"https://gh-proxy.com/https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
    f"https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-pc-windows-msvc.zip",
]
# 独立 CPython 与 PyPI 走国内镜像（uv 官方源国内不稳）
_UV_ENV = {
    "UV_PYTHON_INSTALL_MIRROR": "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download",
    "UV_HTTP_TIMEOUT": "120",
}
_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
_GH_PROXY = "https://gh-proxy.com/https://github.com"
_TORCH_XPU_INDEX = "https://download.pytorch.org/whl/xpu"
# ONNX Runtime 1.18.0 在 PyPI 的默认轮是 CUDA 11.8 构建（导入 cublas64_11/
# cudart64_110），与本机 cu12 运行库不兼容；微软官方 CUDA 12 源的同版本轮
# 导入 cublas64_12/cudart64_12/cufft64_11（2026-10-20 逐 DLL 实测）。
_ORT_VERSION = "1.18.0"
_ORT_GPU_INDEX = (
    "https://aiinfra.pkgs.visualstudio.com/PublicPackages/"
    "_packaging/onnxruntime-cuda-12/pypi/simple/"
)
_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
_TORCH_CPU = ["torch==2.8.0", "torchaudio==2.8.0"]
# 以下尺寸全部为**实测精确字节数**（2026-09-24 逐件下载量得）：download_file 的
# expected_size 是精确匹配校验（防代理截断/半包），估一个"大概 18MB"只会把完好
# 下载拒之门外——uv 首装就是这么失败的（期望 18MiB 整，实际 19103643）。
_UV_ZIP_SIZE = 19103643  # uv 0.8.4 win-msvc.zip
# 双栈依赖并集。IndexTTS 基线 17 项；CosyVoice 追加项（派生自上游
# requirements@074ca6dc 裁到合成所需，差异注释见各 pin）：
_COSYVOICE_EXTRAS = [
    "conformer==0.3.2",
    "diffusers==0.39.0",
    "hydra-core==1.3.6",
    "HyperPyYAML==1.2.3",
    "inflect==7.3.1",
    "librosa==0.10.2",
    "lightning==2.6.6",
    "matplotlib==3.7.5",
    "networkx==3.1",
    "onnx==1.22.0",
    "protobuf==5.29.6",  # onnx==1.22 要 >=4.25.1；抬升理由见上方注释（安全公告）
    "pydantic==2.7.0",
    "rich==13.7.1",
    "soundfile==0.12.1",
    "numpy==1.26.4",  # numba（IndexTTS 侧）与 librosa 共同的兼容锚点
    "x-transformers==2.11.24",
    "gdown==6.4.0",
    "wget==3.2",
    "pyarrow==25.0.1",
]
# 人声分离（参考音频清洗「彻底档」，vocal_separation.py）：MDX-Net 的 ORT
# 后端单独按 GPU/CPU 变体安装（_install_ort），不进本组以免解析器拉默认轮。
# torch/torchvision 必须在本组显式 pin——
# audio-separator 的裸 torch 依赖 + onnx2torch 的裸 torchvision 依赖会让解析器
# 把 torch 拉到 2.14（torchvision 0.29 连带），双栈全炸（2026-09-28 本机实测）。
# torchvision 取 PyPI CPU 轮即可：onnx2torch 只用它的 CPU 算子做 ONNX 图转换，
# 分离全程 onnxruntime，不依赖 torchvision 的 CUDA 内核。
_SEPARATION_EXTRAS = [
    "audio-separator==0.18.3",
    "beartype==0.18.5",
    "diffq==0.2.4",
    "julius==0.2.7",
    "ml_collections",
    "onnx2torch==1.5.15",
    "torchvision==0.23.0",
    "pydub==0.25.1",
    "resampy==0.4.3",
    "rotary-embedding-torch==0.6.5",
    "samplerate==0.1.0",
    "scipy==1.13.1",
]
# 本地 ASR（funasr，E-2 并入）：pin 与 dev 主 venv 实装一致（1.4.16 实测）。
# fbank 后端用 kaldi-native-fbank（funasr 1.4 缺 fbank 实现时报 "torchaudio is
# not installed"——torchaudio 与 torch 强耦合难装，knf 是无 torch 依赖的独立
# C++ 实现，同 pyproject ml 组的既定取舍）。其余推理期依赖（librosa/soundfile/
# scipy/pyyaml/modelscope/jieba）已被双栈组覆盖，不重复 pin。
_ANALYSIS_EXTRAS = [
    "funasr==1.4.16",
    "kaldi-native-fbank==1.22.3",
    "kaldiio==2.18.1",
    "jaconv==0.5.0",
    "opencc-python-reimplemented==0.1.7",
]
# 本地 TTS（kokoro，E-2 并入）：kokoro 包顶层 import torch+transformers，只能
# 在本 venv 执行。misaki 取 [zh] extra（中文 g2p：jieba+pypinyin+num2words，
# 解析器自取）；espeak-ng 不需要（zh 路径不走 espeak）。transformers 沿用双栈
# 组的 4.52.1 pin——kokoro 只用 AlbertConfig 稳定 API，兼容性由尾部自检把守。
_KOKORO_EXTRAS = [
    "kokoro==0.9.4",
    "misaki[zh]==0.9.4",
]
# openai-whisper 20231117 在构建期需要 pkg_resources（已废）：20250625 是
# Windows 实测可构建版（CosyVoice 只用它的 mel 前端）。
# main 分支是移动目标：zip 字节数随上游推送变化，精确校验必碎——钉 commit。
_INDEXTTS_REV = "ee40fa7d6c6b8a2c7f06105f9f1e65775b74868c"
_INDEXTTS_SOURCES = [
    f"https://gh-proxy.com/https://github.com/index-tts/index-tts/archive/{_INDEXTTS_REV}.zip",
    f"https://github.com/index-tts/index-tts/archive/{_INDEXTTS_REV}.zip",
]
_INDEXTTS_ZIP_SIZE = 35993020
_COSYVOICE_ZIP_SIZE = 1633232
_MATCHA_TGZ_SIZE = 484695
_PYWORLD_TGZ_SIZE = 46981
_WORLD_TGZ_SIZE = 111098
#: CosyVoice 上游固定 revision（本机 Windows 实测组合所用）。
_COSYVOICE_REV = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
_MATCHA_REV = "dd9105b34bf2be2230f4aa1e4769fb586a3c824e"
_PYWORLD_REV = "f31ad88d543fdaebbda2d0c9a5e4d4f991ae0b6c"
_WORLD_REV = "d625e7608ca23a870018f01e7c562ac683d9847f"
# PyPI 轮子不带 WORLD 子模块 → 源码构建，需要 C++ 编译器（缺编译器的报错在
# 安装日志里很明显，装 VS Build Tools 后重跑本安装即可续）。
_PYWORLD_SOURCES = [
    f"{_GH_PROXY}/JeremyCCHsu/Python-Wrapper-for-World-Vocoder/archive/{_PYWORLD_REV}.tar.gz",
    f"https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder/archive/{_PYWORLD_REV}.tar.gz",
]
_WORLD_SOURCES = [
    f"{_GH_PROXY}/mmorise/World/archive/{_WORLD_REV}.tar.gz",
    f"https://github.com/mmorise/World/archive/{_WORLD_REV}.tar.gz",
]
_MATCHA_SOURCES = [
    f"{_GH_PROXY}/shivammehta25/Matcha-TTS/archive/{_MATCHA_REV}.tar.gz",
    f"https://github.com/shivammehta25/Matcha-TTS/archive/{_MATCHA_REV}.tar.gz",
]
_COSYVOICE_SOURCES = [
    f"{_GH_PROXY}/FunAudioLLM/CosyVoice/archive/{_COSYVOICE_REV}.zip",
    f"https://github.com/FunAudioLLM/CosyVoice/archive/{_COSYVOICE_REV}.zip",
]


def _gpu_variant() -> str:
    """cuda / xpu / cpu：N 卡算力 ≥7.0 走 cu128；Intel Arc/Ultra 级适配器走 xpu 轮；其余 CPU。

    老卡（<7.0，Maxwell/Pascal）的 cu126 兼容轮已实测否决（2026-10-16）：
    torch 2.8.0+cu126 在 Quadro M4000（sm_52）装得上、算子无内核——
    「Torch not compiled with CUDA enabled」，官方 2.8 起 CUDA 内核最低
    算力线即 7.0（早前验证 sm_52 可用的是 2.14+cu126，版本与变体是两个
    维度）。老卡走 CPU 轮，CUDA 可用性由合成探针如实回退。

    xpu 判据（2026-10-25）：vendor intel（D3D PCI ID 优先）+ 适配器名含
    Arc/Ultra（Meteor Lake+ 核显与 Arc 独显的命名特征；老 Gen9.5 核显无
    XPU 后端不入）。最终裁决在 worker 的 torch.xpu 真算探针——装错轮的
    代价是一次 CPU 回退与如实 reason。
    """
    raw_adapters = gpu.snapshot_sync().get("adapters") or []
    adapters = (
        [a for a in raw_adapters if isinstance(a, dict)] if isinstance(raw_adapters, list) else []
    )
    if _intel_xpu_capable(adapters):
        print("[tts-runtime] Intel Arc/Ultra 适配器在场：装 torch XPU 轮")
        return "xpu"
    if shutil.which("nvidia-smi") is None:
        return "cpu"
    probe = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW, check=False,
    )
    lines = probe.stdout.strip().splitlines() if probe.returncode == 0 else []
    raw = lines[0].strip() if lines else ""
    cap = raw if raw else ""
    try:
        major = float(cap.split()[0]) if cap else -1.0
    except ValueError:
        return "cuda"  # 算力读不出来：保守装 CUDA 轮，合成探针诚实回退
    if major < 0.0:
        return "cuda"  # nvidia-smi 空输出同理：信息缺失不等于没有 CUDA
    if major < 7.0:
        print(f"[tts-runtime] N 卡算力 {cap} 低于 cu128 支持线（7.0）：装 CPU 轮")
        return "cpu"
    return "cuda"


def _intel_xpu_capable(adapters: list[dict[str, object]] | None) -> bool:
    """Intel 主机且存在 Arc/Ultra 级适配器（XPU 轮的目标硬件）。"""
    for adapter in adapters or []:
        if not isinstance(adapter, dict):
            continue
        if adapter.get("is_virtual") or adapter.get("is_software"):
            continue
        vendor = str(adapter.get("vendor") or "")
        vendor_id = str(adapter.get("vendor_id") or "")
        if vendor != "intel" and vendor_id != "0x8086":
            continue
        name_l = str(adapter.get("name") or "").lower()
        if "arc" in name_l or "ultra" in name_l:
            return True
    return False


def venv_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "tts-venv"


def venv_python(data_dir: Path) -> Path:
    return venv_dir(data_dir) / "Scripts" / "python.exe"


def analysis_ready(data_dir: Path) -> bool:
    """funasr 组的零探针安装判据：venv 解释器 + funasr 包目录在场（纯文件检查）。

    status() 的分组探针要跑子进程，models.list / 引擎清单是高频端点用不起；与
    变体标记同一哲学——文件在场≈装好，真坏了由 worker 启动失败如实报错引导重装。
    """
    venv = venv_dir(data_dir)
    if not venv_python(data_dir).is_file():
        return False
    return (venv / "Lib" / "site-packages" / "funasr" / "__init__.py").is_file()


def cosyvoice_src_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "cosyvoice-src"


def _variant_marker(data_dir: Path) -> Path:
    return venv_dir(data_dir).parent / "tts-venv.torch-variant"


def torch_variant(data_dir: Path) -> str:
    """venv 里 torch 的变体：cuda / cpu / unknown（未装或旧版安装无标记）。

    安装完成时写标记文件（零探针成本——status 是 health 高频端点，不能跑子进程）；
    判定不允许只看文件在不在：torch 装了但 CUDA 初始化失败的情形由合成 worker
    的运行时探针诚实回退，这里的变体只是「装的时候选了哪条轮子」。
    """
    marker = _variant_marker(data_dir)
    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    # 认不得的值（磁盘损坏/手改）如实 unknown，不冒充 cpu。
    return raw if raw in ("cuda", "cpu", "xpu") else "unknown"


def _ort_marker(data_dir: Path) -> Path:
    return venv_dir(data_dir).parent / "tts-venv.ort.json"


def ort_state(data_dir: Path) -> dict[str, Any]:
    """人声分离 ORT 后端：variant gpu / cpu / unknown + backend cuda / dml / cpu。

    marker 只记录「装的时候探测到了什么」；实际任务以 worker 回执为准。
    """
    empty = {
        "variant": "unknown", "gpu": False, "backend": "cpu",
        "providers": [], "version": "", "reason": "",
    }
    try:
        data = json.loads(_ort_marker(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    variant = data.get("variant")
    if variant not in ("gpu", "cpu"):
        return empty
    providers = data.get("providers")
    # 旧 marker 没有 backend：gpu 一律按当时唯一的 GPU 通道 cuda 读。
    backend = str(data.get("backend") or ("cuda" if variant == "gpu" else "cpu"))
    return {
        "variant": variant,
        "gpu": variant == "gpu",
        "backend": backend if backend in ("cuda", "dml", "cpu") else "cpu",
        "providers": [str(p) for p in providers] if isinstance(providers, list) else [],
        "version": str(data.get("version") or ""),
        "reason": str(data.get("reason") or ""),
    }


def _write_ort_marker(data_dir: Path, **fields: Any) -> None:
    marker = _ort_marker(data_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"variant": "cpu", "providers": [], "version": "", "reason": "", **fields},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def _ort_install_plan(
    *,
    nvidia_present: bool,
    cuda_runtime_installed: bool,
    amd_intel_present: bool,
) -> str:
    """分离 ORT 变体三选一：NVIDIA（+运行库）=CUDA EP，AMD/Intel=DML EP，其余 CPU。

    GPU 的条件是硬件 + 运行库，与本 venv 的 torch 变体无关（老卡也能跑 CUDA EP）。
    N 卡且运行库齐装 CUDA 轮；运行库缺而 AMD/Intel 在场，DML 是真可用的次选
    （回执如实标 dml，冒充红线只在显式 cuda 请求处）。
    """
    if nvidia_present and cuda_runtime_installed:
        return "cuda"
    if amd_intel_present:
        return "dml"
    return "cpu"


def _probe_ort_gpu(py: Path, data_dir: Path) -> dict[str, Any]:
    """在 tts-venv 里跑 worker 的最小 CUDA session；只认 session 的 provider。"""
    args = ["--probe", "--cuda-dll-dir", str(cuda_runtime.runtime_dir(data_dir))]
    return _run_ort_probe(py, args)


def _probe_ort_dml(py: Path) -> dict[str, Any]:
    """在 tts-venv 里跑 worker 的最小 DirectML session；DML 不需要 CUDA DLL。"""
    return _run_ort_probe(py, ["--probe-dml"])


def _run_ort_probe(py: Path, worker_args: list[str]) -> dict[str, Any]:
    from dramaclip.engines.tts.workers import separation_worker

    try:
        result = subprocess.run(  # noqa: S603 - 固定解释器固定参数
            [str(py), str(Path(separation_worker.__file__)), *worker_args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, creationflags=_NO_WINDOW, check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "error": "探针没有返回协议应答"}
    try:
        payload = json.loads(lines[-1])
    except ValueError:
        return {"ok": False, "error": "探针应答不是 JSON"}
    return payload if isinstance(payload, dict) else {"ok": False, "error": "探针应答形状不对"}


def _install_ort(
    uv: Path,
    venv: Path,
    data_dir: Path,
    *,
    check_cancel: Callable[[], None],
    progress: Callable[[float, str], None],
) -> None:
    """按变体安装 ONNX Runtime（cuda / dml / cpu 三选一）；GPU 探测失败回装 CPU 轮，
    绝不把安装态当可用态。"""
    py = venv / "Scripts" / "python.exe"
    adapters = gpu.snapshot_sync().get("adapters") or []
    cards = adapters if isinstance(adapters, list) else []
    vendors = {str(card.get("vendor") or "") for card in cards}
    # CIM 适配器枚举拿不到时退 nvidia-smi 在场判定：宁可装 CUDA 轮再探针裁决，
    # 也不把「探测失败」当成「没有卡」装成 CPU（真机 2026-10-21 实证过这条坑）。
    nvidia_present = "nvidia" in vendors or shutil.which("nvidia-smi") is not None
    amd_intel_present = bool(vendors & {"amd", "intel"})
    runtime_installed = cuda_runtime.status(data_dir)["installed"]
    want = _ort_install_plan(
        nvidia_present=nvidia_present,
        cuda_runtime_installed=runtime_installed,
        amd_intel_present=amd_intel_present,
    )
    current = ort_state(data_dir)
    if want == "cpu" and current["variant"] == "cpu" and _venv_imports_ok(py, ("onnxruntime",)):
        return
    if want == "cuda" and current["backend"] == "cuda" and current["gpu"] \
            and _probe_ort_gpu(py, data_dir).get("ok"):
        return
    if want == "dml" and current["backend"] == "dml" and current["gpu"] \
            and _probe_ort_dml(py).get("ok"):
        return

    check_cancel()
    progress(70, "配置人声分离运行后端（ONNX Runtime）")
    # 三个变体互斥，不能同时留在 site-packages 里。
    _run_uv(uv, venv, "pip", "uninstall", "onnxruntime", "onnxruntime-gpu", "onnxruntime-directml")

    if want == "cuda":
        try:
            _run_uv(uv, venv, "pip", "install", "--no-deps",
                    f"onnxruntime-gpu=={_ORT_VERSION}", "--index-url", _ORT_GPU_INDEX)
            probe = _probe_ort_gpu(py, data_dir)
            if probe.get("ok"):
                _write_ort_marker(
                    data_dir, variant="gpu", backend="cuda",
                    providers=probe.get("providers") or [],
                    version=str(probe.get("version") or _ORT_VERSION),
                )
                return
            reason = f"分离 GPU 不可用：{probe.get('error') or 'CUDA session 探测失败'}"
        except RuntimeError as exc:
            reason = f"分离 GPU 不可用：{exc}"
        check_cancel()
        with contextlib.suppress(RuntimeError):
            _run_uv(uv, venv, "pip", "uninstall", "onnxruntime", "onnxruntime-gpu")
    elif want == "dml":
        try:
            _run_uv(uv, venv, "pip", "install", f"onnxruntime-directml=={_ORT_VERSION}",
                    "--index-url", _PYPI_MIRROR)
            probe = _probe_ort_dml(py)
            if probe.get("ok"):
                _write_ort_marker(
                    data_dir, variant="gpu", backend="dml",
                    providers=probe.get("providers") or [],
                    version=str(probe.get("version") or _ORT_VERSION),
                )
                return
            reason = f"分离 DirectML 不可用：{probe.get('error') or 'DML session 探测失败'}"
        except RuntimeError as exc:
            reason = f"分离 DirectML 不可用：{exc}"
        check_cancel()
        with contextlib.suppress(RuntimeError):
            _run_uv(uv, venv, "pip", "uninstall", "onnxruntime", "onnxruntime-directml")
    else:
        reason = (
            "未检测到可加速的显卡（分离走 CPU）"
            if not nvidia_present and not amd_intel_present
            else "CUDA 运行库未安装（安装后可重跑本地运行环境以启用 GPU 分离）"
        )

    try:
        _run_uv(uv, venv, "pip", "install", f"onnxruntime=={_ORT_VERSION}",
                "--index-url", _PYPI_MIRROR)
    except RuntimeError as exc:
        # 主链不依赖 ORT：CPU 轮也装不上时只让分离不可用，不拖垮整个运行环境。
        _write_ort_marker(data_dir, variant="cpu", reason=f"{reason}；CPU 轮安装失败：{exc}")
        return
    _write_ort_marker(data_dir, variant="cpu", reason=reason)


def status(data_dir: Path) -> dict[str, Any]:
    """venv 安装态：installed = 双栈 TTS 基线（indextts+torch）通过；groups 按能力分族。

    目录在但坏=未装完，可重装修复。groups 是 E-2 扩容后的按族探针（一次子进程
    逐个 __import__ 记成败）：indextts 需源码路径引入，funasr/kokoro 是纯 pip 组。
    installed 维持旧口径（双栈 TTS）——前端既有判据零改动，新消费者读 groups。
    """

    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        return {
            "installed": False,
            "dir": str(venv),
            "torch_variant": "unknown",
            "groups": {},
            "ort_gpu": ort_state(data_dir),
        }
    src = data_dir / "runtimes" / "indextts-src"
    probe_code = (
        "import json, sys\n"
        f"sys.path.insert(0, r'{src}')\n"
        "groups = {}\n"
        "for name in ('indextts', 'funasr', 'kokoro'):\n"
        "    try:\n"
        "        __import__(name)\n"
        "        groups[name] = True\n"
        "    except Exception:\n"
        "        groups[name] = False\n"
        "try:\n"
        "    import torch\n"
        "    groups['torch'] = True\n"
        "except Exception:\n"
        "    groups['torch'] = False\n"
        "print(json.dumps(groups))"
    )
    try:
        probe = subprocess.run(  # noqa: S603 - 固定解释器固定参数
            [str(py), "-c", probe_code],
            capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW, check=False,
        )
        groups: dict[str, bool] = {}
        if probe.returncode == 0:
            try:
                groups = {k: bool(v) for k, v in json.loads(probe.stdout).items()}
            except ValueError:
                groups = {}
        return {
            "installed": bool(groups.get("indextts") and groups.get("torch")),
            "dir": str(venv),
            "torch_variant": torch_variant(data_dir),
            "groups": groups,
            "ort_gpu": ort_state(data_dir),
        }
    except (OSError, subprocess.TimeoutExpired):
        return {
            "installed": False,
            "dir": str(venv),
            "torch_variant": "unknown",
            "groups": {},
            "ort_gpu": ort_state(data_dir),
        }


def _venv_imports_ok(py: Path, modules: tuple[str, ...]) -> bool:
    """venv 解释器内逐个 import 全过才真：依赖组的可重入跳过判据。

    不能用标记文件——存量已装 venv 没有新依赖组，标记会说谎；import 是唯一真相。
    只在 install 流程里调用（单次秒到十秒级），不进 status 高频端点。
    """
    probe = subprocess.run(  # noqa: S603 - 固定解释器固定参数
        [str(py), "-c", "; ".join(f"import {m}" for m in modules)],
        capture_output=True, timeout=120, creationflags=_NO_WINDOW, check=False,
    )
    return probe.returncode == 0


def install(
    data_dir: Path,
    *,
    cancel: threading.Event,
    on_progress: Any | None = None,
) -> None:
    def _pct(value: float, stage: str) -> None:
        if on_progress is not None:
            on_progress(value, stage)

    def _check_cancel() -> None:
        if cancel.is_set():
            raise RuntimeError("已取消")

    runtimes = data_dir / "runtimes"
    runtimes.mkdir(parents=True, exist_ok=True)

    # ① uv.exe（~17MB 单文件；已存在跳过）
    uv = runtimes / "uv.exe"
    if not uv.is_file():
        _pct(2, "下载 uv 引导器")
        _fetch_first(_UV_SOURCES, runtimes / "uv.zip", _UV_ZIP_SIZE, cancel)
        with zipfile.ZipFile(runtimes / "uv.zip") as zf:
            for item in zf.namelist():
                if item.endswith("uv.exe"):
                    uv.write_bytes(zf.read(item))
                    break
        (runtimes / "uv.zip").unlink(missing_ok=True)
        if not uv.is_file():
            raise RuntimeError("uv.exe 解包失败")
    _check_cancel()

    # ② venv + 独立 Python 3.11（uv 自动下载，国内镜像）
    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        _pct(8, "创建 Python 3.11 运行环境（首次含解释器下载）")
        _run_uv(uv, venv, "venv", str(venv), "--python", "3.11")
    _check_cancel()

    # ③ torch：N 卡且算力 ≥7.0 走 cu128（GPU 大版），否则 CPU 轮（省 4GB）。
    # 判据不能是 venv 里的 import torch——此时 torch 还没装，探针永远假阴性；
    # 也不能只看 nvidia-smi 在场——老卡（如 Pascal 5.2）在 cu128 里没有内核，
    # 装 GPU 轮是白下 2.5GB，CUDA 是否真能用再由 worker 合成时的探针诚实回退。
    variant = _gpu_variant()
    variant_label = {"cuda": "CUDA 12.8", "xpu": "Intel XPU"}.get(variant, "CPU")
    _pct(18, f"安装 torch（{variant_label} 变体，约 0.2-2.5GB）")
    _install_torch(uv, venv, variant)
    _check_cancel()

    # ④ 双栈其余依赖（清华镜像；transformers 定 4.52.1 = IndexTTS 硬需要 +
    #    CosyVoice 上游同代版本，见模块头）。无条件重跑：pin 收敛即修复语义，
    #    解析器对已满足的 pin 是快速空转。
    _pct(45, "安装双栈推理依赖（transformers 4.52 等 58 项）")
    # descript-audiotools 的教训（2026-09-29 真机实证）：它不是「上游搭车依赖」——
    # indextts/s2mel/dac 有 4 处真实 import，剔除后 IndexTTS worker 必死在
    # ModuleNotFoundError。但它的 protobuf<3.20 陈年 pin 与 onnx>=4.25 死锁是真，
    # 所以必须 --no-deps 单独装（只取包本体），import 链上真正缺的 9 个子依赖
    # 走常规批次（都是无恩怨的纯工具包）。
    _run_uv(uv, venv, "pip", "install",
            "transformers==4.52.1", "omegaconf", "accelerate", "munch", "einops",
            "json5", "wetext", "cn2an", "jieba", "numba",
            "openai-whisper==20250625", "sentencepiece", "fugashi", "unidic-lite",
            "g2p-en", "modelscope==1.27.0",
            "flatten-dict", "pysbd", "decorator", "ffmpy", "importlib-resources",
            "tensorboard", "randomname", "argbind", "docstring-parser",
            *_COSYVOICE_EXTRAS, *_SEPARATION_EXTRAS, "--index-url", _PYPI_MIRROR)
    _check_cancel()
    _run_uv(uv, venv, "pip", "install", "--no-deps", "descript-audiotools==0.7.2",
            "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ④b/④c 分析与 kokoro 依赖组（E-2 并入：与双栈共用本 venv 的 torch，单份不重复
    # 下载）。跳过判据是 import 探针不是标记——存量已装 venv 没有新组，标记会说谎；
    # 探针只在 install 流程跑（秒到十秒级），不进 status 高频端点。
    if not _venv_imports_ok(py, ("funasr",)):
        _pct(60, "安装分析依赖组（funasr，本地 ASR）")
        _run_uv(uv, venv, "pip", "install", *_ANALYSIS_EXTRAS, "--index-url", _PYPI_MIRROR)
    _check_cancel()
    if not _venv_imports_ok(py, ("kokoro",)):
        _pct(66, "安装 kokoro 依赖组（本地 TTS）")
        _run_uv(uv, venv, "pip", "install", *_KOKORO_EXTRAS, "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ④d 人声分离 ORT：N 卡 + CUDA 运行库才装 GPU 轮，装完立刻真建 session 探测；
    # 探测失败回 CPU 轮并留原因——GPU 安装态不等于 GPU 可用。
    _install_ort(uv, venv, data_dir, check_cancel=_check_cancel, progress=_pct)
    _check_cancel()

    # ⑤ 源码：IndexTTS zip（--no-deps 可编辑装）+ CosyVoice/Matcha/PyWorld
    # （CosyVoice 非 pip 包：解包落位，由 worker 经 sys.path + 环境变量引入）
    src_root = runtimes / "indextts-src"
    if not (src_root / "pyproject.toml").is_file():
        _pct(75, "获取 IndexTTS 源码")
        _fetch_first(_INDEXTTS_SOURCES, runtimes / "indextts-src.zip", _INDEXTTS_ZIP_SIZE, cancel)
        # 与 CosyVoice 同一条解包路：裸 extractall 不校验成员名，归档里一个 ../ 就写到
        # runtimes 外面；剥一层前缀的做法也顺手替掉 move + rmtree 的临时目录
        _extract_zip_stripped(runtimes / "indextts-src.zip", src_root)
        (runtimes / "indextts-src.zip").unlink(missing_ok=True)
    # IndexTTS 上游 pyproject 用了 uv 专属 TOML 扩展写 optional-deps（PEP 517 解析
    # 直接拒），不走 pip——与 CosyVoice 同构：源码落位，运行时经 sys.path 引入
    #（engines/tts/workers/indextts_worker.py 自举）。
    _check_cancel()

    cv_src = cosyvoice_src_dir(data_dir)
    if not (cv_src / "cosyvoice" / "cli" / "cosyvoice.py").is_file():
        _pct(84, "获取 CosyVoice 源码（固定 revision）")
        _fetch_first(
            _COSYVOICE_SOURCES, runtimes / "cosyvoice-src.zip", _COSYVOICE_ZIP_SIZE, cancel,
        )
        _extract_zip_stripped(runtimes / "cosyvoice-src.zip", cv_src)
        (runtimes / "cosyvoice-src.zip").unlink(missing_ok=True)
    _check_cancel()

    matcha = cv_src / "third_party" / "Matcha-TTS"
    if not (matcha / "matcha" / "__init__.py").is_file():
        _pct(87, "获取 Matcha-TTS 子模块")
        _fetch_first(_MATCHA_SOURCES, runtimes / "matcha.tar.gz", _MATCHA_TGZ_SIZE, cancel)
        _extract_tar_stripped(runtimes / "matcha.tar.gz", matcha)
        (runtimes / "matcha.tar.gz").unlink(missing_ok=True)
    _check_cancel()

    pyworld = cv_src / "third_party" / "PyWorld"
    if not (pyworld / "pyworld" / "__init__.py").is_file():
        _pct(89, "获取 PyWorld 源码（含 WORLD 声码器子模块）")
        _fetch_first(_PYWORLD_SOURCES, runtimes / "pyworld.tar.gz", _PYWORLD_TGZ_SIZE, cancel)
        _extract_tar_stripped(runtimes / "pyworld.tar.gz", pyworld)
        (runtimes / "pyworld.tar.gz").unlink(missing_ok=True)
    if not (pyworld / "lib" / "World" / "src" / "dio.cpp").is_file():
        _fetch_first(_WORLD_SOURCES, runtimes / "world.tar.gz", _WORLD_TGZ_SIZE, cancel)
        _extract_tar_stripped(runtimes / "world.tar.gz", pyworld / "lib" / "World")
        (runtimes / "world.tar.gz").unlink(missing_ok=True)
    _check_cancel()

    if not (pyworld / "pyworld" / "__init__.py").is_file():
        raise RuntimeError("PyWorld 源码不完整，无法构建")
    _pct(91, "构建安装 PyWorld（源码编译，需 C++ 编译器）")
    _run_uv(uv, venv, "pip", "install", "--no-deps", str(pyworld))
    _check_cancel()

    # ⑥ 自检：四族各一遍（CosyVoice 走 worker --check，含 sys.path 引导）
    _pct(96, "自检（首次 import 较慢）")
    if not status(data_dir)["installed"]:
        raise RuntimeError("自检失败：venv 已建但 indextts 导入异常，可重试修复")
    from dramaclip.engines.tts.workers import cosyvoice_worker

    worker_src = Path(cosyvoice_worker.__file__)
    cv_check = subprocess.run(  # noqa: S603 - 固定解释器固定参数
        [str(py), str(worker_src), "--check"],
        capture_output=True, text=True, timeout=300,
        creationflags=_NO_WINDOW, check=False,
        env={**os.environ, "DRAMACLIP_COSYVOICE_SRC": str(cv_src)},
    )
    if cv_check.returncode != 0:
        raise RuntimeError("自检失败：cosyvoice 导入异常，可重试修复")
    if not _venv_imports_ok(py, ("funasr",)):
        raise RuntimeError("自检失败：funasr 导入异常（本地 ASR），可重试修复")
    if not _venv_imports_ok(py, ("kokoro",)):
        raise RuntimeError("自检失败：kokoro 导入异常（本地 TTS），可重试修复")
    _variant_marker(data_dir).write_text(variant, encoding="utf-8")
    _pct(100, "完成")


def _member_parts(name: str) -> tuple[str, ...]:
    """归档成员名的形状闸：绝对路径、盘符、``..`` 逃逸一律当场报错，其余返回规范化路径段。

    解包的是第三方镜像拉下来的仓库归档，成员名属于外部输入：一条 ``repo-x/../../evil``
    就能把文件写到 runtimes 之外，而装运行环境这步正握着用户目录的写权限。
    宁可报错也不悄悄跳过——跳过只会得到一棵缺文件的源码树，然后在 pip 构建那步
    抛一句看不出根因的错误。
    """
    parts = tuple(p for p in name.replace("\\", "/").split("/") if p not in ("", "."))
    if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":") or not parts:
        raise RuntimeError(f"归档成员是绝对路径，拒绝解包：{name!r}")
    if ".." in parts:
        raise RuntimeError(f"归档成员路径逃逸目标目录，拒绝解包：{name!r}")
    return parts


def _extract_zip_stripped(archive: Path, dest: Path) -> None:
    """GitHub zip 有一层 <repo>-<rev>/ 前缀，剥掉后落 dest。"""
    with zipfile.ZipFile(archive) as zf:
        prefix = zf.namelist()[0].split("/")[0]
        for member in zf.infolist():
            _member_parts(member.filename)  # 原始名先过闸：绝对成员剥完前缀看着就"听话"了
            name = member.filename.removeprefix(prefix + "/")
            if not name:
                continue
            target = dest.joinpath(*_member_parts(name))
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))


def _extract_tar_stripped(archive: Path, dest: Path) -> None:
    """GitHub /archive/<sha>.tar.gz 有一层 <repo>-<sha>/ 前缀，剥掉后落 dest。

    不走 ``tar.extract``：它按成员类型建符号链接/硬链接/设备节点，而链接本身就是
    第二条逃逸通道（先落一个 ``a -> /``，再写 ``a/etc/...`` 就出圈了）。这里只认
    目录与常规文件。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        strip = members[0].name.split("/")[0]
        for member in members:
            _member_parts(member.name)
            name = member.name.removeprefix(strip + "/")
            if not name:
                continue
            target = dest.joinpath(*_member_parts(name))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                handle = tar.extractfile(member)
                if handle is None:
                    raise RuntimeError(f"归档成员读不出来：{member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(handle.read())
            else:
                raise RuntimeError(
                    f"归档里有非常规成员（{member.type!r}），拒绝解包：{member.name}"
                )


def _install_torch(uv: Path, venv: Path, variant: str) -> None:
    """torch 按变体安装：官方 cu 源优先，失败回落阿里 pytorch-wheels flat 镜像。

    download.pytorch.org 在部分国内网络直连握手失败（2026-10-15 本机实测 SSL
    握手失败），GPU 轮 2.5GB 没有二次机会就是安装流程最大的单点。阿里镜像
    的 flat 目录做 --find-links（torch==2.8.0 匹配 +cuNNN local version，
    pip/uv 语义），其余传递依赖仍走清华。
    """
    if variant == "xpu":
        # XPU 轮自包含（索引自带 intel-cmplr-lib-rt/intel-openmp 运行时依赖）；
        # 与 cuda 轮互斥语义同源：变体是安装期决策，运行期探针如实回退 CPU。
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _TORCH_XPU_INDEX)
        return
    if variant == "cpu":
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _PYPI_MIRROR)
        return
    index = _TORCH_INDEX
    mirror_dir = "https://mirrors.aliyun.com/pytorch-wheels/cu128/"
    attempts: list[tuple[str, list[str]]] = [
        ("官方 cu 源", ["pip", "install", *_TORCH_CPU, "--index-url", index]),
        (
            "阿里镜像",
            [
                "pip", "install", *_TORCH_CPU,
                "--find-links", mirror_dir, "--index-url", _PYPI_MIRROR,
            ],
        ),
    ]
    last: Exception | None = None
    for label, args in attempts:
        try:
            _run_uv(uv, venv, *args)
            return
        except RuntimeError as exc:
            last = exc
            print(f"[tts-runtime] torch {variant} 轮 {label} 失败，尝试下一来源")
    raise RuntimeError(f"torch {variant} 轮全部来源失败: {last}")


def _run_uv(uv: Path, venv: Path, *args: str) -> None:
    cmd = [str(uv), *args]
    env = {**os.environ, **_UV_ENV}
    if args and args[0] == "pip":
        # --python 必须落在子命令之后：uv 0.8.4 的 `pip` 组不接受组级 --python
        py = str(venv / "Scripts" / "python.exe")
        cmd = [str(uv), "pip", *args[1:2], "--python", py, *args[2:]]
    result = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        cmd, capture_output=True, text=True, timeout=3600,
        creationflags=_NO_WINDOW, env=env, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv {' '.join(args[:2])} 失败: {result.stderr[-300:]}")


def _fetch_first(sources: list[str], target: Path, size: int, cancel: threading.Event) -> None:
    last: Exception | None = None
    for url in sources:
        if cancel.is_set():
            raise RuntimeError("已取消")
        try:
            download_file(url, target, size, cancel=cancel)
            return
        except Exception as exc:  # noqa: BLE001 - 多源容错
            last = exc
    raise RuntimeError(f"全部源下载失败: {last}") from last
