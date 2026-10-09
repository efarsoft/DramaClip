"""模型清单与状态解析（registry v2）。
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
    # 必需文件集覆盖：同一引擎挂多份资产时（如 paraformer 的主模型与 vad/分离
    # 辅助模型），引擎级 _REQUIREMENTS 表只有一份——覆盖字段让每份资产各判各的。
    required_files: tuple[str, ...] = ()
    # 下载白名单：GGUF 等仓库同仓多量化（F16 单文件 16GB），整仓下载是灾难——
    # 非空时只下载列出的仓库相对路径，体检必需集仍走 required_files。
    download_files: tuple[str, ...] = ()

    def sources(self) -> list[tuple[str, str]]:
        """可用下载源（国内优先排序）：[(kind, repo)]，kind ∈ modelscope/hf_mirror/huggingface。

        空 ``repo_id`` = 该模型没有仓库形式的自动下载源（只能业主自己取回后导入），
        返回空表让调用方明确拒绝下载，而不是拼出一个不存在的 URL。
        """
        out: list[tuple[str, str]] = []
        if self.ms_repo:
            out.append(("modelscope", self.ms_repo))
        if self.repo_id:
            out.append(("hf_mirror", self.repo_id))
            out.append(("huggingface", self.repo_id))
        return out


# 视觉档位的双文件组（主模型 GGUF + mmproj 视觉编码器）：登记/白名单/体检三处共用一份事实。
_VL2B_FILES = ("Qwen3VL-2B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf")
_VL4B_FILES = ("Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf")
_VL8B_FILES = ("Qwen3VL-8B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf")


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
            repo_id="IndexTeam/IndexTTS-2.5",
            ms_repo="IndexTeam/IndexTTS-2.5",
            placement="tts/indextts2",
            name="IndexTTS-2.5（音色克隆+情绪控制）",
            notes="约 5.1GB；建议 N 卡 4GB+ 显存；时长控制+情感解耦，RTF 较 2 提速 2.28 倍",
            size_label="~5.1GB",
            tier="accurate",
            speed=2,
            quality=5,
            desc="B站开源，零样本音色克隆，情绪可自然语言控制",
        ),
        ModelSpec(
            model_id="fun-cosyvoice3-0.5b",
            kind="tts",
            engine="cosyvoice3",
            repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            ms_repo="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            placement="tts/funcosyvoice3",
            name="Fun-CosyVoice3 0.5B（当前开源第一梯队）",
            notes="约 9.75GB（含 RL/base 双底座）；PyTorch 路线老卡可跑；与 300M 共用隔离 venv 桥",
            size_label="~9.75GB",
            tier="accurate",
            speed=2,
            quality=5,
            desc="阿里 FunAudioLLM 最新：零样本克隆、多情感、多语言、流式",
        ),
        ModelSpec(
            model_id="cosyvoice-300m",
            kind="tts",
            engine="cosyvoice",
            repo_id="iic/CosyVoice-300M",
            ms_repo="iic/CosyVoice-300M",
            placement="tts/cosyvoice300m",
            name="CosyVoice 300M（轻量克隆）",
            notes="约 2.6GB；阿里开源（Apache-2.0）；隔离 conda env 桥（引擎页「安装运行环境」）",
            size_label="~5.4GB",
            tier="balanced",
            speed=3,
            quality=4,
            desc="轻量零样本克隆，支持方言与情感控制",
        ),
        ModelSpec(
            model_id="paraformer-large",
            kind="asr",
            engine="paraformer",
            repo_id="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            ms_repo="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            placement="asr/paraformer",
            name="Paraformer-large（FunASR 旗舰）",
            notes="约 880MB；funasr 同栈；CPU RTF ~0.3",
            size_label="~880MB",
            tier="balanced",
            speed=4,
            quality=4,
            desc="阿里 FunASR 旗舰，中文准确率高、自带标点、CPU 友好",
        ),
        ModelSpec(
            model_id="fsmn-vad",
            kind="asr",
            engine="paraformer",
            repo_id="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            ms_repo="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            placement="asr/fsmn-vad",
            name="FSMN-VAD（语音活动检测）",
            notes="约 1MB；说话人分离的前置（嵌入按语音区间提取，无 VAD 没有输入窗）",
            size_label="~1MB",
            tier="fast",
            speed=5,
            quality=4,
            desc="切出有语音的区间；paraformer 说话人分离必需",
            required_files=("config.yaml", "model.pt"),
        ),
        ModelSpec(
            model_id="campplus-sv",
            kind="asr",
            engine="paraformer",
            repo_id="iic/speech_campplus_sv_zh-cn_16k-common",
            ms_repo="iic/speech_campplus_sv_zh-cn_16k-common",
            placement="asr/campplus",
            name="CAM++（说话人分离/角色聚类）",
            notes="约 28MB；funasr 内置聚类自动判人数（1~15），asr.num_speakers 可指定",
            size_label="~28MB",
            tier="fast",
            speed=5,
            quality=4,
            desc="声纹嵌入+聚类，把台词按角色聚类并标注说话人（角色A/B…）",
            required_files=("campplus_cn_common.bin",),
        ),
        # ---- 视觉轨（vision）：Qwen3-VL 三档，GGUF+mmproj 双文件（管理先行，运行接入见 P2b）----
        ModelSpec(
            model_id="qwen3-vl-2b",
            kind="vision",
            engine="qwen3_vl",
            repo_id="Qwen/Qwen3-VL-2B-Instruct-GGUF",
            ms_repo="Qwen/Qwen3-VL-2B-Instruct-GGUF",
            placement="vl/qwen3-vl-2b",
            name="Qwen3-VL 2B（视觉·轻量档）",
            notes="主模型 + mmproj 视觉编码器双文件；运行需 llama.cpp（接入中）",
            size_label="~1.6GB",
            tier="fast",
            speed=5,
            quality=2,
            desc="逐集拼图画面理解·轻量档：16GB 内存机器可跑，弱机/尝鲜",
            required_files=_VL2B_FILES,
            download_files=_VL2B_FILES,
        ),
        ModelSpec(
            model_id="qwen3-vl-4b",
            kind="vision",
            engine="qwen3_vl",
            repo_id="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            ms_repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            placement="vl/qwen3-vl-4b",
            name="Qwen3-VL 4B（视觉·均衡档）",
            notes="主模型 + mmproj 视觉编码器双文件；运行需 llama.cpp（接入中）",
            size_label="~3GB",
            tier="balanced",
            speed=4,
            quality=3,
            desc="逐集拼图画面理解·均衡档：默认推荐候选，真机 CPU 一张拼图约 15~30 秒",
            required_files=_VL4B_FILES,
            download_files=_VL4B_FILES,
        ),
        ModelSpec(
            model_id="qwen3-vl-8b",
            kind="vision",
            engine="qwen3_vl",
            repo_id="Qwen/Qwen3-VL-8B-Instruct-GGUF",
            ms_repo="Qwen/Qwen3-VL-8B-Instruct-GGUF",
            placement="vl/qwen3-vl-8b",
            name="Qwen3-VL 8B（视觉·高配档）",
            notes="主模型 + mmproj 视觉编码器双文件；运行需 llama.cpp（接入中）",
            size_label="~5.8GB",
            tier="accurate",
            speed=3,
            quality=4,
            desc="逐集拼图画面理解·高配档：32GB+ 内存机器",
            required_files=_VL8B_FILES,
            download_files=_VL8B_FILES,
        ),
    ]


def _hf_cache_layout(base: Path) -> bool:
    """HF hub 缓存目录特征：models--<org>--<name>/snapshots/<hash>/。"""
    return (base / "snapshots").is_dir() or any(base.glob("models--*"))


def whisper_cache(base: Path, spec: ModelSpec) -> Path | None:
    """placement 下该档位自己的缓存根（四个 whisper 档位共用 placement，必须按档切分）。"""
    return _whisper_cache(base, spec)


def detect_status(models_dir: Path, spec: ModelSpec) -> dict[str, Any]:
    """探测单个模型的安装状态：placement 目录下有实质文件即视为已安装。"""
    base = models_dir / spec.placement
    installed = False
    resolved: Path | None = None
    asset: Path | None = None
    if base.is_dir():
        if spec.engine == "faster_whisper":
            # HF 缓存布局，模型级精确探测：
            # placement/models--Systran--faster-whisper-<size>/snapshots/<hash>/model.bin
            # 快照枚举序见 _snapshot_candidates（与引擎加载同口径）。
            short = spec.model_id.removeprefix("faster-whisper-")
            for cache_dir in sorted(base.glob(f"models--*faster-whisper-{short}")):
                for snapshot in _snapshot_candidates(cache_dir):
                    if (snapshot / "model.bin").is_file():
                        installed, resolved, asset = True, snapshot, cache_dir
                        break
                if installed:
                    break
        else:
            # 通用：目录树内（含子目录）任一模型权重文件即已安装
            for pattern in ("*.pth", "*.pt", "*.bin", "*.onnx", "*.safetensors"):
                hit = next(base.rglob(pattern), None)
                if hit is not None:
                    installed, resolved, asset = True, base, base
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
        # 磁盘实占：按「这份资产自己的目录」统计（whisper 是缓存根，权重实体在 blobs/ 下），
        # 不是清单里的标称大小，也不把同 placement 的邻居档位算进来。
        "size_bytes": _dir_bytes(asset) if asset is not None else 0,
        "engine_ready": engine_ready(spec),
    }


def _dir_bytes(root: Path) -> int:
    """目录树内全部普通文件字节数之和。"""
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def engine_ready(spec: ModelSpec) -> bool:
    """该模型归属的合成/识别路径是否真接进了工厂——「可用」与「储备」的唯一判据。

    名单只存在于两处：``engines/tts/factory.supported()`` 与
    ``engines/analysis/runtime.supported()``。这里只做查表，不再抄一份。
    """
    if spec.kind == "tts":
        from dramaclip.engines.tts.factory import supported
    elif spec.kind == "asr":
        from dramaclip.engines.analysis.runtime import supported
    else:
        return False
    return spec.engine in supported()


# 每引擎的必需相对路径（相对「模型根目录」；含 * 者按一次通配匹配，目录直接写名字）。
_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "faster_whisper": ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"),
    "sensevoice": ("model.pt",),
    # funasr AutoModel 从本地目录加载的最低判据：权重在场（config.yaml 由 AutoModel
    # 缺省兜底）。与 sensevoice 同栈同判（engines/analysis/transcriber.ParaformerEngine）。
    "paraformer": ("model.pt",),
    "kokoro": (
        "Kokoro-82M-v1.1-zh/config.json",
        "Kokoro-82M-v1.1-zh/*.pth",
        "Kokoro-82M-v1.1-zh/voices",
    ),
    # worker 加载三件套（engines/tts/workers/indextts_worker.py：cfg_path=config.yaml，
    # IndexTTS2 按 config 再取 gpt/s2mel 权重）。bpe.model 官方 2.5 仓库不带，不列判据。
    "indextts2": ("config.yaml", "gpt.pth", "s2mel.pth"),
    # CosyVoice 三件套权重 + zero/cross 两种克隆模式都要用的语音 tokenizer onnx。
    # 文件清单量自 HF FunAudioLLM/CosyVoice-300M 主分支（2026-09-24）。
    "cosyvoice": ("cosyvoice.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v1.onnx"),
    # v3 与 300M 的差异：cosyvoice3.yaml + speech_tokenizer_v3.onnx + CosyVoice-BlankEN/
    # 目录（文本前端词表）。清单量自 HF Fun-CosyVoice3-0.5B-2512（本机验证组合的取文件集）。
    "cosyvoice3": ("cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx"),
}
_WEIGHT_SUFFIXES = (".bin", ".pth", ".pt", ".onnx", ".safetensors", ".gguf")
_HEX = set("0123456789abcdef")


def _whisper_cache(base: Path, spec: ModelSpec) -> Path | None:
    short = spec.model_id.removeprefix("faster-whisper-")
    for cache in sorted(base.glob(f"models--*faster-whisper-{short}")):
        if cache.is_dir():
            return cache
    return None


def _whisper_snapshot(cache: Path) -> Path | None:
    """优先按 refs/main 指向的快照；没有 ref 时退回目录名倒序的第一个（与探测同序）。"""
    ref = cache / "refs" / "main"
    if ref.is_file():
        try:
            named = cache / "snapshots" / ref.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if named.is_dir():
            return named
    candidates = [p for p in sorted((cache / "snapshots").glob("*"), reverse=True) if p.is_dir()]
    return candidates[0] if candidates else None


def _snapshot_candidates(cache: Path) -> list[Path]:
    """快照目录枚举序：refs/main 解析出的那个排最前，其余按名字倒序兜底。

    detect_status 与引擎加载必须同口径：refs 指向谁就优先信谁，
    否则「体检报的修订」与「引擎真加载的修订」可能不是同一份。
    """
    preferred = _whisper_snapshot(cache)
    rest = sorted((cache / "snapshots").glob("*"), reverse=True)
    if preferred is None:
        return rest
    return [preferred] + [path for path in rest if path != preferred]


def _missing_requirements(root: Path, required: tuple[str, ...]) -> list[str]:
    missing = []
    for pattern in required:
        if "*" in pattern:
            if not any(p.is_file() for p in root.glob(pattern)):
                missing.append(pattern)
        elif not (root / pattern).exists():
            missing.append(pattern)
    return missing


def requirements(engine: str) -> tuple[str, ...]:
    """该引擎的必需文件集（相对模型根目录）——体检与导入向导共用同一份判据。"""
    return _REQUIREMENTS.get(engine, ())


def missing_requirements(root: Path, required: tuple[str, ...]) -> list[str]:
    """按必需文件集核对一个目录，返回缺项（``*`` 者按一次通配匹配）。"""
    return _missing_requirements(root, required)


def whisper_snapshot(cache: Path) -> Path | None:
    """HF 缓存里已解析出的快照目录；导入识别与体检都只认这一个解析规则。"""
    return _whisper_snapshot(cache)


def verify(models_dir: Path, spec: ModelSpec) -> dict[str, Any]:
    """资产体检：逐项判据，任何一项 ``fail`` 都不许被当成「可用」。

    为什么不复用 ``detect_status`` 的 ``status``：那个判据是「placement 下存在一个权重
    文件」，下载中断留下的半截目录一样过。这里按引擎各自的必需文件、快照提交号、
    下载清单、中断残留、重复缓存五道查，全部有真机形态对应
    （见 tests/infra/model_manager/test_verify.py 的模块 docstring）。
    """
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str = "", *, paths: list[str] | None = None) -> None:
        # paths：给修复动作用的结构化白名单（如「删除多余副本」只删这里列出的路径）。
        # 文案里的路径是给人读的，动作不能靠解析文案——所以单独带字段。
        check: dict[str, Any] = {"name": name, "status": status, "detail": detail}
        if paths:
            check["paths"] = paths
        checks.append(check)

    base = models_dir / spec.placement
    # cache 只在 faster_whisper 下算得出：非 None 即等价于「这是 HF 缓存布局的模型」。
    cache = _whisper_cache(base, spec) if spec.engine == "faster_whisper" else None
    snapshot = _whisper_snapshot(cache) if cache is not None else None

    if not base.is_dir():
        add("目录存在", "fail", f"未找到 {base}")
        add("必需文件", "skip", "目录不存在，未继续")
    elif cache is None and spec.engine == "faster_whisper":
        add("目录存在", "pass", str(base))
        add("必需文件", "fail", f"{base} 下没有 {spec.repo_id.replace('/', '--')} 缓存目录")
    else:
        add("目录存在", "pass", str(base))
        required = spec.required_files or _REQUIREMENTS.get(spec.engine, ())
        root = snapshot if snapshot is not None else base
        if cache is not None and snapshot is None:
            add("必需文件", "fail", f"{cache} 下没有已解析的快照目录（snapshots/<提交号>）")
        else:
            missing = _missing_requirements(root, required)
            if missing:
                add("必需文件", "fail", f"缺 {', '.join(missing)}")
            else:
                add("必需文件", "pass", f"{len(required)} 项齐全")
        if root.is_dir():
            _verify_weights(root, add)
        if cache is not None:
            _verify_snapshot_revision(cache, snapshot, add)
            _verify_manifest(cache, snapshot, add)
    _verify_residue(cache if cache is not None else base, add)
    _verify_unique_path(models_dir, base, cache, add)
    if not engine_ready(spec):
        add("引擎接入", "warn", f"{spec.engine} 尚未接入，只能作为储备资产")
    return {
        "model_id": spec.model_id,
        "name": spec.name,
        "kind": spec.kind,
        "engine": spec.engine,
        "engine_ready": engine_ready(spec),
        "path": str(base),
        "ok": not any(check["status"] == "fail" for check in checks),
        "checks": checks,
    }


def weight_files(root: Path) -> list[Path]:
    """目录树内的权重文件——体检与导入共用同一份扩展名表，不各抄一份。"""
    return [path for path in root.rglob("*") if path.suffix in _WEIGHT_SUFFIXES and path.is_file()]


def _verify_weights(root: Path, add: Any) -> None:
    weights = weight_files(root)
    if not weights:
        add("权重非空", "fail", "目录里没有任何权重文件")
        return
    largest = max(weights, key=lambda p: p.stat().st_size)
    if largest.stat().st_size <= 0:
        add("权重非空", "fail", f"全部权重文件都是 0 字节（{len(weights)} 个）")
        return
    add("权重非空", "pass", f"{largest.name} {largest.stat().st_size / 1024 / 1024:.1f}MB")


def _verify_snapshot_revision(cache: Path, root: Path | None, add: Any) -> None:
    """refs/main 与快照目录名的一致性判据（severity 划分按规格 §10.1）。

    - **fail**：refs 与快照不一致（两个权威对「加载哪个修订」意见不同，是真矛盾）；
      或目录名非提交号**却有** trees 清单（清单自称可对账，与目录名互相打脸）。
    - **warn**：目录名非提交号且无清单——下载时解析不到提交号的退化形态（多为
      下载器自己制造，不是手动放置），无从逐文件对账 ≠ 权重缺损，能不能加载
      留给能力层自检，不在文件层判死。
    """
    name = root.name if root is not None else ""
    ref = cache / "refs" / "main"
    content = ref.read_text(encoding="utf-8", errors="replace").strip() if ref.is_file() else None
    if content is not None and content != name:
        add(
            "快照提交号",
            "fail",
            f"refs/main={content!r} 与快照 {name!r} 不一致——加载哪个修订两个权威意见不同",
        )
        return
    if len(name) == 40 and all(char in _HEX for char in name):
        add("快照提交号", "pass", name[:12])
        return
    has_trees = (cache / "trees").is_dir() and any((cache / "trees").glob("*.json"))
    if has_trees:
        add(
            "快照提交号",
            "fail",
            f"有 trees 清单但快照目录名不是提交号：{name or '（无）'}——清单与目录名互相矛盾",
        )
        return
    add(
        "快照提交号",
        "warn",
        f"快照目录名不是提交号：{name or '（无）'}——无从按上游修订逐文件对账；"
        "权重齐全仍可用，建议就地迁移或重新下载",
    )


def _verify_manifest(cache: Path, root: Path | None, add: Any) -> None:
    """HF 的 ``trees/<rev>.json`` 是逐文件对账的依据；没有它只能信「文件在」。"""
    rev = root.name if root is not None else ""
    if (cache / "trees" / f"{rev}.json").is_file():
        add("下载清单", "pass", f"trees/{rev[:12]}.json")
    else:
        add("下载清单", "warn", "无 trees 清单，无法逐文件对账（可能是手动放置）")


def _verify_residue(scope: Path, add: Any) -> None:
    """下载残留是卫生问题不是可用性缺陷（规格 §10.1 fail→warn）。

    体检从头到尾不碰权重本身，残留也不参与推理——它只占磁盘。把它判成「不完整」
    等于让 192MB 的垃圾文件禁掉一份 483MB 完好权重的「选为生效」；正确形态是
    warn 上卡 + 「清理残留」动作（clean_residue 的删除范围与本判据同一口径）。
    """
    leftovers = [path for path in scope.rglob("*.incomplete") if path.is_file()]
    if leftovers:
        total = sum(p.stat().st_size for p in leftovers) / 1024 / 1024
        add(
            "中断残留",
            "warn",
            f"{len(leftovers)} 个 .incomplete 半截文件（{total:.0f}MB）——上次下载中断的残留，"
            "占磁盘但不参与推理，可安全清理",
        )
        return
    add("中断残留", "pass", "无 .incomplete 残留")


def _looks_like_assets(path: Path) -> bool:
    """目录里确实放着模型：HF 缓存骨架，或任一权重文件。锁目录/空壳目录不算。"""
    if (path / "snapshots").is_dir() or (path / "blobs").is_dir():
        return True
    return any(f.suffix in _WEIGHT_SUFFIXES for f in path.rglob("*") if f.is_file())


def _verify_unique_path(models_dir: Path, base: Path, cache: Path | None, add: Any) -> None:
    """同一份缓存出现在第二个路径：引擎只会读登记路径那份，另一份纯占磁盘。

    只数「目录里真有模型」的：``models/.locks/models--…`` 与登记项同名却是 hf_hub 的空锁
    目录，按名字判重复会把每个正常模型都报成脏。
    """
    probe = cache.name if cache is not None else base.name
    own = cache if cache is not None else base
    others = [
        path
        for path in models_dir.rglob(probe)
        if path != own and _looks_like_assets(path)
    ]
    if others:
        shown = ", ".join(str(o) for o in others[:2])
        add(
            "唯一路径",
            "warn",
            f"另有 {len(others)} 处同名缓存：{shown}",
            paths=[str(o) for o in others],
        )
        return
    add("唯一路径", "pass", "仅登记路径一份")


# --------------------------------------------------------------------------- 修复动作的判定口径
# 「清理残留」「删除多余副本」的删除范围必须与体检判据**同一条**——否则清完再校验还是红，
# 动作就成了摆设（规格 §10.2）。判定放这里（体检旁），api 层只做参数校验与删除执行。


def residue_files(models_dir: Path, spec: ModelSpec) -> list[Path]:
    """该资产的中断残留清单：与 ``_verify_residue`` 的作用域同一条。

    whisper 按自己的缓存根切分（四档共用 placement，不能替邻居删），其余按 placement 根。
    """
    base = models_dir / spec.placement
    scope: Path | None = base
    if spec.engine == "faster_whisper":
        scope = _whisper_cache(base, spec)
    if scope is None or not scope.is_dir():
        return []
    return [path for path in scope.rglob("*.incomplete") if path.is_file()]


def orphan_copies(models_dir: Path, spec: ModelSpec) -> list[Path]:
    """登记路径之外的同名缓存（与 ``_verify_unique_path`` 同一探法）——删除入口的白名单。

    只列 models_dir 之内的；外面 world 的目录一个字节都不碰。
    """
    base = models_dir / spec.placement
    if not base.is_dir():
        return []
    cache = _whisper_cache(base, spec) if spec.engine == "faster_whisper" else None
    probe = cache.name if cache is not None else base.name
    own = cache if cache is not None else base
    return [
        path
        for path in models_dir.rglob(probe)
        if path != own and _looks_like_assets(path)
    ]


def list_models(models_dir: Path) -> list[dict[str, Any]]:
    return [detect_status(models_dir, spec) for spec in builtin_specs()]


def find(spec: ModelSpec, models_dir: Path) -> Path | None:
    """已安装则返回可用路径（供引擎加载），否则 None。"""
    status = detect_status(models_dir, spec)
    return Path(status["path"]) if status["path"] is not None else None
