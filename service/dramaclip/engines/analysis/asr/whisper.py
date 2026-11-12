"""faster-whisper 引擎：CTranslate2，CPU 可用，模型自动下载到 models_dir。

自 transcriber.py 拆出（拆分专项）：whisper 引擎独立成模块，
依赖 common（设备解析、文本简化、回执）——不触 funasr、不触 worker 桥。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from dramaclip.engines.analysis.asr.common import (
    _CUDA_PROBLEM,
    _ct2_cuda_available,
    _report_from_state,
    simplify,
)
from dramaclip.engines.analysis.models import AsrSegment, WordSpan
from dramaclip.infra import compute

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


class FasterWhisperEngine:
    """faster-whisper（CTranslate2，CPU 可用，模型自动下载到 models_dir）。"""

    supports_diarization = False  # 该引擎无说话人通道

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        models_dir: Path | None = None,
        compute_type: str = "auto",
    ) -> None:
        self._model_size = model_size
        self._requested = compute.normalize_requested(device)
        self._models_dir = models_dir
        self._compute_type = compute_type
        self._model: WhisperModel | None = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

    @property
    def name(self) -> str:
        return f"faster_whisper:{self._model_size}"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        try:
            return self._run(self._ensure_model(), wav_path, language, hotwords)
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            # cuBLAS/cuDNN 缺失往往在首次推理（惰性计算）时才暴露，构造期兜不住
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，推理失败：{type(exc).__name__}: {exc}"
                ) from exc
            if self._actual_device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            _LOGGER.warning("CUDA 推理失败，自动回退 CPU：%s", exc)
            from faster_whisper import WhisperModel  # ml extras 懒加载

            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            self._model = self._create(WhisperModel, "cpu")
            return self._run(self._model, wav_path, language, hotwords)

    def _run(
        self, model: WhisperModel, wav_path: Path, language: str, hotwords: str
    ) -> list[AsrSegment]:
        # word_timestamps：字级时间戳+概率，供 OCR 融合对齐（关闭则 words 为空）
        segments, _info = model.transcribe(
            str(wav_path),
            language=language,
            vad_filter=True,
            word_timestamps=True,
            hotwords=hotwords or None,
        )
        result: list[AsrSegment] = []
        for seg in segments:
            text = simplify(seg.text.strip())
            if not text:
                continue
            words = [
                WordSpan(
                    start=word.start,
                    end=word.end,
                    word=simplify(word.word.strip()),
                    probability=word.probability,
                )
                for word in (seg.words or [])
                if word.word.strip()
            ]
            result.append(AsrSegment(start=seg.start, end=seg.end, text=text, words=words))
        return result

    def _require_local_model(self) -> None:
        """本地模型预检：缺失给行动性引导，不在分析路径里静默联网下载。

        download_root 的 HF 缓存布局与 registry.detect_status 同一套
        （models--Systran--…/snapshots/<rev>/model.bin），引擎中心「下载」落的
        正是这一份。放行缺失的话，huggingface_hub 会自己去撞网络——国内网络
        下用户看到的是英文连接超时，那是「分析失败没细节」的又一种来源。
        """
        if self._models_dir is None:
            return
        short = self._model_size.removeprefix("faster-whisper-")
        for cache_dir in sorted(self._models_dir.glob(f"models--*faster-whisper-{short}")):
            for snapshot in sorted(cache_dir.glob("snapshots/*"), reverse=True):
                if (snapshot / "model.bin").is_file():
                    return
        raise ValueError(
            f"未找到本地 Whisper 模型（{self._model_size}）："
            "请到「引擎中心 → 语音识别 ASR」下载模型资产后再分析"
        )

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            self._require_local_model()
            from faster_whisper import WhisperModel  # ml extras 懒加载

            if self._requested == "cpu":
                target = "cpu"
            else:
                target = "cuda" if self._requested == "cuda" or _ct2_cuda_available() else "cpu"
            self._model = self._create(WhisperModel, target)
        return self._model

    def _create(self, cls: type[WhisperModel], device: str) -> WhisperModel:
        try:
            model = cls(
                self._model_size,
                device=device,
                compute_type=self._compute_for(device),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，初始化失败：{type(exc).__name__}: {exc}"
                ) from exc
            _LOGGER.warning("CUDA 初始化失败，自动回退 CPU：%s", exc)
            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            model = cls(
                self._model_size,
                device="cpu",
                compute_type=self._compute_for("cpu"),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        else:
            self._actual_device = "cuda" if device != "cpu" else "cpu"
        return model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.whisper", self._requested, self._actual_device, self._fallback_reason
        )

    def _compute_for(self, device: str) -> str:
        """int8 是 CPU 档：ctranslate2 的 CUDA 后端在没有高效 int8 GEMM 的卡上直接拒绝，
        硬塞的后果只是触发回退——GPU 在场却永远用不上。

        这层映射兜的是存量：老设置库里落盘的 int8、或调用方显式传入的 int8——设备不是
        cpu 时改交 auto，由库按实际解析到的设备挑最快可用档（CUDA→float16/float32，
        CPU→int8）。其余显式档位原样透传——业主自己选的，尊重。
        """
        if device != "cpu" and self._compute_type == "int8":
            return "auto"
        return self._compute_type


_LOGGER = logging.getLogger(__name__)
