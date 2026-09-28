"""TTS 共享运行时引导：uv 拉起独立 venv（Python 3.11 + torch + IndexTTS/CosyVoice 双栈）。

主服务（Python 3.13）与两个上游的约束不可调和——运行时是数据目录下的独立
venv，由 uv 引导创建（uv 自动下载独立 CPython，用户机器零 Python 依赖）。
IndexTTS 与 CosyVoice **共用这一个 venv**：两边都能吃 Python 3.11 + torch
2.8.0；transformers 定 4.52.1（IndexTTS 的 vendored 内部 API 硬需要；CosyVoice
上游@074ca6dc 自己 pin 的 4.51.3 与之同代，跑在近原生版本上，cosyvoice_worker
的 transformers-5 适配补丁在该版本下自动跳过）。产物路径：
  - engens/tts/engines/indextts2.py 探测 runtimes/tts-venv
  - engines/tts/engines/cosyvoice.py 探测同一路径
  - CosyVoice 上游源码落 runtimes/cosyvoice-src（sys.path 引入，非 pip 包）

流程（阶段→进度）：uv.exe 下载(0-5) → venv 创建含独立 Python(5-15) →
torch(15-50, GPU 探测定 cu128/CPU 变体) → 双栈依赖(50-75) → 源码 zip
（IndexTTS + CosyVoice + Matcha-TTS + PyWorld）(75-95) → import 自检
（两栈各一遍）(95-100)。全程多镜像容错，可取消，可重入（已存在阶段跳过）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import threading
import zipfile
from pathlib import Path
from typing import Any

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
    "onnxruntime==1.18.0",
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
# 人声分离（参考音频清洗「彻底档」，vocal_separation.py）：MDX-Net 走
# onnxruntime 纯 CPU，不碰 GPU 栈。torch/torchvision 必须在本组显式 pin——
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
    """cuda / cpu：N 卡在场且算力 ≥7.0 才值得装 cu128 轮。"""
    if shutil.which("nvidia-smi") is None:
        return "cpu"
    probe = subprocess.run(  # noqa: S603 - 固定二进制受控参数
        ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW, check=False,
    )
    raw = probe.stdout.strip().splitlines()[0].strip() if probe.returncode == 0 else ""
    cap = raw if raw else ""
    try:
        if cap and float(cap.split()[0]) < 7.0:
            print(f"[tts-runtime] N 卡算力 {cap} 低于 cu128 支持线（7.0）：装 CPU 轮")
            return "cpu"
        return "cuda"
    except ValueError:
        return "cuda"


def venv_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "tts-venv"


def cosyvoice_src_dir(data_dir: Path) -> Path:
    return data_dir / "runtimes" / "cosyvoice-src"


def status(data_dir: Path) -> dict[str, Any]:
    """installed = venv 存在且双栈 import 自检通过（目录在但坏=未装完，可重装修复）。"""

    venv = venv_dir(data_dir)
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        return {"installed": False, "dir": str(venv)}
    src = data_dir / "runtimes" / "indextts-src"
    probe_code = (
        f"import sys; sys.path.insert(0, r'{src}'); import indextts, torch"
    )
    try:
        probe = subprocess.run(  # noqa: S603 - 固定解释器固定参数
            [str(py), "-c", probe_code],
            capture_output=True, timeout=90, creationflags=_NO_WINDOW, check=False,
        )
        return {"installed": probe.returncode == 0, "dir": str(venv)}
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False, "dir": str(venv)}


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
    gpu_ok = _gpu_variant() == "cuda"
    _pct(18, f"安装 torch（{'CUDA 12.8 变体' if gpu_ok else 'CPU 变体'}，约 0.2-2.5GB）")
    if gpu_ok:
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _TORCH_INDEX)
    else:
        _run_uv(uv, venv, "pip", "install", *_TORCH_CPU, "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ④ 双栈其余依赖（清华镜像；transformers 定 4.52.1 = IndexTTS 硬需要 +
    #    CosyVoice 上游同代版本，见模块头）
    _pct(50, "安装双栈推理依赖（transformers 4.52 等 49 项）")
    # descript-audiotools（上游搭车依赖）已剔除：index-tts 全源码零 import
    # （grep 实证），其 protobuf<3.20 陈年 pin 还与 onnx>=4.25 死锁。
    _run_uv(uv, venv, "pip", "install",
            "transformers==4.52.1", "omegaconf", "accelerate", "munch", "einops",
            "json5", "wetext", "cn2an", "jieba", "numba",
            "openai-whisper==20250625", "sentencepiece", "fugashi", "unidic-lite",
            "g2p-en", "modelscope==1.27.0",
            *_COSYVOICE_EXTRAS, *_SEPARATION_EXTRAS, "--index-url", _PYPI_MIRROR)
    _check_cancel()

    # ⑤ 源码：IndexTTS zip（--no-deps 可编辑装）+ CosyVoice/Matcha/PyWorld
    # （CosyVoice 非 pip 包：解包落位，由 worker 经 sys.path + 环境变量引入）
    src_root = runtimes / "indextts-src"
    if not (src_root / "pyproject.toml").is_file():
        _pct(72, "获取 IndexTTS 源码")
        _fetch_first(_INDEXTTS_SOURCES, runtimes / "indextts-src.zip", _INDEXTTS_ZIP_SIZE, cancel)
        with zipfile.ZipFile(runtimes / "indextts-src.zip") as zf:
            zf.extractall(runtimes / "indextts-src-tmp")
        inner = next((runtimes / "indextts-src-tmp").iterdir())
        shutil.move(str(inner), str(src_root))
        shutil.rmtree(runtimes / "indextts-src-tmp", ignore_errors=True)
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

    # ⑥ 自检：两栈各一遍（CosyVoice 走 worker --check，含 sys.path 引导）
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
    _pct(100, "完成")


def _extract_zip_stripped(archive: Path, dest: Path) -> None:
    """GitHub zip 有一层 <repo>-<rev>/ 前缀，剥掉后落 dest。"""
    with zipfile.ZipFile(archive) as zf:
        prefix = zf.namelist()[0].split("/")[0]
        for member in zf.infolist():
            name = member.filename.removeprefix(prefix + "/")
            if not name:
                continue
            target = dest / name
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))


def _extract_tar_stripped(archive: Path, dest: Path) -> None:
    """GitHub /archive/<sha>.tar.gz 有一层 <repo>-<sha>/ 前缀，剥掉后落 dest。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        strip = members[0].name.split("/")[0]
        for member in members:
            member.name = member.name.removeprefix(strip + "/")
            if member.name:
                tar.extract(member, dest)


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
