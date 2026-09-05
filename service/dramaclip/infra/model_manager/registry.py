"""模型清单与状态解析（registry）。

清单 = 引擎所需的已知模型（id/kind/repo/放置目录）；
状态 = placement 目录探测（installed / not_installed），手动放置即生效。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    """一个已知模型的登记项。"""

    model_id: str          # 如 faster-whisper-base
    kind: str              # asr | tts | diarization
    engine: str            # 归属引擎（faster_whisper / sensevoice / kokoro）
    repo_id: str           # ModelScope/HF 仓库 id
    placement: str         # 相对 models_dir 的目录（手动放置位置）
    name: str              # 展示名
    required: bool = False
    notes: str = ""


def builtin_specs() -> list[ModelSpec]:
    return [
        ModelSpec(
            model_id="faster-whisper-base",
            kind="asr",
            engine="faster_whisper",
            repo_id="Systran/faster-whisper-base",
            placement="asr/faster-whisper",
            name="Whisper Base（CPU 快速转写）",
            required=True,
            notes="约 145MB；目录形如 models--Systran--faster-whisper-base/snapshots/<hash>",
        ),
        ModelSpec(
            model_id="faster-whisper-small",
            kind="asr",
            engine="faster_whisper",
            repo_id="Systran/faster-whisper-small",
            placement="asr/faster-whisper",
            name="Whisper Small（更准，稍慢）",
            notes="约 480MB",
        ),
        ModelSpec(
            model_id="sensevoice-small",
            kind="asr",
            engine="sensevoice",
            repo_id="iic/SenseVoiceSmall",
            placement="asr/iic/SenseVoiceSmall",
            name="SenseVoice Small（含情绪标签）",
            notes="约 900MB；需安装 ml 依赖组（torch/funasr）",
        ),
        ModelSpec(
            model_id="kokoro-82m",
            kind="tts",
            engine="kokoro",
            repo_id="hexgrad/Kokoro-82M-v1.1-zh",
            placement="tts/kokoro",
            name="Kokoro 82M 中文（本地 TTS）",
            notes="约 350MB；需安装 kokoro 依赖组（含 espeak-ng）",
        ),
    ]


def _hf_cache_layout(base: Path) -> bool:
    """HF hub 缓存目录特征：models--<org>--<name>/snapshots/<hash>/。"""
    return (base / "snapshots").is_dir() or any(base.glob("models--*"))


def detect_status(models_dir: Path, spec: ModelSpec) -> dict[str, Any]:
    """探测单个模型的安装状态：placement 目录下有实质文件即视为已安装。"""
    base = models_dir / spec.placement
    installed = False
    resolved: Path | None = None
    if base.is_dir():
        if spec.engine == "faster_whisper":
            # HF 缓存布局：placement/models--Systran--faster-whisper-base/snapshots/<hash>
            for cache_dir in base.glob("models--*"):
                for snapshot in sorted((cache_dir / "snapshots").glob("*"), reverse=True):
                    if (snapshot / "model.bin").is_file():
                        installed, resolved = True, snapshot
                        break
                if installed:
                    break
        else:
            has_files = any(item.is_file() for item in base.iterdir())
            installed, resolved = has_files, base
    return {
        "model_id": spec.model_id,
        "kind": spec.kind,
        "engine": spec.engine,
        "repo_id": spec.repo_id,
        "name": spec.name,
        "required": spec.required,
        "notes": spec.notes,
        "status": "installed" if installed else "not_installed",
        "path": str(resolved) if resolved is not None else None,
    }


def list_models(models_dir: Path) -> list[dict[str, Any]]:
    return [detect_status(models_dir, spec) for spec in builtin_specs()]


def find(spec: ModelSpec, models_dir: Path) -> Path | None:
    """已安装则返回可用路径（供引擎加载），否则 None。"""
    status = detect_status(models_dir, spec)
    return Path(status["path"]) if status["path"] is not None else None
