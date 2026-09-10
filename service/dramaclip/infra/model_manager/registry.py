"""模型清单与状态解析（registry v2）。

清单 = 引擎所需的已知模型（id/kind/repo/放置目录/档位与评级元数据）；
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
    repo_id: str           # HuggingFace 仓库 id
    placement: str         # 相对 models_dir 的目录（手动放置位置）
    name: str              # 展示名
    required: bool = False
    notes: str = ""
    ms_repo: str = ""      # ModelScope 仓库 id（空 = 该模型无 ModelScope 源）
    # ---- v2 展示元数据 ----
    size_label: str = ""   # 体积说明（如 "~480MB"）
    tier: str = ""         # fast | balanced | accurate（档位分组）
    speed: int = 0         # 速度评级 1-5（5 最快）
    quality: int = 0       # 精度评级 1-5（5 最准）
    desc: str = ""         # 一句话定位

    def sources(self) -> list[tuple[str, str]]:
        """可用下载源（国内优先排序）：[(kind, repo)]，kind ∈ modelscope/hf_mirror/huggingface。"""
        out: list[tuple[str, str]] = []
        if self.ms_repo:
            out.append(("modelscope", self.ms_repo))
        out.append(("hf_mirror", self.repo_id))
        out.append(("huggingface", self.repo_id))
        return out


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
            notes="目录形如 models--Systran--faster-whisper-base/snapshots/<hash>",
            size_label="~145MB",
            tier="fast",
            speed=4,
            quality=3,
            desc="快速转写，日常够用",
        ),
        ModelSpec(
            model_id="faster-whisper-small",
            kind="asr",
            engine="faster_whisper",
            repo_id="Systran/faster-whisper-small",
            placement="asr/faster-whisper",
            name="Whisper Small（更准，稍慢）",
            notes="约 480MB",
            size_label="~480MB",
            tier="balanced",
            speed=3,
            quality=4,
            desc="速度与准确度的平衡点",
        ),
        ModelSpec(
            model_id="faster-whisper-medium",
            kind="asr",
            engine="faster_whisper",
            repo_id="Systran/faster-whisper-medium",
            placement="asr/faster-whisper",
            name="Whisper Medium（高准确度）",
            size_label="~1.5GB",
            tier="accurate",
            speed=2,
            quality=4,
            desc="更准，CPU 上较慢",
        ),
        ModelSpec(
            model_id="faster-whisper-large-v3",
            kind="asr",
            engine="faster_whisper",
            repo_id="Systran/faster-whisper-large-v3",
            placement="asr/faster-whisper",
            name="Whisper Large-v3（最高精度）",
            size_label="~3GB",
            tier="accurate",
            speed=1,
            quality=5,
            desc="精度天花板，建议 GPU",
        ),
        ModelSpec(
            model_id="sensevoice-small",
            kind="asr",
            engine="sensevoice",
            repo_id="iic/SenseVoiceSmall",
            ms_repo="iic/SenseVoiceSmall",
            placement="asr/iic/SenseVoiceSmall",
            name="SenseVoice Small（含情绪标签）",
            notes="约 900MB；需安装 ml 依赖组（torch/funasr）",
            size_label="~900MB",
            tier="balanced",
            speed=4,
            quality=4,
            desc="含情绪标签，需 ml 依赖组",
        ),
        ModelSpec(
            model_id="kokoro-82m",
            kind="tts",
            engine="kokoro",
            repo_id="hexgrad/Kokoro-82M-v1.1-zh",
            placement="tts/kokoro",
            name="Kokoro 82M 中文（本地 TTS）",
            notes="约 350MB；需安装 kokoro 依赖组（含 espeak-ng）",
            size_label="~350MB",
            tier="balanced",
            speed=3,
            quality=4,
            desc="中文离线配音",
        ),
        ModelSpec(
            model_id="indextts2",
            kind="tts",
            engine="indextts2",
            repo_id="IndexTeam/IndexTTS-2",
            ms_repo="IndexTeam/IndexTTS-2",
            placement="tts/indextts2",
            name="IndexTTS2（音色克隆+情绪控制）",
            notes="约 5.5GB；建议 N 卡 4GB+ 显存；毫秒级时长控制",
            size_label="~5.5GB",
            tier="accurate",
            speed=2,
            quality=5,
            desc="B站开源，零样本音色克隆，情绪可自然语言控制",
        ),
        ModelSpec(
            model_id="vibevoice-1.5b",
            kind="tts",
            engine="vibevoice",
            repo_id="microsoft/VibeVoice-1.5B",
            placement="tts/vibevoice",
            name="VibeVoice 1.5B（多角色）",
            notes="约 5GB；建议 N 卡；多角色对话合成（微软，MIT）",
            size_label="~5GB",
            tier="accurate",
            speed=2,
            quality=4,
            desc="最多 4 角色对话式配音，适合双人对谈",
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
            # HF 缓存布局，模型级精确探测：
            # placement/models--Systran--faster-whisper-<size>/snapshots/<hash>/model.bin
            short = spec.model_id.removeprefix("faster-whisper-")
            for cache_dir in sorted(base.glob(f"models--*faster-whisper-{short}")):
                for snapshot in sorted((cache_dir / "snapshots").glob("*"), reverse=True):
                    if (snapshot / "model.bin").is_file():
                        installed, resolved = True, snapshot
                        break
                if installed:
                    break
        else:
            # 通用：目录树内（含子目录）任一模型权重文件即已安装
            for pattern in ("*.pth", "*.pt", "*.bin", "*.onnx", "*.safetensors"):
                hit = next(base.rglob(pattern), None)
                if hit is not None:
                    installed, resolved = True, base
                    break
    return {
        "model_id": spec.model_id,
        "kind": spec.kind,
        "engine": spec.engine,
        "repo_id": spec.repo_id,
        "name": spec.name,
        "required": spec.required,
        "notes": spec.notes,
        "size_label": spec.size_label,
        "tier": spec.tier,
        "speed": spec.speed,
        "quality": spec.quality,
        "desc": spec.desc,
        "sources": [{"kind": kind, "repo": repo} for kind, repo in spec.sources()],
        "status": "installed" if installed else "not_installed",
        "path": str(resolved) if resolved is not None else None,
    }


def list_models(models_dir: Path) -> list[dict[str, Any]]:
    return [detect_status(models_dir, spec) for spec in builtin_specs()]


def find(spec: ModelSpec, models_dir: Path) -> Path | None:
    """已安装则返回可用路径（供引擎加载），否则 None。"""
    status = detect_status(models_dir, spec)
    return Path(status["path"]) if status["path"] is not None else None
