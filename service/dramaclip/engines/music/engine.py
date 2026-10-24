"""ACE-Step 本地 BGM 生成引擎：junction 视图 + 双路径装配（kokoro 同款哲学）。

双路径：进程内 acestep 可导入（dev 手动装了上游包/测试桩）直呼 worker 模块的
setup/generate_one（单一真相，worker 文件自包含可安全被主进程 importlib 加载）；
否则走 music-venv 的 worker 进程（产品态）。

junction 视图：上游按 ``ACESTEP_CHECKPOINTS_DIR`` 下的**注册名子目录**装载
（acestep-v15-sft / vae / Qwen3-Embedding-0.6B / acestep-5Hz-lm-0.6B），而我方
资产库按各自的 placement 独立落盘（体积统计/删除/体检互不污染）。两边名字对不
上，用 Windows 目录联接（``mklink /J``，免管理员）把注册名映射到真实 placement——
联接是链接不是拷贝，零额外磁盘；已存在即跳过，指向失效由生成期报错如实上抛。
"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

from dramaclip.engines.music.generator import GenerateRequest
from dramaclip.infra import compute
from dramaclip.infra.model_manager import music_runtime, worker_bridge
from dramaclip.infra.paths import resolve_data_dir

_LOGGER = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 注册名 → 我方 placement 内的映射目标（相对 models_dir）。键 = 上游在
# checkpoints 根下硬编码查找的目录名，值尾段 = 下载白名单保留的仓库子目录。
_VIEW: dict[str, str] = {
    "acestep-v15-sft": "music/acestep-v15-sft",
    "vae": "music/acestep-vae/vae",
    "Qwen3-Embedding-0.6B": "music/acestep-text-encoder/Qwen3-Embedding-0.6B",
    "acestep-5Hz-lm-0.6B": "music/acestep-5Hz-lm-0.6B",
}

# 生成最低三件套（LM 可选）的文件判据——与 registry required_files 同口径的
# 引擎侧轻探测副本（is_available 只做「在不在」，逐项核对是 registry.verify 的活）
_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "acestep-v15-sft": ("model.safetensors", "config.json"),
    "vae": ("vae/config.json", "vae/diffusion_pytorch_model.safetensors"),
    "Qwen3-Embedding-0.6B": ("Qwen3-Embedding-0.6B/model.safetensors",),
}


def _acestep_importable() -> bool:
    """进程内 acestep 可用（dev 手装/测试桩）；测试经 monkeypatch 本函数切分支。"""
    return importlib.util.find_spec("acestep") is not None


def _worker_module() -> Any:
    from dramaclip.engines.music.workers import acestep_worker

    spec = importlib.util.spec_from_file_location(
        "dramaclip_acestep_worker", Path(acestep_worker.__file__),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_checkpoints_view(models_dir: Path) -> Path:
    """建/复用注册名 junction 视图，返回 checkpoints 根（worker config 消费）。"""
    root = resolve_data_dir() / "runtimes" / "acestep-checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    for name, rel in _VIEW.items():
        target = models_dir / rel
        if not target.is_dir():
            continue  # 组件未装：不建链接，is_available 已挡在生成入口之前
        link = root / name
        if link.exists():
            continue
        result = subprocess.run(  # noqa: S603 - 固定命令受控参数
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, creationflags=_NO_WINDOW, check=False,
        )
        if result.returncode != 0 or not link.exists():
            raise RuntimeError(
                f"配乐模型目录映射失败（{name}）：{result.stderr.strip()[:160]}"
            )
    return root


class AceStepEngine:
    """BGM 单曲生成（duck protocol：is_available/generate/compute）。"""

    def __init__(self, models_dir: Path, device: str = "auto") -> None:
        self._models_dir = models_dir
        self._device = compute.normalize_requested(device)
        self._worker: worker_bridge.VenvWorker | None = None
        self._hello: dict[str, Any] | None = None
        self._inproc_ctx: dict[str, Any] | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "acestep"

    def is_available(self) -> tuple[bool, str]:
        if not _acestep_importable() and not music_runtime.installed(resolve_data_dir()):
            return False, "未装配乐运行环境（引擎页「配乐 BGM · 安装运行环境」）"
        for name, files in _REQUIRED_FILES.items():
            base = self._models_dir / _VIEW[name]
            missing = [f for f in files if not (base / f).is_file()]
            if missing:
                label = "ACE-Step 文本编码器" if name.startswith("Qwen3") else name
                return False, f"缺模型资产 {label}：{', '.join(missing)}（先在引擎页下载）"
        return True, "模型就绪"

    def synthesize(self, request: GenerateRequest, out_dir: Path) -> Path:
        """单曲合成 → 产物 wav 路径（转码入库是 api 层的事）。

        方法名对齐 TTS 侧的 synthesize 而非 generate：api 层的 AST 留痕扫描把
        ``.generate()`` 调用点一律当 LLM 调用核对 trace 参数，配乐引擎不该陪绑。"""
        available, reason = self.is_available()
        if not available:
            raise RuntimeError(reason)
        kwargs = {
            "caption": request.caption,
            "duration_s": request.duration_s,
            "bpm": request.bpm,
            "out_dir": str(out_dir),
        }
        if _acestep_importable():
            produced = self._generate_inproc(kwargs)
        else:
            produced = self._generate_worker(kwargs)
        path = Path(str(produced["path"]))
        if not path.is_file():
            raise RuntimeError(f"worker 回执的产物不存在：{path}")
        return path

    def _generate_inproc(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        module = _worker_module()
        with self._lock:
            if self._inproc_ctx is None:
                self._inproc_ctx = module.setup({
                    "checkpoints": str(_ensure_checkpoints_view(self._models_dir)),
                    "device": self._device,
                })
            produced: dict[str, Any] = module.generate_one(self._inproc_ctx, kwargs)
            return produced

    def _generate_worker(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            worker = self._ensure_worker()
            msg = worker.request({"kwargs": kwargs})
        if not msg.get("ok"):
            raise RuntimeError(f"acestep 生成失败: {msg.get('error')}")
        return msg

    def _ensure_worker(self) -> worker_bridge.VenvWorker:
        if self._worker is not None:
            return self._worker
        from dramaclip.engines.music.workers import acestep_worker

        self._worker = worker_bridge.spawn_venv_worker(
            Path(acestep_worker.__file__),
            {
                "checkpoints": str(_ensure_checkpoints_view(self._models_dir)),
                "device": self._device,
            },
        )
        self._hello = dict(self._worker.ready or {})
        return self._worker

    def compute(self) -> compute.ComputeReport | None:
        hello = self._hello
        if hello is None:
            return None
        actual = "cuda" if str(hello.get("device") or "").startswith("cuda") else "cpu"
        fallback = bool(hello.get("fallback"))
        return compute.ComputeReport(
            component="music.acestep",
            requested=str(hello.get("requested") or self._device),
            resolved="cuda" if actual == "cuda" else "cpu",
            actual=actual,
            fallback=fallback,
            reason=str(hello.get("reason") or ""),
        )
