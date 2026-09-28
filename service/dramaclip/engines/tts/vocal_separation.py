"""参考音频清洗「彻底档」的编排：模型就位 → 拉起 worker 分离 → 回收干声路径。

主服务进程（Python 3.13）不 import audio_separator——它住在 tts-venv，与双栈
TTS 共用运行时（tts_runtime.py 安装）。这里只做三件事：模型文件在不在（不在
就经 gh-proxy 多源下载，与 tts_runtime 同一套容错姿势）；venv 在不在（不在就
说明去引擎页装运行环境，而不是裸抛 ImportError）；worker 的超时与协议解析。

「快速档」（ffmpeg 滤镜链，零依赖）在 reference_clean.py，两档由 RPC 层按
mode 参数分发。QC 实测对比（scratch/ref-voice-10s.wav，2026-09-28）：
原始 fair/SNR 10.7dB → fast 档 fair/13.6dB → 本档 good/26.1dB（削波归零）——
底噪大头是 BGM，滤镜链只能压不能剥，这也是默认走本档的依据。
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from dramaclip.engines.tts.reference_clean import cleaned_path
from dramaclip.infra.model_manager.fetch import download_file
from dramaclip.infra.paths import resolve_data_dir

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MODEL_FILENAME = "UVR_MDXNET_KARA_2.onnx"
#: 实测精确字节数（2026-09-28 下载量得）：expected_size 是精确匹配校验，防代理截断。
_MODEL_SIZE = 52_786_726
_MODEL_SOURCES = [
    f"https://gh-proxy.com/https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/{_MODEL_FILENAME}",
    f"https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/{_MODEL_FILENAME}",
]
#: RTF≈2（CPU 实测）+ 模型加载；900s 足够 3 分钟长参考，也兜得住首跑冷启动。
_TIMEOUT_S = 900


def model_path(models_dir: Path) -> Path:
    return models_dir / "tts" / "separation" / _MODEL_FILENAME


def clean_reference(models_dir: Path, src: Path) -> Path:
    """分离出干声，落 <stem>.cleaned.wav（与 fast 档同一命名语义）。"""
    py = _venv_python()
    if not py.is_file():
        raise RuntimeError(
            "TTS 运行环境未安装（人声分离与克隆引擎共用 tts-venv）："
            "在引擎页「安装运行环境」后重试"
        )
    ensure_model(models_dir)  # worker 不做下载：模型没就位时在这边用多源容错补
    out = cleaned_path(src)
    worker_src = _worker_src()
    cmd = [
        str(py), str(worker_src),
        "--in", str(src), "--out", str(out),
        "--models", str(model_path(models_dir).parent),
    ]
    result = subprocess.run(  # noqa: S603 - 固定解释器固定 worker 脚本
        cmd, capture_output=True, text=True, timeout=_TIMEOUT_S,
        creationflags=_NO_WINDOW, check=False,
    )
    return _collect(result, out)


def ensure_model(models_dir: Path) -> Path:
    """模型缺失时多源下载（一次点击可能就是首次使用），存在即原样返回。"""
    target = model_path(models_dir)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for url in _MODEL_SOURCES:
        try:
            download_file(url, target, _MODEL_SIZE, cancel=threading.Event())
            return target
        except Exception as exc:  # noqa: BLE001 - 多源容错，与 tts_runtime 同姿势
            last = exc
    raise RuntimeError(f"分离模型下载失败: {last}") from last


def _collect(result: subprocess.CompletedProcess[str], out: Path) -> Path:
    """worker 的 stdout 只认最后一行 JSON：日志混不进来，退出码不当你撒谎。"""
    line = (result.stdout.strip().splitlines() or [""])[-1]
    try:
        payload: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"worker 没有返回协议应答（exit={result.returncode}）") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"分离失败：{payload.get('error', '未知原因')}")
    path = Path(str(payload["out"]))
    if not path.is_file():
        raise RuntimeError(f"worker 报告成功但产物不存在：{path}")
    if path != out:
        raise RuntimeError(f"worker 产物路径与约定不符：{path}（应为 {out}）")
    return path


def _worker_src() -> Path:
    from dramaclip.engines.tts.workers import separation_worker

    return Path(separation_worker.__file__)


def _venv_python() -> Path:
    return resolve_data_dir() / "runtimes" / "tts-venv" / "Scripts" / "python.exe"
