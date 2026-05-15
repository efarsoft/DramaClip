"""
模型下载管理服务
支持 ASR (faster-whisper) 和 TTS (StyleTTS 2) 模型的下载、检测、删除
"""

import json
import os
import shutil
import tempfile
import threading
import time
import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

from loguru import logger


# ---------------------------------------------------------------------------
# 模型注册表 - 定义所有可管理的模型
# ---------------------------------------------------------------------------

ModelInfo = {
    "id": str,          # 唯一标识，如 "whisper-large-v3"
    "name": str,        # 显示名称
    "category": str,    # "asr" | "tts"
    "type": str,        # "whisper" | "styletts2"
    "size_mb": float,   # 预估大小（MB）
    "description": str, # 描述
    "download_urls": list,  # 下载地址列表 (用于自定义进度追踪)
    "cache_dir": str,   # 缓存目录相对路径
}

# Whisper 模型信息
WHISPER_MODELS = {
    "tiny": {
        "id": "whisper-tiny",
        "name": "Whisper Tiny",
        "category": "asr",
        "type": "whisper",
        "size_mb": 150,
        "description": "轻量级，速度快，准确率较低",
        "hf_repo": "Systran/faster-whisper-tiny",
        "required_files": [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "preprocessor_config.json",
            "vocabulary.json",
        ],
    },
    "base": {
        "id": "whisper-base",
        "name": "Whisper Base",
        "category": "asr",
        "type": "whisper",
        "size_mb": 290,
        "description": "基础模型，平衡速度与准确率",
        "hf_repo": "Systran/faster-whisper-base",
        "required_files": [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "preprocessor_config.json",
            "vocabulary.json",
        ],
    },
    "small": {
        "id": "whisper-small",
        "name": "Whisper Small",
        "category": "asr",
        "type": "whisper",
        "size_mb": 950,
        "description": "中等大小，推荐日常使用",
        "hf_repo": "Systran/faster-whisper-small",
        "required_files": [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "preprocessor_config.json",
            "vocabulary.json",
        ],
    },
    "medium": {
        "id": "whisper-medium",
        "name": "Whisper Medium",
        "category": "asr",
        "type": "whisper",
        "size_mb": 3000,
        "description": "大模型，高准确率，需 ~3GB",
        "hf_repo": "Systran/faster-whisper-medium",
        "required_files": [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "preprocessor_config.json",
            "vocabulary.json",
        ],
    },
    "large-v3": {
        "id": "whisper-large-v3",
        "name": "Whisper Large V3",
        "category": "asr",
        "type": "whisper",
        "size_mb": 6000,
        "description": "最大模型，最高准确率，需 ~6GB",
        "hf_repo": "Systran/faster-whisper-large-v3",
        "required_files": [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "preprocessor_config.json",
            "vocabulary.json",
        ],
    },
}

# StyleTTS 2 模型信息
STYLETTS2_MODEL = {
    "id": "styletts2",
    "name": "StyleTTS 2",
    "category": "tts",
    "type": "styletts2",
    "size_mb": 2000,
    "description": "情感语音合成模型，支持风格迁移，约 2GB",
    "hf_repo": "yl4579/StyleTTS2-LJSpeech",
    "checkpoint_file": "checkpoint.pth",
    "config_file": "config.yml",
}


# ---------------------------------------------------------------------------
# 缓存目录检测
# ---------------------------------------------------------------------------

def _get_hf_home() -> Path:
    """获取 HuggingFace Hub 缓存根目录"""
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    hf_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hf_cache:
        return Path(hf_cache)
    return Path.home() / ".cache" / "huggingface" / "hub"


def _get_hf_model_dir(hf_repo: str) -> Path:
    """获取 HuggingFace 模型在缓存中的目录"""
    # huggingface hub 缓存格式: models--{org}--{name}
    repo_id_safe = hf_repo.replace("/", "--").replace("-", "--")
    return _get_hf_home() / f"models--{repo_id_safe}"


def _get_styletts2_cache_dir() -> Path:
    """获取 StyleTTS 2 缓存目录"""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return base / "styletts2"


def check_whisper_model(model_size: str) -> bool:
    """检查指定大小的 Whisper 模型是否已下载"""
    info = WHISPER_MODELS.get(model_size)
    if not info:
        return False
    model_dir = _get_hf_model_dir(info["hf_repo"])
    if not model_dir.exists():
        return False
    # 检查快照目录
    snapshots_dir = model_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        return False
    # 检查最新的快照是否包含所需文件
    latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)
    for fname in info["required_files"]:
        if not (latest_snapshot / fname).exists():
            return False
    return True


def check_styletts2_model() -> bool:
    """检查 StyleTTS 2 模型是否已下载"""
    cache_dir = _get_styletts2_cache_dir()
    checkpoint = cache_dir / STYLETTS2_MODEL["checkpoint_file"]
    config = cache_dir / STYLETTS2_MODEL["config_file"]
    return checkpoint.exists() and config.exists()


def get_whisper_model_size_on_disk(model_size: str) -> int:
    """获取已下载的 Whisper 模型占用磁盘大小（字节）"""
    info = WHISPER_MODELS.get(model_size)
    if not info:
        return 0
    model_dir = _get_hf_model_dir(info["hf_repo"])
    if not model_dir.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(str(model_dir)):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def get_styletts2_model_size_on_disk() -> int:
    """获取已下载的 StyleTTS 2 模型占用磁盘大小（字节）"""
    cache_dir = _get_styletts2_cache_dir()
    if not cache_dir.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(str(cache_dir)):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def delete_whisper_model(model_size: str) -> bool:
    """删除指定大小的 Whisper 模型"""
    info = WHISPER_MODELS.get(model_size)
    if not info:
        return False
    model_dir = _get_hf_model_dir(info["hf_repo"])
    if not model_dir.exists():
        logger.warning(f"Whisper model {model_size} not found at {model_dir}")
        return False
    try:
        shutil.rmtree(str(model_dir))
        logger.info(f"Deleted Whisper model {model_size}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete Whisper model {model_size}: {e}")
        return False


def delete_styletts2_model() -> bool:
    """删除 StyleTTS 2 模型"""
    cache_dir = _get_styletts2_cache_dir()
    if not cache_dir.exists():
        logger.warning(f"StyleTTS2 model not found at {cache_dir}")
        return False
    try:
        shutil.rmtree(str(cache_dir))
        logger.info("Deleted StyleTTS2 model")
        return True
    except Exception as e:
        logger.error(f"Failed to delete StyleTTS2 model: {e}")
        return False


# ---------------------------------------------------------------------------
# 模型下载（带进度）
# ---------------------------------------------------------------------------

_download_tasks: Dict[str, threading.Thread] = {}
_download_cancel_flags: Dict[str, threading.Event] = {}
_progress_callbacks: Dict[str, Callable] = {}


def _download_file(
    url: str,
    dest_path: Path,
    task_id: str,
    cancel_flag: threading.Event,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> bool:
    """
    下载单个文件，支持进度回调

    Args:
        url: 下载 URL
        dest_path: 目标路径
        task_id: 任务 ID
        cancel_flag: 取消标志
        progress_callback: 进度回调 fn(progress: int, message: str)
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # 先获取文件大小
        req = Request(url, method="HEAD")
        with urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))

        # 开始下载
        req = Request(url)
        with urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", total_size))
            downloaded = 0
            chunk_size = 8192
            last_report = 0

            with tempfile.NamedTemporaryFile(
                delete=False, dir=str(dest_path.parent)
            ) as tmp:
                while True:
                    if cancel_flag.is_set():
                        tmp.close()
                        os.unlink(tmp.name)
                        logger.info(f"Download cancelled: {url}")
                        return False

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    downloaded += len(chunk)

                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        if pct > last_report or downloaded == total:
                            last_report = pct
                            mb_downloaded = downloaded / (1024 * 1024)
                            mb_total = total / (1024 * 1024)
                            msg = (
                                f"下载中… {pct}% "
                                f"({mb_downloaded:.1f}/{mb_total:.1f} MB)"
                            )
                            if progress_callback:
                                progress_callback(pct, msg)

                # 写入完成，重命名
                shutil.move(tmp.name, str(dest_path))

        return True

    except URLError as e:
        logger.error(f"Download failed (network): {url} -> {e}")
        if progress_callback:
            progress_callback(-1, f"网络错误: {e.reason}")
        return False
    except Exception as e:
        logger.error(f"Download failed: {url} -> {e}")
        if progress_callback:
            progress_callback(-1, f"下载失败: {e}")
        return False


def download_whisper_model(
    model_size: str,
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 Whisper 模型（通过 huggingface_hub，带进度回调）

    huggingface_hub 的 hf_hub_download 支持 resume 和 cache，
    但我们需要自定义进度。这里使用 huggingface_hub 的 snapshot_download。
    """
    info = WHISPER_MODELS.get(model_size)
    if not info:
        raise ValueError(f"Unknown whisper model size: {model_size}")

    if cancel_flag is None:
        cancel_flag = threading.Event()

    try:
        from huggingface_hub import snapshot_download, HfApi
        from huggingface_hub.utils import (
            HfHubHTTPError,
            LocalEntryNotFoundError,
        )

        repo_id = info["hf_repo"]

        if progress_callback:
            progress_callback(0, f"正在连接 HuggingFace…")

        local_dir = snapshot_download(
            repo_id=repo_id,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        if progress_callback:
            progress_callback(100, f"下载完成")

    except ImportError:
        # 没有 huggingface_hub，回退到直接下载
        logger.warning(
            "huggingface_hub not installed, falling back to direct download"
        )
        _download_whisper_direct(model_size, progress_callback, cancel_flag)
    except InterruptedError:
        logger.info(f"Whisper {model_size} download cancelled by user")
        if progress_callback:
            progress_callback(-2, "已取消")
    except HfHubHTTPError as e:
        logger.error(f"HuggingFace Hub error: {e}")
        if progress_callback:
            progress_callback(-1, f"网络错误: {e}")
    except Exception as e:
        logger.error(f"Failed to download whisper model {model_size}: {e}")
        if progress_callback:
            progress_callback(-1, f"下载失败: {e}")


def _download_whisper_direct(
    model_size: str,
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """回退方案：直接从 HuggingFace 下载模型文件"""
    info = WHISPER_MODELS.get(model_size)
    if not info:
        return

    # 尝试从 HuggingFace 模型页面获取文件列表
    hf_base = f"https://huggingface.co/{info['hf_repo']}/resolve/main"
    model_dir = _get_hf_model_dir(info["hf_repo"])
    snapshots_dir = model_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    import hashlib
    import json

    # 生成本地快照 ID
    snapshot_id = hashlib.sha256(
        f"{info['hf_repo']}-{int(time.time())}".encode()
    ).hexdigest()[:12]
    snapshot_path = snapshots_dir / snapshot_id
    snapshot_path.mkdir(parents=True, exist_ok=True)

    files = info["required_files"]
    total_files = len(files)
    for idx, fname in enumerate(files):
        if cancel_flag and cancel_flag.is_set():
            if progress_callback:
                progress_callback(-2, "已取消")
            shutil.rmtree(str(snapshot_path), ignore_errors=True)
            return

        url = f"{hf_base}/{fname}"
        dest = snapshot_path / fname
        file_pct_base = int((idx / total_files) * 90)

        def _file_progress(fp: int, msg: str):
            if progress_callback:
                overall = file_pct_base + int(fp / total_files)
                progress_callback(min(overall, 99), msg)

        success = _download_file(url, dest, model_size, cancel_flag, _file_progress)
        if not success:
            shutil.rmtree(str(snapshot_path), ignore_errors=True)
            return

    # 写入 refs
    refs_dir = model_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / "main").write_text(snapshot_id)

    if progress_callback:
        progress_callback(100, "下载完成")


def download_styletts2_model(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 StyleTTS 2 模型
    优先使用 huggingface_hub，回退到直接下载
    """
    if cancel_flag is None:
        cancel_flag = threading.Event()

    cache_dir = _get_styletts2_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    repo_id = STYLETTS2_MODEL["hf_repo"]

    try:
        from huggingface_hub import hf_hub_download

        if progress_callback:
            progress_callback(0, "正在连接 HuggingFace…")

        # 下载 checkpoint
        checkpoint_path = hf_hub_download(
            repo_id=repo_id,
            filename=STYLETTS2_MODEL["checkpoint_file"],
            local_dir=str(cache_dir),
            resume_download=True,
        )
        if progress_callback:
            progress_callback(50, "下载检查点完成，正在下载配置文件…")

        # 下载 config
        config_path = hf_hub_download(
            repo_id=repo_id,
            filename=STYLETTS2_MODEL["config_file"],
            local_dir=str(cache_dir),
            resume_download=True,
        )
        if progress_callback:
            progress_callback(100, "下载完成")

    except ImportError:
        logger.warning(
            "huggingface_hub not installed, falling back to direct download"
        )
        _download_styletts2_direct(progress_callback, cancel_flag)
    except InterruptedError:
        logger.info("StyleTTS2 download cancelled by user")
        if progress_callback:
            progress_callback(-2, "已取消")
    except Exception as e:
        logger.error(f"Failed to download StyleTTS2 model: {e}")
        if progress_callback:
            progress_callback(-1, f"下载失败: {e}")


def _download_styletts2_direct(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """回退方案：直接从 HuggingFace 下载 StyleTTS2 文件"""
    cache_dir = _get_styletts2_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    hf_base = (
        f"https://huggingface.co/{STYLETTS2_MODEL['hf_repo']}/resolve/main"
    )

    # 下载 checkpoint
    checkpoint_url = f"{hf_base}/{STYLETTS2_MODEL['checkpoint_file']}"
    checkpoint_dest = cache_dir / STYLETTS2_MODEL["checkpoint_file"]

    if progress_callback:
        progress_callback(0, "下载 StyleTTS2 检查点 (~2GB)…")

    ok = _download_file(
        checkpoint_url,
        checkpoint_dest,
        "styletts2",
        cancel_flag,
        lambda p, m: progress_callback(p // 2, m) if progress_callback else None,
    )
    if not ok:
        return

    # 下载 config
    config_url = f"{hf_base}/{STYLETTS2_MODEL['config_file']}"
    config_dest = cache_dir / STYLETTS2_MODEL["config_file"]

    if progress_callback:
        progress_callback(50, "下载配置文件…")

    ok = _download_file(
        config_url,
        config_dest,
        "styletts2",
        cancel_flag,
        lambda p, m: progress_callback(50 + p // 2, m) if progress_callback else None,
    )
    if not ok:
        return

    if progress_callback:
        progress_callback(100, "下载完成")


# ---------------------------------------------------------------------------
# 模型管理 API
# ---------------------------------------------------------------------------

def list_models() -> List[Dict]:
    """
    列出所有可用模型及其状态

    Returns:
        [{
            "id": str,
            "name": str,
            "category": "asr" | "tts",
            "type": "whisper" | "styletts2",
            "size_mb": float,
            "description": str,
            "downloaded": bool,
            "disk_size_bytes": int,
        }, ...]
    """
    models = []

    # Whisper 模型
    for size, info in WHISPER_MODELS.items():
        downloaded = check_whisper_model(size)
        disk_size = get_whisper_model_size_on_disk(size) if downloaded else 0
        models.append({
            "id": info["id"],
            "name": info["name"],
            "category": "asr",
            "type": "whisper",
            "size_mb": info["size_mb"],
            "description": info["description"],
            "downloaded": downloaded,
            "disk_size_bytes": disk_size,
        })

    # StyleTTS 2
    downloaded = check_styletts2_model()
    disk_size = get_styletts2_model_size_on_disk() if downloaded else 0
    models.append({
        "id": STYLETTS2_MODEL["id"],
        "name": STYLETTS2_MODEL["name"],
        "category": "tts",
        "type": "styletts2",
        "size_mb": STYLETTS2_MODEL["size_mb"],
        "description": STYLETTS2_MODEL["description"],
        "downloaded": downloaded,
        "disk_size_bytes": disk_size,
    })

    return models


def download_model(
    model_id: str,
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    下载指定模型（在后台线程中执行）

    Args:
        model_id: 模型 ID（如 "whisper-large-v3", "styletts2"）
        progress_callback: 进度回调 fn(progress: int, message: str)

    Returns:
        是否成功启动下载
    """
    # 检查是否正在下载
    if model_id in _download_tasks and _download_tasks[model_id].is_alive():
        logger.warning(f"Model {model_id} is already downloading")
        return False

    cancel_flag = threading.Event()
    _download_cancel_flags[model_id] = cancel_flag

    def _run():
        try:
            # 判断模型类型
            if model_id == "styletts2":
                download_styletts2_model(progress_callback, cancel_flag)
            elif model_id.startswith("whisper-"):
                size = model_id.replace("whisper-", "", 1)
                download_whisper_model(size, progress_callback, cancel_flag)
            else:
                if progress_callback:
                    progress_callback(-1, f"未知模型: {model_id}")
        finally:
            _download_tasks.pop(model_id, None)
            _download_cancel_flags.pop(model_id, None)

    thread = threading.Thread(target=_run, daemon=True, name=f"dl-{model_id}")
    _download_tasks[model_id] = thread
    _progress_callbacks[model_id] = progress_callback
    thread.start()
    return True


def cancel_download(model_id: str) -> bool:
    """取消正在进行的下载"""
    flag = _download_cancel_flags.get(model_id)
    if flag:
        flag.set()
        logger.info(f"Cancelling download: {model_id}")
        return True
    return False


def delete_model(model_id: str) -> bool:
    """删除已下载的模型"""
    if model_id == "styletts2":
        return delete_styletts2_model()
    elif model_id.startswith("whisper-"):
        size = model_id.replace("whisper-", "", 1)
        return delete_whisper_model(size)
    return False


def get_download_status(model_id: str) -> Dict:
    """获取下载状态"""
    is_active = (
        model_id in _download_tasks
        and _download_tasks[model_id].is_alive()
    )
    return {
        "downloading": is_active,
        "model_id": model_id,
    }
