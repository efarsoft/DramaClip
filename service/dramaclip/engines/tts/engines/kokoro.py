"""Kokoro 本地 TTS 引擎（82M v1.1-zh，24kHz）。
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any

from dramaclip.engines.tts.base import EngineCaps
from dramaclip.engines.tts.text_split import split_long_text
from dramaclip.infra import compute
from dramaclip.infra.model_manager import worker_bridge
from dramaclip.infra.paths import resolve_data_dir

_SAMPLE_RATE = 24000

#: 模型加载判据文件（与 registry._REQUIREMENTS 的 kokoro 条目同口径的引擎侧副本：
#: is_available 只做「在不在」的轻探测，不逐文件核对——那是 registry.verify 的活）。
_REQUIRED_FILES = ("config.json", "kokoro-v1_1-zh.pth")


def _venv_kokoro_installed() -> bool:
    """本地智能运行环境的 kokoro 组判据（零探针文件检查，同 funasr 组哲学）。"""
    venv = resolve_data_dir() / "runtimes" / "tts-venv"
    return (venv / "Lib" / "site-packages" / "kokoro" / "__init__.py").is_file()


def _kokoro_importable() -> bool:
    """进程内 kokoro 可用（dev ml 组/测试桩）；测试经 monkeypatch 本函数切分支。"""
    return importlib.util.find_spec("kokoro") is not None


def _probe_torch_device(requested: str) -> tuple[str, str]:
    """最小 CUDA 运算探针：老卡被认出但新栈无内核，加载大模型才崩。"""
    if requested == "cpu":
        return "cpu", ""
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda", ""
    except Exception as exc:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理
        torch.cuda.empty_cache()
        return "cpu", f"{type(exc).__name__}: {exc}"


class KokoroEngine:
    """实现 TtsEngine 协议（duck typing）。

    双路径装配（E-2，与 transcriber 的 funasr 同款）：进程内 kokoro 可用
    （dev ml 组/测试桩）走 KPipeline 直呼；不可用（打包态）走 tts-venv 的
    kokoro worker——切块留主进程（split_long_text 单一真相），整块列表一次
    请求，拼接落盘在 worker 端 numpy 完成。
    """

    def __init__(self, model_dir: Path, device: str = "auto") -> None:
        self._model_dir = model_dir
        self._device = compute.normalize_requested(device)
        self._pipeline: Any | None = None
        self._worker: worker_bridge.VenvWorker | None = None
        self._hello: dict[str, Any] | None = None
        self._actual_device: str | None = None
        self._fallback_reason = ""
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "kokoro"

    def capabilities(self) -> EngineCaps:
        available, reason = self.is_available()
        return EngineCaps(
            sample_rate=_SAMPLE_RATE,  # sf.write 的落盘采样率，与合成输出同源
            supports_cloning=False,  # 固定音色表（voices/*.pt），无参考音频入口
            supports_emotion=False,
            # 量自 KPipeline.__call__ 签名：speed: Number = 1
            speed_control="native",
            available=available,
            reason=reason,
        )

    def is_available(self) -> tuple[bool, str]:
        if not _kokoro_importable() and not _venv_kokoro_installed():
            return False, "未装运行环境：需要本地智能运行环境（引擎页「安装运行环境」）"
        missing = [
            name for name in _REQUIRED_FILES if not (self._model_dir / name).is_file()
        ]
        if missing:
            return False, f"缺模型：{self._model_dir} 下没有 {', '.join(missing)}（先下载或导入）"
        return True, "模型就绪"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        voice_pt = self._resolve_voice(voice)

        # B7 长文本：先按统一规则切块（kokoro 的 pipeline 内部也切，但它按 '\n+' 切，
        # 对无换行的长段是一次整段推理——显式切块让超长文本的内存与耗时可控）。
        chunks, dropped = split_long_text(text)
        pieces = chunks if len(chunks) > 1 else [text]
        if dropped:
            logging.getLogger(__name__).info(
                "kokoro 长文本切分丢弃 %d 个空块（%d 块合成）", dropped, len(pieces)
            )

        if _kokoro_importable():
            self._synthesize_inproc(pieces, voice_pt, out_path)
        else:
            self._synthesize_worker(pieces, voice_pt, out_path)
        return out_path

    def _synthesize_inproc(self, pieces: list[str], voice_pt: Path, out_path: Path) -> None:
        import numpy as np
        import soundfile as sf

        pipeline = self._ensure_pipeline()
        segments: list[Any] = []
        with self._lock:
            for piece in pieces:
                for _gs, _ps, audio in pipeline(piece, voice=str(voice_pt)):
                    segments.append(np.asarray(audio))
        audio_np = (
            np.concatenate(segments) if segments else np.zeros(0, dtype="float32")
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), audio_np, _SAMPLE_RATE)

    def _synthesize_worker(self, pieces: list[str], voice_pt: Path, out_path: Path) -> None:
        with self._lock:
            worker = self._ensure_worker()
            msg = worker.request({
                "kwargs": {
                    "pieces": pieces,
                    "voice_pt": str(voice_pt),
                    "out": str(out_path),
                },
            })
        if not msg.get("ok"):
            raise RuntimeError(f"kokoro 合成失败: {msg.get('error')}")

    def _ensure_worker(self) -> worker_bridge.VenvWorker:
        if self._worker is not None:
            return self._worker
        from dramaclip.engines.tts.workers import kokoro_worker

        self._worker = worker_bridge.spawn_venv_worker(
            Path(kokoro_worker.__file__),
            {"model_dir": str(self._model_dir), "device": self._device},
        )
        self._hello = dict(self._worker.ready or {})
        return self._worker

    def _resolve_voice(self, voice: str) -> Path:
        voice_name = voice or "zf_001"
        voice_pt = self._model_dir / "voices" / f"{voice_name}.pt"
        if not voice_pt.is_file():
            voice_pt = self._model_dir / "voices" / "zf_001.pt"
        return voice_pt

    def _ensure_pipeline(self) -> Any:
        if self._loaded:
            return self._pipeline
        import torch  # noqa: PLC0415
        from kokoro import KPipeline  # noqa: PLC0415
        from kokoro.model import KModel  # noqa: PLC0415

        target, probe_reason = _probe_torch_device(self._device)
        if self._device == "cuda" and target != "cuda":
            raise compute.ComputeUnavailableError(
                f"Kokoro 请求 CUDA，探针失败：{probe_reason or '未知原因'}"
            )
        with self._lock:
            if self._loaded:
                return self._pipeline
            config = self._model_dir / "config.json"
            weights = self._model_dir / "kokoro-v1_1-zh.pth"
            kmodel = KModel(config=str(config), model=str(weights))
            kmodel = kmodel.to(torch.device(target)).eval()
            pipeline = KPipeline(lang_code="z", model=kmodel)
            self._pipeline = pipeline
            self._actual_device = target
            if (
                self._device == "auto"
                and target == "cpu"
                and probe_reason
                and not probe_reason.startswith("torch.cuda.is_available")
            ):
                self._fallback_reason = probe_reason
            self._loaded = True
        return self._pipeline

    def compute(self) -> compute.ComputeReport | None:
        hello = self._hello
        if hello is not None:
            actual = "cuda" if str(hello.get("device") or "").startswith("cuda") else "cpu"
            fallback = bool(hello.get("fallback"))
            requested = str(hello.get("requested") or self._device)
            reason = str(hello.get("reason") or "")
        elif self._actual_device is not None:
            actual = self._actual_device
            fallback = bool(self._fallback_reason)
            requested = self._device
            reason = self._fallback_reason
        else:
            return None
        return compute.ComputeReport(
            component="tts.kokoro",
            requested=requested,
            resolved="cuda" if fallback or actual == "cuda" else "cpu",
            actual=actual,
            fallback=fallback,
            reason=reason,
        )
