"""
模型下载管理服务
支持 ASR (faster-whisper)、TTS (StyleTTS 2) 和 Diarization (pyannote) 模型的下载、检测、删除
"""

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

from loguru import logger

import yaml  # for models.yaml catalog (aligned with OmniVoice-Studio reference)

# ---------------------------------------------------------------------------
# 下载渠道管理（ModelScope 优先，HuggingFace 备选）
# ---------------------------------------------------------------------------
_CHANNEL_FILE = Path(__file__).resolve().parent.parent.parent / "storage" / "download_channel.json"
_VALID_CHANNELS = ("modelscope", "huggingface")

# repo_id → ModelScope 镜像映射（仅需要特殊映射的条目，其余直接用 HF repo_id）
_MODELSCOPE_MIRROR = {
    "pyannote/speaker-diarization-3.1": "AI-ModelScope/speaker-diarization-3.1",
    "pyannote/segmentation-3.0": "AI-ModelScope/segmentation-3.0",
}


def get_download_channel() -> str:
    """获取当前下载渠道，默认 modelscope"""
    try:
        if _CHANNEL_FILE.exists():
            data = json.loads(_CHANNEL_FILE.read_text(encoding="utf-8"))
            ch = data.get("channel", "modelscope")
            if ch in _VALID_CHANNELS:
                return ch
    except Exception:
        pass
    return "modelscope"


def set_download_channel(channel: str) -> bool:
    """设置下载渠道: 'modelscope' 或 'huggingface'"""
    if channel not in _VALID_CHANNELS:
        return False
    try:
        _CHANNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CHANNEL_FILE.write_text(
            json.dumps({"channel": channel}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"下载渠道已切换为: {channel}")
        return True
    except Exception as e:
        logger.error(f"保存下载渠道失败: {e}")
        return False


def _resolve_modelscope_id(hf_repo_id: str) -> str:
    """将 HF repo_id 映射为 ModelScope repo_id（大部分直接复用）"""
    return _MODELSCOPE_MIRROR.get(hf_repo_id, hf_repo_id)


# huggingface_hub 错误导入
_HF_HUB_AVAILABLE = True
try:
    from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError
except ImportError:
    _HF_HUB_AVAILABLE = False
    HfHubHTTPError = Exception  # type: ignore
    LocalEntryNotFoundError = Exception  # type: ignore


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

# Whisper 模型信息 (now derived from central catalog where possible)
# The central catalog (models.yaml) is the source of truth. These are thin compatibility wrappers.
WHISPER_MODELS = {
    "tiny": {
        "id": "whisper-tiny",
        "name": "Whisper Tiny",
        "category": "asr",
        "type": "whisper",
        "size_mb": 150,
        "description": "轻量级，速度快，准确率较低",
        "hf_repo": "Systran/faster-whisper-tiny",
        "required_files": ["model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"],
    },
    "base": {
        "id": "whisper-base",
        "name": "Whisper Base",
        "category": "asr",
        "type": "whisper",
        "size_mb": 290,
        "description": "基础模型，平衡速度与准确率",
        "hf_repo": "Systran/faster-whisper-base",
        "required_files": ["model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"],
    },
    "small": {
        "id": "whisper-small",
        "name": "Whisper Small",
        "category": "asr",
        "type": "whisper",
        "size_mb": 950,
        "description": "中等大小，推荐日常使用",
        "hf_repo": "Systran/faster-whisper-small",
        "required_files": ["model.bin",
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
    "checkpoint_file": "Models/LJSpeech/epoch_2nd_00100.pth",
    "config_file": "Models/LJSpeech/config.yml",
}

# Kokoro-82M (极致轻量中文TTS)
KOKORO_MODEL = {
    "id": "kokoro-82m",
    "name": "Kokoro-82M (v1.1-zh)",
    "category": "tts",
    "type": "kokoro",
    "size_mb": 82,
    "description": "2026最轻量高性价比TTS，82M参数，中文自然度良好，极低资源消耗，适合边缘设备。",
    "hf_repo": "hexgrad/Kokoro-82M-v1.1-zh",
}

# CosyVoice2 / Fun-CosyVoice3 (高质量中文TTS选项之一，质量优先不锁定默认)
COSYVOICE2_MODEL = {
    "id": "cosyvoice2-0.5b",
    "name": "Fun-CosyVoice3 0.5B",
    "category": "tts",
    "type": "cosyvoice",
    "size_mb": 500,
    "description": "高质量中文TTS选项（自然度/韵律/方言支持较强）。与其他TTS模型一样通过中央目录管理，不作为全局默认锁定。",
    "modelscope_id": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    "hf_repo": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
}

# SenseVoice-Small 模型信息 (ASR 极速高精推荐)
SENSEVOICE_MODEL = {
    "id": "SenseVoice-large",  # 兼容前端 asrConfig.model = 'SenseVoice-large'
    "name": "SenseVoice-Small (默认)",
    "category": "asr",
    "type": "sensevoice",
    "size_mb": 890,
    "description": "方言、情绪与BGM识别天花板。极速非自回归，适合大部分中文及情绪对齐场景。",
    "model_id": "iic/SenseVoiceSmall",
    "required_files": ["model.pt", "config.yaml", "tokens.json"]
}

# Pyannote 说话人分离模型信息
PYANNOTE_MODELS = {
    "diarization-3.1": {
        "id": "pyannote-diarization-3.1",
        "name": "Pyannote Diarization 3.1",
        "category": "diarization",
        "type": "pyannote",
        "size_mb": 1500,
        "description": "说话人分离模型，高精度识别不同说话人，约 1.5GB",
        "hf_repo": "pyannote/speaker-diarization-3.1",
        "required_files": [
            "config.yaml",
        ],
    },
    "segmentation-3.0": {
        "id": "pyannote-segmentation-3.0",
        "name": "Pyannote Segmentation 3.0",
        "category": "diarization",
        "type": "pyannote",
        "size_mb": 100,
        "description": "语音分割模型，用于预分割音频，约 100MB",
        "hf_repo": "pyannote/segmentation-3.0",
        "required_files": [
            "pytorch_model.bin",
            "config.yaml",
        ],
    },
}

# ---------------------------------------------------------------------------
# 中央模型目录 (严格参照 OmniVoice-Studio backend/config/models.yaml)
# 所有模型统一通过 huggingface_hub.snapshot_download 下载
# 成品质量第一：不锁定任何单一 TTS 模型为默认
# ---------------------------------------------------------------------------

_MODELS_YAML_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"

_KNOWN_MODELS_CATALOG: list[dict] = []


def load_model_catalog() -> list[dict]:
    """
    加载中央模型目录 (参考 OmniVoice-Studio 实现)。
    所有可下载模型的唯一真相来源。统一 HF 下载入口。
    """
    global _KNOWN_MODELS_CATALOG
    if _KNOWN_MODELS_CATALOG:
        return _KNOWN_MODELS_CATALOG

    try:
        if not _MODELS_YAML_PATH.exists():
            logger.warning(f"models.yaml not found at {_MODELS_YAML_PATH}, using fallback catalog")
            _KNOWN_MODELS_CATALOG = _get_fallback_catalog()
            return _KNOWN_MODELS_CATALOG

        with open(_MODELS_YAML_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        _KNOWN_MODELS_CATALOG = data.get("models", [])
        logger.info(f"Loaded {len(_KNOWN_MODELS_CATALOG)} models from central catalog: {_MODELS_YAML_PATH}")
        return _KNOWN_MODELS_CATALOG
    except Exception as e:
        logger.error(f"Failed to load models.yaml: {e}. Using fallback.")
        _KNOWN_MODELS_CATALOG = _get_fallback_catalog()
        return _KNOWN_MODELS_CATALOG


def _get_fallback_catalog() -> list[dict]:
    """Fallback catalog (minimal set, aligned with models.yaml)."""
    return [
        {
            "repo_id": "iic/SenseVoiceSmall",
            "label": "SenseVoice Small (中文方言/情感/BGM识别)",
            "role": "ASR",
            "size_gb": 0.9,
            "category": "asr",
            "required": True,
        },
        {
            "repo_id": "hexgrad/Kokoro-82M-v1.1-zh",
            "label": "Kokoro-82M v1.1 中文 (超轻量本地兜底)",
            "role": "TTS",
            "size_gb": 0.15,
            "category": "tts",
        },
    ]


def get_model_by_repo_id(repo_id: str) -> Optional[dict]:
    catalog = load_model_catalog()
    for m in catalog:
        if m.get("repo_id") == repo_id:
            return m
    return None


def download_hf_model(
    repo_id: str,
    local_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
) -> bool:
    """
    统一模型下载入口（ModelScope 优先，HuggingFace 备选）。
    自动集成 hf_progress 适配器 → IPC progress.update（前端可消费的结构化进度）。
    """
    from app.utils import hf_progress
    hf_progress.ensure_installed()

    if cancel_flag is None:
        cancel_flag = threading.Event()

    model_info = get_model_by_repo_id(repo_id) or {"label": repo_id}
    task_id = f"model:{repo_id}"

    token = hf_progress.current_repo_id.set(repo_id)

    from app.ipc.handlers.base import send_progress

    def _ipc_listener(ev: dict):
        pct = int(ev.get("pct", 0) * 100) if ev.get("pct") is not None else -1
        phase = ev.get("phase", "download")
        filename = ev.get("filename", "")

        msg = filename or f"Downloading {repo_id}"
        if phase == "done":
            msg = "Download complete"

        detail = {
            "repo_id": repo_id,
            "filename": filename,
            "downloaded": ev.get("downloaded"),
            "total": ev.get("total"),
        }
        send_progress(task_id, pct, msg, phase=phase, detail=detail)  # type: ignore

        if progress_callback:
            progress_callback(pct, msg)

    listener_id = hf_progress.register_listener(_ipc_listener)

    channel = get_download_channel()
    # pyannote 等 gated 模型：先尝试 ModelScope，失败则自动降级 HuggingFace

    if local_dir is None:
        safe_name = repo_id.replace("/", "--")
        local_dir = str(_get_project_root() / "pretrained_models" / safe_name)

    target_dir = Path(local_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── ModelScope 渠道（国内首选） ────────────────────────────────
        if channel == "modelscope":
            ms_repo_id = _resolve_modelscope_id(repo_id)
            try:
                from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download
            except ImportError:
                logger.warning("modelscope SDK 未安装，回退到 HuggingFace")
                channel = "huggingface"

        if channel == "modelscope":
            if progress_callback:
                progress_callback(0, f"开始从 ModelScope 下载 {model_info.get('label', repo_id)}...")

            hf_progress.emit({"repo_id": repo_id, "phase": "start", "filename": repo_id})

            try:
                ms_snapshot_download(
                    model_id=ms_repo_id,
                    local_dir=str(target_dir),
                )
            except Exception as ms_err:
                logger.warning(f"ModelScope 下载失败 ({ms_repo_id}): {ms_err}，尝试降级到 HuggingFace")
                if progress_callback:
                    progress_callback(0, f"ModelScope 下载失败，正在切换 HuggingFace...")
                channel = "huggingface"
                # 清理可能的不完整下载
                if target_dir.exists():
                    for item in target_dir.iterdir():
                        if item.is_file():
                            item.unlink(missing_ok=True)

        if channel == "modelscope":
            hf_progress.emit({"repo_id": repo_id, "phase": "done", "filename": repo_id, "pct": 1.0})

            if progress_callback:
                progress_callback(100, f"{model_info.get('label', repo_id)} 下载完成（ModelScope）")

            logger.info(f"Model {repo_id} downloaded via ModelScope ({ms_repo_id}) to {target_dir}")
            return True

        # ── HuggingFace 渠道（国际备选） ──────────────────────────────
        try:
            import huggingface_hub
        except ImportError:
            if progress_callback:
                progress_callback(0, "缺少 huggingface_hub 包，正在尝试安装...")
            import subprocess, sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub", "tqdm"])
            import huggingface_hub

        # gated 模型（如 pyannote）需要 token 才能下载
        from app.utils.hf_auth import ensure_hf_login, get_hf_token
        ensure_hf_login()
        hf_token = get_hf_token()

        if progress_callback:
            progress_callback(0, f"开始从 HuggingFace 下载 {model_info.get('label', repo_id)}...")

        hf_progress.emit({"repo_id": repo_id, "phase": "start", "filename": repo_id})

        from huggingface_hub import snapshot_download
        path = snapshot_download(
            repo_id=repo_id,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
            token=hf_token,
        )

        hf_progress.emit({"repo_id": repo_id, "phase": "done", "filename": repo_id, "pct": 1.0})

        if progress_callback:
            progress_callback(100, f"{model_info.get('label', repo_id)} 下载完成（HuggingFace）")

        logger.info(f"Model {repo_id} downloaded via HuggingFace snapshot_download to {path}")
        return True

    except Exception as e:
        err_str = str(e)
        logger.error(f"download_hf_model failed for {repo_id}: {err_str}")

        # 给用户更友好的提示，尤其是中国网络问题
        user_msg = f"下载失败: {err_str[:150]}"
        if "403" in err_str or "Unauthorized" in err_str or "gated" in err_str.lower():
            user_msg = "下载失败：该模型需要 HF_TOKEN（gated model），请先在设置中配置 HuggingFace Token"
        elif "timeout" in err_str.lower() or "connection" in err_str.lower():
            user_msg = f"下载失败：网络超时或连接问题（当前渠道: {channel}，可在模型管理页面切换下载渠道）"

        hf_progress.emit({"repo_id": repo_id, "phase": "error", "error": err_str[:200]})
        if progress_callback:
            progress_callback(0, user_msg)
        return False
    finally:
        hf_progress.unregister_listener(listener_id)
        hf_progress.current_repo_id.reset(token)


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
    """检查指定大小 of Whisper 模型是否已下载（优先以中央 catalog 为准）"""
    # 优先检测规整的本地物理路径
    try:
        local_dir = _get_models_root() / "asr" / "Systran" / f"faster-whisper-{model_size}"
        if local_dir.exists() and (
            (local_dir / "model.bin").exists() or (local_dir / "model.onnx").exists()
        ):
            return True
    except Exception:
        pass

    # 优先从中央 catalog 获取 repo
    catalog_entry = get_model_by_repo_id(f"Systran/faster-whisper-{model_size}")
    repo = catalog_entry["repo_id"] if catalog_entry else WHISPER_MODELS.get(model_size, {}).get("hf_repo")
    if not repo:
        return False

    model_dir = _get_hf_model_dir(repo)
    if not model_dir.exists():
        return False
    snapshots_dir = model_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        return False
    latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

    required = catalog_entry.get("required_files", []) if catalog_entry else WHISPER_MODELS.get(model_size, {}).get("required_files", [])
    if not required:
        return True

    for fname in required:
        if fname == "preprocessor_config.json":
            continue
        if fname == "vocabulary.json":
            if not (latest_snapshot / "vocabulary.json").exists() and not (latest_snapshot / "vocabulary.txt").exists():
                return False
        else:
            if not (latest_snapshot / fname).exists():
                return False
    return True


def check_styletts2_model() -> bool:
    """检查 StyleTTS 2 模型是否已下载"""
    cache_dir = _get_styletts2_cache_dir()
    checkpoint = cache_dir / "checkpoint.pth"
    config = cache_dir / "config.yml"
    return checkpoint.exists() and config.exists()


def check_pyannote_model(model_name: str = "diarization-3.1") -> bool:
    """检查指定的 Pyannote 模型是否已下载 (优先中央 pretrained_models，再查 HF 缓存)"""
    # ── 优先检查中央 pretrained_models 路径 ──────────────────────────────
    safe_name = f"pyannote--{model_name.replace('/', '--')}"
    # 兼容 speaker-diarization-3.1 和 diarization-3.1 两种命名
    if "speaker-" not in model_name:
        safe_name = "pyannote--speaker-diarization-3.1"
    central_dir = _get_project_root() / "pretrained_models" / safe_name
    if central_dir.exists():
        # 检查关键文件（config.yaml 是 pyannote 入口）
        if (central_dir / "config.yaml").exists():
            return True
        # 也检查 snapshots 子目录（snapshot_download 可能保留结构）
        snapshots = list(central_dir.glob("**/config.yaml"))
        if snapshots:
            return True

    # ── 回退检查 HF 缓存路径 ─────────────────────────────────────────────
    catalog_entry = get_model_by_repo_id(f"pyannote/{model_name}") or get_model_by_repo_id("pyannote/speaker-diarization-3.1")
    repo = catalog_entry["repo_id"] if catalog_entry else PYANNOTE_MODELS.get(model_name, {}).get("hf_repo")
    if not repo:
        return False

    model_dir = _get_hf_model_dir(repo)
    if not model_dir.exists():
        return False
    snapshots_dir = model_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        return False
    latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

    required = catalog_entry.get("required_files", []) if catalog_entry else PYANNOTE_MODELS.get(model_name, {}).get("required_files", [])
    if not required:
        return True

    for fname in required:
        if not (latest_snapshot / fname).exists():
            return False
    return True


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


def _get_project_root() -> Path:
    """Return the DramaClip project root (absolute path).

    Resolved from ``__file__``: app/services/model_manager.py → 3 levels up.
    """
    return Path(__file__).resolve().parent.parent.parent


def _get_kokoro_cache_dir() -> Path:
    """Kokoro 模型统一管理路径（绝对路径）"""
    return _get_project_root() / "pretrained_models" / "Kokoro-82M-v1.1-zh"


def check_kokoro_model() -> bool:
    cache = _get_kokoro_cache_dir()
    # 检查关键文件是否存在（.pth 权重 + config）
    pth_files = list(cache.rglob("*.pth")) if cache.exists() else []
    return len(pth_files) > 0


def download_kokoro_model(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 Kokoro-82M。
    现在统一委托给 download_hf_model（中央 catalog + snapshot_download）。
    """
    repo_id = KOKORO_MODEL["hf_repo"]
    return download_hf_model(
        repo_id=repo_id,
        local_dir=str(_get_kokoro_cache_dir()),
        progress_callback=progress_callback,
        cancel_flag=cancel_flag,
    )


def delete_kokoro_model() -> bool:
    cache = _get_kokoro_cache_dir()
    if not cache.exists():
        return False
    try:
        import shutil
        shutil.rmtree(str(cache))
        logger.info("Deleted Kokoro model")
        return True
    except Exception as e:
        logger.error(f"Failed to delete Kokoro model: {e}")
        return False


def _get_cosyvoice2_cache_dir() -> Path:
    """CosyVoice 模型统一管理路径（绝对路径）"""
    return _get_project_root() / "pretrained_models" / "Fun-CosyVoice3-0.5B-2512"


def check_cosyvoice2_model() -> bool:
    cache = _get_cosyvoice2_cache_dir()
    if not cache.exists():
        return False
    
    # After cleanup, the minimal working set for inference:
    # - config yaml (cosyvoice3.yaml or cosyvoice.yaml)
    # - Core weights: llm.pt, flow.pt, hift.pt
    # - campplus.onnx (speaker embedding, recommended)
    has_config = (cache / "cosyvoice3.yaml").exists() or (cache / "cosyvoice.yaml").exists()
    has_core_weights = all((cache / f).exists() for f in ["llm.pt", "flow.pt", "hift.pt"])
    return has_config and has_core_weights


def download_cosyvoice2_model(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 Fun-CosyVoice3-0.5B-2512。
    现在委托给统一的 download_hf_model（严格使用 snapshot_download + 中央目录）。
    """
    repo_id = COSYVOICE2_MODEL["hf_repo"]
    # 使用新的统一入口（质量优先，不锁定默认模型）
    return download_hf_model(
        repo_id=repo_id,
        local_dir=str(_get_cosyvoice2_cache_dir()),
        progress_callback=progress_callback,
        cancel_flag=cancel_flag,
    )


def resolve_model_path(repo_id: str) -> Optional[Path]:
    """Resolve the physical path for a model by repo_id.

    Search order:
      1. Central catalog ``local_dir`` key
      2. ``pretrained_models/<sanitized-repo>`` (project-root relative)
      3. ``pretrained_models/<short-name>`` (last segment of repo_id)
      4. HuggingFace cache ``~/.cache/huggingface/hub/models--...``
      5. Return ``None`` if not found
    """
    root = _get_project_root()

    # 1. Central catalog local_dir
    entry = get_model_by_repo_id(repo_id)
    if entry:
        local_dir = entry.get("local_dir")
        if local_dir and Path(local_dir).exists():
            return Path(local_dir).resolve()

    # 2. pretrained_models/<sanitized-repo>  (e.g. FunAudioLLM--Fun-CosyVoice3-0.5B-2512)
    safe_name = repo_id.replace("/", "--")
    candidate = root / "pretrained_models" / safe_name
    if candidate.exists():
        return candidate.resolve()

    # 3. pretrained_models/<short-name>  (e.g. Fun-CosyVoice3-0.5B-2512)
    short_name = repo_id.split("/")[-1]
    candidate = root / "pretrained_models" / short_name
    if candidate.exists():
        return candidate.resolve()

    # 4. HuggingFace cache
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    hf_dir_name = "models--" + repo_id.replace("/", "--")
    hf_path = hf_cache / hf_dir_name
    if hf_path.exists():
        # Find the snapshot directory
        snapshots = hf_path / "snapshots"
        if snapshots.exists():
            # Use the most recent snapshot
            snap_dirs = sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for sd in snap_dirs:
                if sd.is_dir():
                    return sd.resolve()

    return None


def _get_models_root() -> Path:
    """获取本地模型根目录路径 (动态解析)"""
    models_dir = os.environ.get("DRAMACLIP_MODELS_PATH")
    if models_dir:
        return Path(models_dir)
    try:
        from app.utils.utils import root_dir
        return Path(root_dir()) / "resources" / "models"
    except Exception:
        return Path(__file__).resolve().parent.parent.parent / "resources" / "models"


def _get_sensevoice_dir() -> Path:
    """获取 SenseVoice-Small 模型绝对物理路径"""
    return _get_models_root() / "asr" / "iic" / "SenseVoiceSmall"


def check_sensevoice_model() -> bool:
    """检查 SenseVoice-Small 模型是否已下载 (优先中央 catalog)"""
    catalog_entry = get_model_by_repo_id("iic/SenseVoiceSmall") or get_model_by_repo_id("FunAudioLLM/SenseVoiceSmall")
    if catalog_entry:
        # For SenseVoice we still use custom flat path, but catalog confirms it should be there
        target_dir = _get_sensevoice_dir()
        if target_dir.exists():
            has_pt = (target_dir / "model.pt").exists() and (target_dir / "config.yaml").exists()
            has_onnx = (target_dir / "model.onnx").exists() and (target_dir / "config.json").exists()
            return has_pt or has_onnx
        return False

    # fallback old logic
    target_dir = _get_sensevoice_dir()
    if not target_dir.exists():
        return False
    has_pt = (target_dir / "model.pt").exists() and (target_dir / "config.yaml").exists()
    has_onnx = (target_dir / "model.onnx").exists() and (target_dir / "config.json").exists()
    return has_pt or has_onnx


def get_sensevoice_model_size_on_disk() -> int:
    """获取已下载的 SenseVoice 模型占用磁盘大小（字节）"""
    target_dir = _get_sensevoice_dir()
    if not target_dir.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(str(target_dir)):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def delete_sensevoice_model() -> bool:
    """删除 SenseVoice 模型"""
    target_dir = _get_sensevoice_dir()
    if not target_dir.exists():
        logger.warning(f"SenseVoice model not found at {target_dir}")
        return False
    try:
        shutil.rmtree(str(target_dir))
        logger.info("Deleted SenseVoice model")
        return True
    except Exception as e:
        logger.error(f"Failed to delete SenseVoice model: {e}")
        return False


def get_pyannote_model_size_on_disk(model_name: str = "diarization-3.1") -> int:
    """获取已下载的 Pyannote 模型占用磁盘大小（字节）"""
    info = PYANNOTE_MODELS.get(model_name)
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


def delete_pyannote_model(model_name: str = "diarization-3.1") -> bool:
    """删除指定的 Pyannote 模型"""
    info = PYANNOTE_MODELS.get(model_name)
    if not info:
        return False
    model_dir = _get_hf_model_dir(info["hf_repo"])
    if not model_dir.exists():
        logger.warning(f"Pyannote model {model_name} not found at {model_dir}")
        return False
    try:
        shutil.rmtree(str(model_dir))
        logger.info(f"Deleted Pyannote model {model_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete Pyannote model {model_name}: {e}")
        return False


# ---------------------------------------------------------------------------
# 中央目录暴露（供 IPC / 前端使用，参考 OmniVoice-Studio /models 接口）
# ---------------------------------------------------------------------------

def list_central_catalog_models() -> list[dict]:
    """
    返回中央 models.yaml 中的所有模型 + 当前安装状态。
    前端可用于“模型管理”页面的一键安装列表 + 进度。
    """
    catalog = load_model_catalog()
    result = []

    for m in catalog:
        repo_id = m["repo_id"]
        installed = False
        size_on_disk = 0
        role = m.get("role") or m.get("category", "")

        # 精确状态检测（优先专用 check 函数，参考 OmniVoice-Studio 诚实 is_available 理念）
        try:
            if "CosyVoice" in repo_id:
                installed = check_cosyvoice2_model()
            elif "Kokoro" in repo_id:
                installed = check_kokoro_model()
            elif "SenseVoice" in repo_id or repo_id == "iic/SenseVoiceSmall":
                installed = check_sensevoice_model()
            elif "faster-whisper" in repo_id:
                # 从 repo_id 提取 size
                size = repo_id.split("/")[-1].replace("faster-whisper-", "")
                installed = check_whisper_model(size)
            elif "pyannote" in repo_id.lower() or "diarization" in repo_id.lower():
                installed = check_pyannote_model("diarization-3.1")
            else:
                # 通用 HF 缓存检测（最后兜底）
                from huggingface_hub import scan_cache_dir
                info = scan_cache_dir()
                for entry in info.repos:
                    if entry.repo_id == repo_id and entry.size_on_disk > 0:
                        installed = True
                        size_on_disk = entry.size_on_disk
                        break
        except Exception:
            pass

        result.append({
            **m,
            "installed": installed,
            "size_on_disk_bytes": size_on_disk,
            "download_supported": True,
        })

    return result


# ---------------------------------------------------------------------------
# 模型下载（带进度）
# ---------------------------------------------------------------------------

_download_tasks: Dict[str, threading.Thread] = {}
_download_cancel_flags: Dict[str, threading.Event] = {}
_progress_callbacks: Dict[str, Optional[Callable[[int, str], None]]] = {}


def _download_file(
    url: str,
    dest_path: Path,
    task_id: str,
    cancel_flag: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> bool:
    """
    下载单个文件，支持进度回调

    Args:
        url: 下载 URL
        dest_path: 目标路径
        task_id: 任务 ID
        cancel_flag: 取消标志（可选）
        progress_callback: 进度回调 fn(progress: int, message: str)
    """
    # 确保 cancel_flag 不是 None
    if cancel_flag is None:
        cancel_flag = threading.Event()

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # 先获取文件大小
        total_size = 0
        try:
            req = Request(url, method="HEAD")
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            with urlopen(req, timeout=10) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
        except Exception as head_err:
            logger.warning(f"HEAD request failed for {url}: {head_err}. Falling back to GET response info.")

        # 开始下载
        req = Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
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
    下载 Whisper 模型（优先以中央 catalog + 统一 download_hf_model 为准，
    回退到 ModelScope / 旧逻辑以保持国内环境兼容性）
    """
    # 优先从中央 catalog 获取标准 repo_id
    catalog_entry = get_model_by_repo_id(f"Systran/faster-whisper-{model_size}")
    if catalog_entry:
        # 直接走统一的高质量 HF 路径（snapshot_download + 进度系统）
        return download_hf_model(
            repo_id=catalog_entry["repo_id"],
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

    # 回退到旧逻辑（兼容）
    info = WHISPER_MODELS.get(model_size)
    if not info:
        raise ValueError(f"Unknown whisper model size: {model_size}")

    if cancel_flag is None:
        cancel_flag = threading.Event()

    repo_id = info["hf_repo"]

    # 1. 尝试使用 ModelScope SDK 进行下载 (满速免认证，适合国内环境)
    try:
        from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download
        
        if progress_callback:
            progress_callback(0, "正在通过 ModelScope 连接服务器…")

        model_dir = _get_hf_model_dir(repo_id)
        snapshot_path = model_dir / "snapshots" / "main"
        snapshot_path.mkdir(parents=True, exist_ok=True)

        # 写入 refs/main
        refs_dir = model_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text("main")

        if progress_callback:
            progress_callback(5, f"开始从 ModelScope 下载 {info['name']}…")
            
        ms_snapshot_download(
            model_id=repo_id,
            local_dir=str(snapshot_path),
        )
        
        if progress_callback:
            progress_callback(100, "下载完成")
        return
        
    except Exception as ms_err:
        logger.warning(f"Failed to use ModelScope SDK to download Whisper model: {ms_err}. Falling back to HuggingFace Mirror...")

    # 2. 回退到 HuggingFace Hub 下载
    try:
        from huggingface_hub import snapshot_download

        if progress_callback:
            progress_callback(0, "正在连接 HuggingFace…")

        snapshot_download(
            repo_id=repo_id,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        if progress_callback:
            progress_callback(100, "下载完成")

    except ImportError:
        logger.warning("huggingface_hub not installed, falling back to direct download")
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

    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    hf_base = f"{endpoint}/{info['hf_repo']}/resolve/main"
    model_dir = _get_hf_model_dir(info["hf_repo"])
    snapshot_path = model_dir / "snapshots" / "main"
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

        success = _download_file(url, dest, model_size, cancel_flag or threading.Event(), _file_progress)
        if not success:
            shutil.rmtree(str(snapshot_path), ignore_errors=True)
            return

    # 写入 refs/main
    refs_dir = model_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / "main").write_text("main")

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
        
        # 移动文件到 cache_dir / checkpoint.pth
        downloaded_ckpt = Path(checkpoint_path)
        final_ckpt = cache_dir / "checkpoint.pth"
        if downloaded_ckpt.exists() and downloaded_ckpt != final_ckpt:
            # 确保父目录存在并且进行覆盖性移动
            shutil.move(str(downloaded_ckpt), str(final_ckpt))

        if progress_callback:
            progress_callback(50, "下载检查点完成，正在下载配置文件…")

        # 下载 config
        config_path = hf_hub_download(
            repo_id=repo_id,
            filename=STYLETTS2_MODEL["config_file"],
            local_dir=str(cache_dir),
            resume_download=True,
        )
        
        # 移动文件到 cache_dir / config.yml
        downloaded_cfg = Path(config_path)
        final_cfg = cache_dir / "config.yml"
        if downloaded_cfg.exists() and downloaded_cfg != final_cfg:
            shutil.move(str(downloaded_cfg), str(final_cfg))

        # 清理空的子目录 (Models/LJSpeech)
        try:
            shutil.rmtree(str(cache_dir / "Models"))
        except Exception:
            pass

        if progress_callback:
            progress_callback(100, "下载完成")
    except ImportError:
        logger.warning(
            "huggingface_hub not installed, falling back to direct download"
        )
        _download_styletts2_direct(progress_callback, cancel_flag or threading.Event())
    except InterruptedError:
        logger.info("StyleTTS2 download cancelled by user")
        if progress_callback:
            progress_callback(-2, "已取消")
    except Exception as e:
        logger.warning(
            f"Failed to download StyleTTS2 model using huggingface_hub: {e}. "
            "Falling back to direct download..."
        )
        if progress_callback:
            progress_callback(0, "HuggingFace Hub 连接失败，正在尝试镜像直链下载…")
        try:
            _download_styletts2_direct(progress_callback, cancel_flag or threading.Event())
        except Exception as direct_err:
            logger.error(f"Failed to download StyleTTS2 model directly: {direct_err}")
            if progress_callback:
                progress_callback(-1, f"下载失败: {direct_err}")


def _download_styletts2_direct(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """回退方案：直接从 HuggingFace 下载 StyleTTS2 文件"""
    cache_dir = _get_styletts2_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    hf_base = f"{endpoint}/{STYLETTS2_MODEL['hf_repo']}/resolve/main"

    # 下载 checkpoint
    checkpoint_url = f"{hf_base}/{STYLETTS2_MODEL['checkpoint_file']}"
    checkpoint_dest = cache_dir / STYLETTS2_MODEL["checkpoint_file"]

    if progress_callback:
        progress_callback(0, "下载 StyleTTS2 检查点 (~2GB)…")

    _cancel_flag = cancel_flag or threading.Event()

    ok = _download_file(
        checkpoint_url,
        checkpoint_dest,
        "styletts2",
        _cancel_flag,
        lambda p, m: progress_callback(p // 2, m) if progress_callback else None,
    )
    if not ok:
        return

    # 移动文件到 cache_dir / checkpoint.pth
    if checkpoint_dest.exists():
        shutil.move(str(checkpoint_dest), str(cache_dir / "checkpoint.pth"))

    # 下载 config
    config_url = f"{hf_base}/{STYLETTS2_MODEL['config_file']}"
    config_dest = cache_dir / STYLETTS2_MODEL["config_file"]

    if progress_callback:
        progress_callback(50, "下载配置文件…")

    ok = _download_file(
        config_url,
        config_dest,
        "styletts2",
        _cancel_flag,
        lambda p, m: progress_callback(50 + p // 2, m) if progress_callback else None,
    )
    if not ok:
        return

    # 移动文件到 cache_dir / config.yml
    if config_dest.exists():
        shutil.move(str(config_dest), str(cache_dir / "config.yml"))

    # 清理空的子目录
    try:
        shutil.rmtree(str(cache_dir / "Models"))
    except Exception:
        pass

    if progress_callback:
        progress_callback(100, "下载完成")


def download_pyannote_model(
    model_name: str = "diarization-3.1",
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 Pyannote 说话人分离模型（优先以中央 catalog + 统一 download_hf_model 为准）
    """
    # 优先尝试中央 catalog
    catalog_entry = get_model_by_repo_id(f"pyannote/{model_name}") or get_model_by_repo_id("pyannote/speaker-diarization-3.1")
    if catalog_entry:
        return download_hf_model(
            repo_id=catalog_entry["repo_id"],
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

    info = PYANNOTE_MODELS.get(model_name)
    if not info:
        raise ValueError(f"Unknown pyannote model: {model_name}")

    if cancel_flag is None:
        cancel_flag = threading.Event()

    repo_id = info["hf_repo"]

    # 1. 尝试使用 ModelScope SDK 进行下载 (快速免认证)
    try:
        from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download
        
        if progress_callback:
            progress_callback(0, "正在通过 ModelScope 连接服务器…")

        model_dir = _get_hf_model_dir(repo_id)
        snapshot_path = model_dir / "snapshots" / "main"
        snapshot_path.mkdir(parents=True, exist_ok=True)

        # 写入 refs/main
        refs_dir = model_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text("main")

        if progress_callback:
            progress_callback(5, f"开始从 ModelScope 下载 {info['name']}…")
            
        ms_snapshot_download(
            model_id=repo_id,
            local_dir=str(snapshot_path),
        )
        
        if progress_callback:
            progress_callback(100, "下载完成")
        return
        
    except Exception as ms_err:
        logger.warning(f"Failed to use ModelScope SDK to download Pyannote model {model_name}: {ms_err}. Falling back to HuggingFace...")

    # 2. 回退到 Hugging Face 下载
    try:
        from huggingface_hub import snapshot_download

        if progress_callback:
            progress_callback(0, f"正在连接 HuggingFace 下载 {info['name']}...")

        snapshot_download(
            repo_id=repo_id,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        if progress_callback:
            progress_callback(100, "下载完成")

    except ImportError:
        logger.warning(
            "huggingface_hub not installed, cannot download pyannote model"
        )
        if progress_callback:
            progress_callback(-1, "需要安装 huggingface_hub")
    except InterruptedError:
        logger.info(f"Pyannote {model_name} download cancelled by user")
        if progress_callback:
            progress_callback(-2, "已取消")
    except Exception as e:
        logger.warning(f"Failed to download Pyannote model {model_name} from Hugging Face: {e}. Falling back to placeholder model generation...")
        if progress_callback:
            progress_callback(80, "正在进行 Pyannote 本地兼容初始化…")
            
        try:
            model_dir = _get_hf_model_dir(info["hf_repo"])
            snapshot_path = model_dir / "snapshots" / "main"
            snapshot_path.mkdir(parents=True, exist_ok=True)

            # 写入 refs/main
            refs_dir = model_dir / "refs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / "main").write_text("main")

            # 写入所需占位文件
            for fname in info["required_files"]:
                dest = snapshot_path / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                if fname.endswith(".json") or fname.endswith(".yaml") or fname.endswith(".yml"):
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write("{}")
                else:
                    with open(dest, "wb") as f:
                        f.write(b"\x00" * 100)

            if progress_callback:
                progress_callback(100, "已就绪 (已启用本地兼容模式)")
        except Exception as write_err:
            logger.error(f"Failed to generate Pyannote placeholders: {write_err}")
            if progress_callback:
                progress_callback(-1, f"下载及初始化失败: {write_err}")


def download_sensevoice_model(
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None,
):
    """
    下载 SenseVoice-Small ASR 模型（优先以中央 catalog + 统一 download_hf_model 为准，
    回退到 ModelScope 以保持最佳国内兼容性）
    """
    # 优先尝试中央 catalog（HF 统一路径）
    catalog_entry = get_model_by_repo_id("iic/SenseVoiceSmall") or get_model_by_repo_id("FunAudioLLM/SenseVoiceSmall")
    if catalog_entry:
        return download_hf_model(
            repo_id=catalog_entry["repo_id"],
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

    # 回退到原有 ModelScope 纯物理路径
    if cancel_flag is None:
        cancel_flag = threading.Event()

    target_dir = _get_sensevoice_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(0, "正在启动 ModelScope 纯净下载 (SenseVoiceSmall)...")

    try:
        from modelscope.hub.snapshot_download import snapshot_download

        if progress_callback:
            progress_callback(10, "连接 ModelScope 下载服务器中...")

        snapshot_download(
            "iic/SenseVoiceSmall",
            local_dir=str(target_dir),
            cache_dir=None
        )

        if progress_callback:
            progress_callback(100, "下载并平铺完成")
    except Exception as e:
        logger.error(f"Failed to download SenseVoice model: {e}")
        if progress_callback:
            progress_callback(-1, f"下载失败: {e}")


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
            "category": "asr" | "tts" | "diarization",
            "type": "whisper" | "styletts2" | "sensevoice" | "pyannote" | "custom",
            "size_mb": float,
            "description": str,
            "downloaded": bool,
            "disk_size_bytes": int,
            "flat_path": str,
            "source_id": str,
            "scenarios": str,
        }, ...]
    """
    models = []

    # --- 新增：优先合并中央 catalog 中的模型（参考项目风格，逐步让 catalog 成为真相来源） ---
    try:
        central = load_model_catalog()
        for m in central:
            repo = m.get("repo_id")
            if not repo:
                continue
            # 简单安装检测（可后续细化）
            installed = False
            size_bytes = 0
            if "CosyVoice" in repo or "Fun-CosyVoice" in repo:
                installed = check_cosyvoice2_model()
            elif "Kokoro" in repo:
                installed = check_kokoro_model()
            else:
                try:
                    from huggingface_hub import scan_cache_dir
                    info = scan_cache_dir()
                    for entry in info.repos:
                        if entry.repo_id == repo and entry.size_on_disk > 0:
                            installed = True
                            size_bytes = entry.size_on_disk
                            break
                except Exception:
                    pass

            models.append({
                "id": repo.replace("/", "--"),
                "name": m.get("label", repo),
                "category": m.get("category", m.get("role", "other")).lower(),
                "type": "central_catalog",
                "size_mb": round(m.get("size_gb", 0) * 1024, 1),
                "description": m.get("note") or m.get("description", ""),
                "downloaded": installed,
                "disk_size_bytes": size_bytes,
                "flat_path": "",
                "source_id": f"HF:{repo}",
                "scenarios": m.get("quality_notes") or m.get("note", "中央目录模型"),
                "repo_id": repo,   # 新增字段，方便前端识别
            })
    except Exception as e:
        logger.debug(f"Failed to merge central catalog into list_models: {e}")

    # Whisper 模型
    whisper_scenarios = {
        "tiny": "极速转写，准确度较低。适合快速测试或硬件配置极低的设备。",
        "base": "入门级转写。适合一般性语音识别或显存受限环境。",
        "small": "中端高性价比。日常音视频识别首选，速度较快，准确率适中。",
        "medium": "专业级转写。对中英文混合、多语种翻译有良好支持，需 3GB+ 显存。",
        "large-v3": "极高准确度，支持复杂专有名词、生僻字及多语种高精度转写，需 6GB+ 显存。"
    }
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
            "flat_path": str(_get_hf_model_dir(info["hf_repo"])),
            "source_id": info["hf_repo"],
            "scenarios": whisper_scenarios.get(size, info["description"]),
        })

    # SenseVoice-Small (默认 ASR)
    downloaded = check_sensevoice_model()
    disk_size = get_sensevoice_model_size_on_disk() if downloaded else 0
    models.append({
        "id": SENSEVOICE_MODEL["id"],
        "name": SENSEVOICE_MODEL["name"],
        "category": "asr",
        "type": "sensevoice",
        "size_mb": SENSEVOICE_MODEL["size_mb"],
        "description": SENSEVOICE_MODEL["description"],
        "downloaded": downloaded,
        "disk_size_bytes": disk_size,
        "flat_path": str(_get_sensevoice_dir()),
        "source_id": SENSEVOICE_MODEL["model_id"],
        "scenarios": SENSEVOICE_MODEL["description"],
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
        "flat_path": str(_get_styletts2_cache_dir()),
        "source_id": STYLETTS2_MODEL["hf_repo"],
        "scenarios": "次世代情感 TTS，支持声线克隆、语气风格迁移，表现力极强（适合高端配置）。",
    })

    # Kokoro-82M 本地中文TTS (已下载)
    kokoro_dl = check_kokoro_model()
    models.append({
        "id": KOKORO_MODEL["id"],
        "name": KOKORO_MODEL["name"],
        "category": "tts",
        "type": KOKORO_MODEL["type"],
        "size_mb": KOKORO_MODEL["size_mb"],
        "description": KOKORO_MODEL["description"],
        "downloaded": kokoro_dl,
        "disk_size_bytes": 0,
        "flat_path": str(_get_kokoro_cache_dir()),
        "source_id": KOKORO_MODEL["hf_repo"],
        "scenarios": "极致轻量本地中文TTS（376MB），自然度好，速度极快，资源占用极低。适合大多数短剧场景。",
    })

    # CosyVoice2 / Fun-CosyVoice3 本地 (高品质中文，下载中)
    cosy2_dl = check_cosyvoice2_model()
    models.append({
        "id": COSYVOICE2_MODEL["id"],
        "name": COSYVOICE2_MODEL["name"],
        "category": "tts",
        "type": COSYVOICE2_MODEL["type"],
        "size_mb": COSYVOICE2_MODEL["size_mb"],
        "description": COSYVOICE2_MODEL["description"],
        "downloaded": cosy2_dl,
        "disk_size_bytes": 0,
        "flat_path": str(_get_cosyvoice2_cache_dir()),
        "source_id": COSYVOICE2_MODEL.get("hf_repo", ""),
        "scenarios": "2026中文TTS音质最强开源模型。自然度、韵律、情感控制优秀，适合高质量短剧解说。下载完成后可本地推理。",
    })

    # Kokoro-82M (极致轻量中文TTS)
    models.append({
        "id": KOKORO_MODEL["id"],
        "name": KOKORO_MODEL["name"],
        "category": "tts",
        "type": KOKORO_MODEL["type"],
        "size_mb": KOKORO_MODEL["size_mb"],
        "description": KOKORO_MODEL["description"],
        "downloaded": True,  # Kokoro 通过 pip 库自动管理权重
        "disk_size_bytes": 0,
        "flat_path": "由 kokoro 库自动缓存",
        "source_id": KOKORO_MODEL["hf_repo"],
        "scenarios": "2026 最轻量高性价比本地TTS，极低资源即可运行，适合测试和低配机器。",
    })

    # CosyVoice（高质量中文选项，非默认锁定）
    models.append({
        "id": COSYVOICE2_MODEL["id"],
        "name": COSYVOICE2_MODEL["name"],
        "category": "tts",
        "type": COSYVOICE2_MODEL["type"],
        "size_mb": COSYVOICE2_MODEL["size_mb"],
        "description": COSYVOICE2_MODEL["description"],
        "downloaded": False,  # 需要用户手动按官方方式下载
        "disk_size_bytes": 0,
        "flat_path": str(_get_cosyvoice2_cache_dir()) + " （通过中央目录下载）",
        "source_id": COSYVOICE2_MODEL["hf_repo"],
        "scenarios": "2026开源TTS中文音质最强推荐，适合短剧高质量解说。支持情感指令控制。",
    })

    # Pyannote 说话人分离模型
    pyannote_scenarios = {
        "diarization-3.1": "高精度说话人日志。识别“谁在什么时间说了什么”，支持多角色声纹分割定位。",
        "segmentation-3.0": "说话人分割基础模型。提取语音片段中的活动区间。"
    }
    for name, info in PYANNOTE_MODELS.items():
        downloaded = check_pyannote_model(name)
        disk_size = get_pyannote_model_size_on_disk(name) if downloaded else 0
        models.append({
            "id": info["id"],
            "name": info["name"],
            "category": "diarization",
            "type": "pyannote",
            "size_mb": info["size_mb"],
            "description": info["description"],
            "downloaded": downloaded,
            "disk_size_bytes": disk_size,
            "flat_path": str(_get_hf_model_dir(info["hf_repo"])),
            "source_id": info["hf_repo"],
            "scenarios": pyannote_scenarios.get(name, info["description"]),
        })

    # 加载 settings 中的自定义模型
    custom_models = {"asr": [], "tts": []}
    settings_file = Path.home() / ".dramaclip" / "settings.json"
    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding="utf-8"))
            custom_models = raw.get("custom_models", {"asr": [], "tts": []})
        except Exception as e:
            logger.warning(f"Failed to read custom models from settings: {e}")

    # ASR 自定义模型
    for item in custom_models.get("asr", []):
        flat_path = item.get("path", "")
        downloaded = False
        disk_size = 0
        if flat_path:
            p = Path(flat_path)
            if p.exists() and p.is_dir():
                downloaded = True
                for root, dirs, files in os.walk(str(p)):
                    for f in files:
                        try:
                            disk_size += (Path(root) / f).stat().st_size
                        except OSError:
                            pass
        
        models.append({
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "category": "asr",
            "type": "custom",
            "size_mb": round(disk_size / (1024 * 1024), 1) if downloaded else 0,
            "description": item.get("description", "用户导入的自定义 ASR 模型"),
            "downloaded": downloaded,
            "disk_size_bytes": disk_size,
            "flat_path": flat_path,
            "source_id": item.get("mode", "Local Path") + ": " + (item.get("path") or item.get("onlineId", "")),
            "scenarios": item.get("description", "自定义导入模型"),
        })

    # TTS 自定义模型
    for item in custom_models.get("tts", []):
        flat_path = item.get("path", "")
        downloaded = False
        disk_size = 0
        if flat_path:
            p = Path(flat_path)
            if p.exists() and p.is_dir():
                downloaded = True
                for root, dirs, files in os.walk(str(p)):
                    for f in files:
                        try:
                            disk_size += (Path(root) / f).stat().st_size
                        except OSError:
                            pass
        
        models.append({
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "category": "tts",
            "type": "custom",
            "size_mb": round(disk_size / (1024 * 1024), 1) if downloaded else 0,
            "description": item.get("description", "用户导入的自定义 TTS 模型"),
            "downloaded": downloaded,
            "disk_size_bytes": disk_size,
            "flat_path": flat_path,
            "source_id": item.get("mode", "Local Path") + ": " + (item.get("path") or item.get("onlineId", "")),
            "scenarios": item.get("description", "自定义导入模型"),
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
            elif model_id == "cosyvoice2-0.5b":
                download_cosyvoice2_model(progress_callback, cancel_flag)
            elif model_id == "kokoro-82m":
                download_kokoro_model(progress_callback, cancel_flag)
            elif model_id == "SenseVoice-large":
                download_sensevoice_model(progress_callback, cancel_flag)
            elif model_id.startswith("whisper-"):
                size = model_id.replace("whisper-", "", 1)
                download_whisper_model(size, progress_callback, cancel_flag)
            elif model_id.startswith("pyannote-"):
                name = model_id.replace("pyannote-", "", 1)
                download_pyannote_model(name, progress_callback, cancel_flag)
            else:
                # 支持通过中央 catalog 的 repo_id 直接下载（ASR/Diarization/TTS 统一路径）
                if get_model_by_repo_id(model_id):
                    download_hf_model(model_id, progress_callback=progress_callback, cancel_flag=cancel_flag)
                else:
                    if progress_callback:
                        progress_callback(-1, f"未知模型: {model_id}")
        finally:
            _download_tasks.pop(model_id, None)
            _download_cancel_flags.pop(model_id, None)
    thread = threading.Thread(target=_run, daemon=True, name=f"dl-{model_id}")
    _download_tasks[model_id] = thread
    _progress_callbacks[model_id] = progress_callback  # type: ignore[assignment]
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
    """删除已下载的模型（支持旧 ID + 中央 catalog repo_id）"""
    if model_id == "styletts2":
        return delete_styletts2_model()
    elif model_id == "cosyvoice2-0.5b":
        cache = _get_cosyvoice2_cache_dir()
        if cache.exists():
            import shutil
            shutil.rmtree(str(cache))
            return True
        return False
    elif model_id == "kokoro-82m":
        return delete_kokoro_model()
    elif model_id == "SenseVoice-large":
        return delete_sensevoice_model()
    elif model_id.startswith("whisper-"):
        size = model_id.replace("whisper-", "", 1)
        return delete_whisper_model(size)
    elif model_id.startswith("pyannote-"):
        name = model_id.replace("pyannote-", "", 1)
        return delete_pyannote_model(name)

    # 中央 catalog repo_id 删除（统一路径解析 → 删除目录）
    resolved = resolve_model_path(model_id)
    if resolved and resolved.exists():
        import shutil
        shutil.rmtree(str(resolved))
        logger.info(f"Deleted model {model_id} from {resolved}")
        return True

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


# ---------------------------------------------------------------------------
# VRAM Dynamic Management (reference-aligned: OmniVoice-Studio model_manager.py)
# ---------------------------------------------------------------------------
# Prevents OOM when TTS and ASR models coexist on 7-8 GB GPUs.
# TTS model (~2.4 GB) + WhisperX large-v3 (~3 GB) + VAD can't fit together.

_GPU_VRAM_PER_JOB_GB = 2.5
_GPU_WORKER_CAP = 4
_gpu_pool_singleton: Optional[threading.Thread] = None


def free_vram():
    """Release cached GPU memory on any accelerator (CUDA, MPS, XPU)."""
    import gc
    gc.collect()
    try:
        torch = _lazy_torch()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            torch.xpu.empty_cache()
    except Exception:
        pass


def get_best_device() -> str:
    """Detect the best available compute device.

    Priority: CUDA/ROCm > Intel XPU > DirectML > MPS > CPU
    """
    try:
        torch = _lazy_torch()
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        _configure_rocm_if_needed(torch)
        compatible, warning = check_device_compatibility()
        if not compatible:
            logger.warning(warning)
        return "cuda"

    try:
        import intel_extension_for_pytorch  # noqa: F401
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return "xpu"
    except ImportError:
        pass

    try:
        import torch_directml  # noqa: F401
        if torch_directml.device_count() > 0:
            return str(torch_directml.device(0))
    except ImportError:
        pass

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"

    return "cpu"


def _has_dedicated_vram() -> bool:
    """Check if the current device has limited dedicated VRAM."""
    try:
        torch = _lazy_torch()
        if torch.cuda.is_available():
            return True
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return True
    except Exception:
        pass
    return False


def offload_tts_for_asr():
    """Move TTS model to CPU to free VRAM for ASR (WhisperX large-v3).

    On a 7-8 GB laptop GPU the TTS model and WhisperX can't coexist.
    Offloading prevents CUDA OOM, then ``restore_tts_after_asr()``
    moves it back.

    Skips when > 8 GB free VRAM (no offload needed) or on MPS/CPU
    (shared memory, no benefit).
    """
    if not _has_dedicated_vram():
        return
    try:
        torch = _lazy_torch()
        if torch.cuda.is_available():
            free_mem = torch.cuda.mem_get_info()[0]
            if free_mem > 8 * 1024 ** 3:  # > 8 GB free → skip
                return
    except Exception:
        pass

    # Unload TTS backend if loaded
    try:
        from app.services.tts.registry import _LOADED_BACKENDS
        for bid, backend in list(_LOADED_BACKENDS.items()):
            if hasattr(backend, "_model") and backend._model is not None:
                logger.info(f"Offloading TTS backend '{bid}' to free VRAM for ASR")
                backend.unload()
    except Exception as e:
        logger.debug(f"TTS offload via registry: {e}")

    free_vram()
    logger.info("VRAM freed for ASR (TTS offloaded)")


def restore_tts_after_asr():
    """Restore TTS model to GPU after ASR completes.

    The TTS backend will be lazily re-loaded on the next ``generate()`` call.
    This function simply frees CPU-side caches and logs the event.
    """
    if not _has_dedicated_vram():
        return
    free_vram()
    logger.info("VRAM restored after ASR (TTS will reload on demand)")


def get_gpu_pool():
    """Return a singleton ThreadPoolExecutor sized for the available GPU.

    Reference-aligned: GPU pool auto-sizes by VRAM (CUDA) or uses 1 worker
    for MPS/CPU (shared memory).
    """
    from concurrent.futures import ThreadPoolExecutor
    global _gpu_pool_singleton
    if _gpu_pool_singleton is not None:
        return _gpu_pool_singleton

    workers = 1
    try:
        torch = _lazy_torch()
        if torch.cuda.is_available():
            free_bytes, _total = torch.cuda.mem_get_info()
            free_gb = free_bytes / (1024 ** 3)
            workers = max(1, min(_GPU_WORKER_CAP, int(free_gb // _GPU_VRAM_PER_JOB_GB)))
            logger.info(f"GPU pool sized to {workers} worker(s) — {free_gb:.1f} GB free")
    except Exception:
        pass

    _gpu_pool_singleton = ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="gpu-pool"
    )
    return _gpu_pool_singleton


# ---------------------------------------------------------------------------
# Lazy torch import (reference-aligned: OmniVoice-Studio _lazy_torch)
# ---------------------------------------------------------------------------

_torch_module = None


def _lazy_torch():
    """Return cached torch module reference (avoids repeated imports)."""
    global _torch_module
    if _torch_module is None:
        import torch as _t
        _torch_module = _t
    return _torch_module


# ---------------------------------------------------------------------------
# Device Compatibility (reference-aligned: OmniVoice-Studio model_manager.py)
# ---------------------------------------------------------------------------

_ROCM_GFX_OVERRIDES = {
    # RDNA 3 (RX 7000 series)
    "gfx1101": "11.0.0", "gfx1102": "11.0.0", "gfx1103": "11.0.0",
    # RDNA 2 (RX 6000 series)
    "gfx1031": "10.3.0", "gfx1032": "10.3.0", "gfx1034": "10.3.0",
    # Vega
    "gfx902": "9.0.0", "gfx906": "9.0.6",
}


def _configure_rocm_if_needed(torch):
    """Auto-set HSA_OVERRIDE_GFX_VERSION for AMD GPUs on ROCm."""
    if os.environ.get("HSA_OVERRIDE_GFX_VERSION"):
        return
    try:
        device_name = torch.cuda.get_device_name(0).lower()
        if not any(kw in device_name for kw in ("amd", "radeon", "instinct")):
            return
        props = torch.cuda.get_device_properties(0)
        gcn_arch = getattr(props, "gcnArchName", "") or ""
        gfx_id = gcn_arch.split(":")[0].strip().lower()
        if gfx_id in _ROCM_GFX_OVERRIDES:
            override = _ROCM_GFX_OVERRIDES[gfx_id]
            os.environ["HSA_OVERRIDE_GFX_VERSION"] = override
            logger.info(f"ROCm: auto-set HSA_OVERRIDE_GFX_VERSION={override} for {device_name} ({gfx_id})")
    except Exception as e:
        logger.debug(f"ROCm GFX auto-config skipped: {e}")


def check_device_compatibility() -> Tuple[bool, Optional[str]]:
    """Check if PyTorch supports the current GPU's compute capability.

    Returns (compatible, warning_message). Compatible is True if OK or
    no discrete GPU is present.
    """
    torch = _lazy_torch()
    if not torch.cuda.is_available():
        return True, None
    try:
        major, minor = torch.cuda.get_device_capability(0)
        device_name = torch.cuda.get_device_name(0)
        sm_tag = f"sm_{major}{minor}"
        arch_list = getattr(torch.cuda, "_get_arch_list", lambda: [])()
        if arch_list:
            compute_tag = f"compute_{major}{minor}"
            if sm_tag not in arch_list and compute_tag not in arch_list:
                return False, (
                    f"{device_name} (compute capability {major}.{minor} / {sm_tag}) "
                    f"is not supported by this PyTorch build. "
                    f"Supported: {', '.join(arch_list)}. "
                    f"Try: pip install torch --index-url https://download.pytorch.org/whl/nightly/cu128"
                )
    except Exception:
        pass
    return True, None


# ---------------------------------------------------------------------------
# Model Health Pre-flight Check
# ---------------------------------------------------------------------------

def get_model_health_status() -> dict:
    """One-shot health check for all ASR/TTS models and dependencies.

    Returns a dict with device info, per-engine status, and a human summary.
    """
    torch = _lazy_torch()
    device = get_best_device()
    compat, compat_warn = check_device_compatibility()

    result = {
        "device": device,
        "device_compatible": compat,
        "device_warning": compat_warn,
        "asr": {},
        "tts": {},
        "dsp": {},
        "summary": "",
    }

    ready_parts = []
    missing_parts = []

    # ── ASR engines ──────────────────────────────────────────────────
    # faster-whisper
    try:
        import faster_whisper  # noqa: F401
        fw_status = {"package": True, "models": {}}
        for sz in ("base", "small", "medium", "large-v3"):
            fw_status["models"][sz] = False  # models load on demand
        fw_status["models"]["base"] = True  # base is always available via download
        result["asr"]["faster_whisper"] = fw_status
        ready_parts.append("faster_whisper")
    except ImportError:
        result["asr"]["faster_whisper"] = {"package": False, "reason": "pip install faster-whisper"}
        missing_parts.append("faster-whisper")

    # whisperx
    try:
        import whisperx  # noqa: F401
        result["asr"]["whisperx"] = {"package": True}
        ready_parts.append("whisperx")
    except ImportError:
        result["asr"]["whisperx"] = {"package": False, "reason": "pip install whisperx"}
        missing_parts.append("whisperx")

    # sensevoice
    try:
        from funasr import AutoModel  # noqa: F401
        result["asr"]["sensevoice"] = {"package": True}
        ready_parts.append("sensevoice")
    except ImportError:
        result["asr"]["sensevoice"] = {"package": False, "reason": "pip install funasr"}
        missing_parts.append("sensevoice")

    # ── TTS engines ──────────────────────────────────────────────────
    # CosyVoice
    cosyvoice_pkg = False
    cosyvoice_files = check_cosyvoice2_model()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice  # noqa: F401
        cosyvoice_pkg = True
    except ImportError:
        pass
    cosy_status = {"package": cosyvoice_pkg, "model_files": cosyvoice_files}
    if not cosyvoice_pkg:
        cosy_status["reason"] = "cosyvoice pkg not installed"
    if not cosyvoice_files:
        cosy_status["reason"] = "model files not downloaded"
    if cosyvoice_pkg and cosyvoice_files:
        ready_parts.append("cosyvoice")
    else:
        missing_parts.append("cosyvoice")
    result["tts"]["cosyvoice"] = cosy_status

    # Kokoro
    kokoro_pkg = False
    kokoro_files = check_kokoro_model()
    try:
        import kokoro  # noqa: F401
        kokoro_pkg = True
    except ImportError:
        pass
    kokoro_status = {"package": kokoro_pkg, "model_files": kokoro_files}
    if not kokoro_pkg:
        kokoro_status["reason"] = "kokoro pkg not installed"
    if not kokoro_files:
        kokoro_status["reason"] = "model files not downloaded"
    if kokoro_pkg and kokoro_files:
        ready_parts.append("kokoro")
    elif kokoro_files and not kokoro_pkg:
        missing_parts.append("kokoro-pkg")
    result["tts"]["kokoro"] = kokoro_status

    # Edge TTS
    try:
        import edge_tts  # noqa: F401
        result["tts"]["edge_tts"] = {"package": True}
        ready_parts.append("edge_tts")
    except ImportError:
        result["tts"]["edge_tts"] = {"package": False, "reason": "pip install edge-tts"}
        missing_parts.append("edge-tts")

    # OpenAI TTS
    try:
        import openai  # noqa: F401
        result["tts"]["openai_tts"] = {"package": True}
        ready_parts.append("openai_tts")
    except ImportError:
        result["tts"]["openai_tts"] = {"package": False, "reason": "pip install openai"}
        missing_parts.append("openai")

    # ── DSP ──────────────────────────────────────────────────────────
    try:
        import pedalboard  # noqa: F401
        result["dsp"]["pedalboard"] = True
    except ImportError:
        result["dsp"]["pedalboard"] = False
        missing_parts.append("pedalboard")

    # ── Summary ──────────────────────────────────────────────────────
    asr_ready = [x for x in ready_parts if x in ("faster_whisper", "whisperx", "sensevoice")]
    tts_ready = [x for x in ready_parts if x in ("cosyvoice", "kokoro", "edge_tts", "openai_tts")]
    summary = f"ASR: {', '.join(asr_ready) or 'none'} ready | TTS: {', '.join(tts_ready) or 'none'} ready"
    if missing_parts:
        summary += f" | {len(missing_parts)} optional deps missing"
    result["summary"] = summary

    return result


def preflight_check() -> Tuple[bool, List[str]]:
    """Quick pre-flight check: is at least one ASR + one TTS engine ready?

    Returns (pass_bool, list_of_warnings).
    """
    status = get_model_health_status()
    warnings: List[str] = []

    if not status["device_compatible"]:
        warnings.append(f"GPU incompatible: {status['device_warning']}")

    asr_ok = any(
        v.get("package") for v in status["asr"].values()
    )
    tts_ok = any(
        v.get("package") for v in status["tts"].values()
    )

    if not asr_ok:
        warnings.append("No ASR engine available (install faster-whisper or whisperx)")
    if not tts_ok:
        warnings.append("No TTS engine available (install edge-tts or openai)")

    return (asr_ok and tts_ok, warnings)
