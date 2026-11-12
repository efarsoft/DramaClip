"""SenseVoice 引擎（funasr）：含 VAD 与情绪标签。

自 transcriber.py 拆出（拆分专项）：依赖 common（设备解析、文本简化）
与 funasr（worker 桥）。_parse_sensevoice 输出合并为句级段（句级切分
由 W3 语义层细化）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.asr.common import (
    _CUDA_PROBLEM,
    _LOGGER,
    _adopt_loaded_device,
    _probe_cuda_op,
    _report_from_state,
    _resolve_torch_device,
)
from dramaclip.engines.analysis.asr.funasr import (
    _FunasrWorker,
    _inproc_funasr,
    _spawn_funasr_worker,
)
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.infra import compute


class SenseVoiceEngine:
    """SenseVoice（funasr，含 VAD 与情绪标签）。依赖较重（torch），按需安装。"""

    supports_diarization = False  # 情绪有通道，说话人没有：接了分离模型再改声明

    def __init__(
        self, model_dir: Path | None = None, *, models_dir: Path | None = None,
        device: str = "auto",
    ) -> None:
        resolved = model_dir if model_dir is not None else (
            models_dir / "asr" / "iic" / "SenseVoiceSmall" if models_dir is not None else None
        )
        self._model_dir = resolved
        self._requested = compute.normalize_requested(device)
        self._model: Any = None
        self._actual_device: str | None = None
        self._fallback_reason = ""

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

    def _ensure_model(self) -> Any:
        if self._model is None:
            auto_model = _inproc_funasr()
            if auto_model is None:
                self._model = self._venv_model()
                return self._model
            device = _resolve_torch_device(self._requested)
            if device.startswith("cuda"):
                problem = _probe_cuda_op(device)
                if problem:
                    if self._requested == "cuda":
                        raise compute.ComputeUnavailableError(
                            f"SenseVoice 请求 CUDA，但 CUDA 不可计算：{problem}"
                        )
                    _LOGGER.warning("SenseVoice CUDA 探针失败回退 CPU：%s", problem)
                    self._actual_device = "cpu"
                    self._fallback_reason = problem
                    device = "cpu"
            kwargs: dict[str, Any] = {"model": str(self._model_dir) if (
                self._model_dir is not None and self._model_dir.is_dir()
            ) else "iic/SenseVoiceSmall", "device": device}
            try:
                self._model = auto_model(**kwargs)
            except Exception as exc:  # noqa: BLE001 - CUDA 类失败按请求语义处理
                if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                    raise
                if self._requested == "cuda":
                    raise compute.ComputeUnavailableError(
                        f"SenseVoice 请求 CUDA，加载失败：{type(exc).__name__}: {exc}"
                    ) from exc
                _LOGGER.warning("SenseVoice CUDA 加载失败回退 CPU：%s", str(exc)[:160])
                self._actual_device = "cpu"
                self._fallback_reason = f"{type(exc).__name__}: {exc}"
                kwargs["device"] = "cpu"
                self._model = auto_model(**kwargs)
            else:
                self._actual_device, reason = _adopt_loaded_device(
                    "SenseVoice", self._requested, device, self._model
                )
                if reason:
                    self._fallback_reason = reason
        return self._model

    def compute(self) -> compute.ComputeReport | None:
        return _report_from_state(
            "asr.funasr", self._requested, self._actual_device, self._fallback_reason
        )

    def _venv_model(self) -> _FunasrWorker:
        """冻结/无 ml 态：本地智能运行环境里的 funasr worker（构造语义 worker 端镜像）。"""
        model_id = (
            str(self._model_dir)
            if self._model_dir is not None and self._model_dir.is_dir()
            else "iic/SenseVoiceSmall"
        )
        worker = _spawn_funasr_worker({
            "engine": "sensevoice",
            "model": model_id,
            "device": self._requested,
        })
        self._adopt_worker_hello(worker)
        _LOGGER.info("SenseVoice 走本地运行环境 worker（device=%s）", worker.device)
        return worker

    def _adopt_worker_hello(self, worker: _FunasrWorker) -> None:
        """worker 就绪行是运行态唯一证据：父进程曾把 device 读出来又丢了。"""
        hello = worker.ready
        self._actual_device = "cuda" if worker.device.startswith("cuda") else "cpu"
        self._fallback_reason = (
            str(hello.get("reason") or "") if hello.get("fallback") else ""
        )


def _parse_sensevoice(raw: list) -> list[AsrSegment]:  # type: ignore[type-arg]
    """funasr 输出 [{text, timestamp:[[beg_ms,end_ms], ...]}]（时间戳按字/词分组）。"""
    segments: list[AsrSegment] = []
    for item in raw:
        timestamps = item.get("timestamp") or []
        text_chunks = str(item.get("text", "")).split()
        if not timestamps:
            continue
        for cursor, span in enumerate(timestamps):
            # 解包守卫与 _parse_paraformer 同款：畸形行（≠2 元素）跳过而不是
            # ValueError: too many values to unpack 炸掉整集。
            if not isinstance(span, (list, tuple)) or len(span) != 2:
                continue
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
