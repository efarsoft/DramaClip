"""ASR 双引擎：faster-whisper（默认，已实测）/ SenseVoice（funasr，懒加载）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from dramaclip.engines.analysis.models import AsrSegment, WordSpan

_LOGGER = logging.getLogger(__name__)
_CUDA_PROBLEM = re.compile(r"cublas|cudnn|cudart|cuda|gpu", re.I)


def simplify(text: str) -> str:
    """繁→简归一（opencc，ml extras 懒加载；whisper 中文输出混繁体是已知行为）。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    return str(OpenCC("t2s").convert(text))

if TYPE_CHECKING:
    # 仅类型检查期导入（运行时懒加载；缺依赖时经 ignore_missing_imports 兜底）
    from faster_whisper import WhisperModel
    from funasr import AutoModel


class AsrEngine(Protocol):
    """ASR 引擎接口：输入 16k 单声道 wav，输出带时间戳的转写段。"""

    @property
    def name(self) -> str: ...

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]: ...


class FasterWhisperEngine:
    """faster-whisper（CTranslate2，CPU 可用，模型自动下载到 models_dir）。"""

    def __init__(
        self,
        model_size: str = "base",
        *,
        device: str = "auto",
        models_dir: Path | None = None,
        compute_type: str = "int8",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._models_dir = models_dir
        self._compute_type = compute_type
        self._model: WhisperModel | None = None

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
            if self._device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            _LOGGER.warning("CUDA 推理失败，自动回退 CPU：%s", exc)
            from faster_whisper import WhisperModel  # ml extras 懒加载

            cpu_model = self._create(WhisperModel, "cpu")
            self._model = cpu_model  # 缓存 CPU 模型，后续集不再重复走失败的 CUDA 路径
            return self._run(cpu_model, wav_path, language, hotwords)

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

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel  # ml extras 懒加载

            self._model = self._create(WhisperModel, self._device)
        return self._model

    def _create(self, cls: type[WhisperModel], device: str) -> WhisperModel:
        try:
            return cls(
                self._model_size,
                device=device,
                compute_type=self._compute_type,
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        except Exception as exc:  # noqa: BLE001 - CUDA 运行库问题统一按关键字识别
            if device != "cpu" and _CUDA_PROBLEM.search(str(exc)):
                # GPU 不可用（缺 cuBLAS/cuDNN、驱动不兼容等）：诚实降级 CPU 并留痕
                _LOGGER.warning("CUDA 初始化失败，自动回退 CPU：%s", exc)
                return cls(
                    self._model_size,
                    device="cpu",
                    compute_type=self._compute_type,
                    download_root=str(self._models_dir) if self._models_dir else None,
                )
            raise


class SenseVoiceEngine:
    """SenseVoice（funasr，含 VAD 与情绪标签）。依赖较重（torch），按需安装。"""

    def __init__(self, model_dir: Path | None = None, *, models_dir: Path | None = None) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "iic" / "SenseVoiceSmall" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._model: AutoModel | None = None

    @property
    def name(self) -> str:
        return "sensevoice"

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]:
        model = self._ensure_model()
        raw = model.generate(
            input=str(wav_path),
            cache={},
            language=language,
            output_timestamp=True,
        )
        return _parse_sensevoice(raw)

    def _ensure_model(self) -> AutoModel:
        if self._model is None:
            from funasr import AutoModel  # ml extras 懒加载

            if self._model_dir is not None and self._model_dir.is_dir():
                self._model = AutoModel(model=str(self._model_dir))
            else:
                self._model = AutoModel(model="iic/SenseVoiceSmall")
        return self._model


def _parse_sensevoice(raw: list) -> list[AsrSegment]:  # type: ignore[type-arg]
    """funasr 输出 [{text, timestamp:[[beg_ms,end_ms], ...]}]（时间戳按字/词分组）。"""
    segments: list[AsrSegment] = []
    for item in raw:
        timestamps = item.get("timestamp") or []
        text_chunks = str(item.get("text", "")).split()
        if not timestamps:
            continue
        for cursor, span in enumerate(timestamps):
            beg_ms, end_ms = span
            chunk = text_chunks[cursor] if cursor < len(text_chunks) else ""
            if chunk:
                segments.append(AsrSegment(start=beg_ms / 1000, end=end_ms / 1000, text=chunk))
    # 合并为句级（简单拼接为整段，句级切分由 W3 语义层细化）
    if segments:
        merged = AsrSegment(
            start=segments[0].start,
            end=segments[-1].end,
            text="".join(seg.text for seg in segments),
        )
        return [merged]
    return []
