"""ASR 引擎族公共层：Protocol、设备解析、文本简化、字级配对。

自 transcriber.py 拆出（拆分专项）：设备解析（CT2/torch 探测、模型落点裁决）
与文本工具（繁简归一、字级配对）是所有引擎共享的纯函数——不触模型、不触
DB。各引擎模块（whisper/sensevoice/paraformer/cloud）从本模块导入，
transcriber.py 做总 re-export。
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from dramaclip.engines.analysis.models import AsrSegment, WordSpan
from dramaclip.infra import compute

_LOGGER = logging.getLogger(__name__)
_CUDA_PROBLEM = re.compile(r"cublas|cudnn|cudart|cuda|gpu|int8 compute type", re.I)


def _ct2_cuda_available() -> bool:
    """CT2 能否看到 CUDA 设备；探不到一律按不可用，构造期再用真实失败兜底。"""
    try:
        import ctranslate2

        return bool(ctranslate2.get_cuda_device_count() > 0)
    except Exception:  # noqa: BLE001 - 坏装/未装是常态，不是转写失败
        return False


def _report_from_state(
    component: str, requested: str, actual: str | None, fallback_reason: str
) -> compute.ComputeReport | None:
    """引擎状态 → 回执：没真加载过就返回 None；回退时 resolved 记曾尝试的 cuda。"""
    if actual is None:
        return None
    resolved = "cpu" if requested == "cpu" or actual == "cpu" else "cuda"
    if fallback_reason:
        resolved = "cuda"
    if actual.startswith("xpu") or requested.startswith("xpu"):
        resolved = "xpu"
        if fallback_reason:
            resolved = "cpu"
    return compute.ComputeReport(
        component=component,
        requested=requested,
        resolved=resolved,
        actual=actual,
        fallback=bool(fallback_reason),
        reason=fallback_reason,
    )


def _probe_cuda_op(device: str) -> str:
    """真实小算子探针：返回空串=可算，否则失败原因。

    `torch.cuda.is_available()` 只说明编译/驱动可见，且 funasr 在不可见时会把
    device 静默改成 cpu——不先算一下，显式 cuda 就会被静默落 CPU。
    """
    try:
        import torch

        (torch.ones(4, device=device) * 2).sum().item()
    except Exception as exc:  # noqa: BLE001 - CPU-only torch/坏驱动都算不可算
        return f"{type(exc).__name__}: {exc}"
    return ""


def _model_device(model: Any) -> str | None:
    """模型真实落点：参数设备是物理证据，funasr 解析后的 kwargs.device 是退路。"""
    inner = getattr(model, "model", model)
    parameters = getattr(inner, "parameters", None)
    if callable(parameters):
        try:
            first = next(parameters())
        except (StopIteration, TypeError):
            first = None
        kind = getattr(getattr(first, "device", None), "type", None)
        if kind in {"cuda", "xpu", "cpu"}:
            return str(kind)
    resolved = getattr(model, "kwargs", None)
    if isinstance(resolved, dict):
        value = str(resolved.get("device") or "")
        if value:
            return "cuda" if value.startswith("cuda") else "cpu"
    return None


def _adopt_loaded_device(
    component: str, requested: str, wanted: str, model: Any
) -> tuple[str, str]:
    """加载成功后的落点裁决：返回 (actual, fallback_reason)，违诺直接抛。"""
    actual = _model_device(model)
    if actual is None:
        # 读不到落点就不许替显式 cuda 打包票；auto 至少探针已经证明可算。
        if requested == "cuda":
            raise compute.ComputeUnavailableError(
                f"{component} 请求 CUDA，但无法确认模型的实际落点"
            )
        actual = "cuda" if wanted.startswith("cuda") else "cpu"
    if requested == "cpu" and actual != "cpu":
        raise compute.ComputeUnavailableError(
            f"{component} 请求 CPU，funasr 把模型落在 {actual}"
        )
    if wanted.startswith("cuda") and actual != "cuda":
        if requested == "cuda":
            raise compute.ComputeUnavailableError(
                f"{component} 请求 CUDA，funasr 把模型落在 {actual}（静默回退）"
            )
        return "cpu", f"funasr 把模型落在 {actual}"
    return actual, ""


def _resolve_torch_device(device: str) -> str:
    """asr.device 设置值 → funasr AutoModel 的 device 实参（进程内路径专用）。

    auto = 交给 torch 探测（有可用 CUDA 即 cuda:0）；显式 cuda 同样解析成
    cuda:0；解析结果仍可能初始化失败（驱动/显存），由引擎的加载回退兜底。
    """
    if device in ("", "auto"):
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda:0"
            if torch.xpu.is_available():
                return "xpu"
            return "cpu"
        except Exception:  # noqa: BLE001 - torch 缺失/坏装一律 CPU（funasr 基线路径）
            return "cpu"
    if device == "cuda":
        return "cuda:0"
    return device


def simplify(text: str) -> str:
    """繁→简归一（opencc，ml extras 懒加载；whisper 中文输出混繁体是已知行为）。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    return str(OpenCC("t2s").convert(text))


if TYPE_CHECKING:
    # 仅类型检查期导入（运行时懒加载；缺依赖时经 ignore_missing_imports 兜底）
    pass


class AsrEngine(Protocol):
    """ASR 引擎接口：输入 16k 单声道 wav，输出带时间戳的转写段。"""

    @property
    def name(self) -> str: ...

    @property
    def supports_diarization(self) -> bool:
        """能否给转写段打说话人标签——`asr.diarization` 的认领方，做不到必须如实说。"""
        ...

    def transcribe(
        self, wav_path: Path, language: str = "zh", *, hotwords: str = ""
    ) -> list[AsrSegment]: ...

    def compute(self) -> compute.ComputeReport | None:
        """最近一次真实转写的算力回执；没跑过返回 None，不猜。"""
        ...


def _pair(
    chars: list[str], timestamps: list[list[float]]
) -> list[tuple[str, tuple[float, float]]]:
    """文本字与时间戳逐位配对；时间戳短时，剩余文本并入末个时间戳的跨度。"""
    if len(chars) <= len(timestamps):
        return [(char, (span[0], span[1])) for char, span in zip(chars, timestamps, strict=False)]
    if not timestamps:
        return []
    head = [(char, (span[0], span[1])) for char, span in zip(chars, timestamps, strict=False)]
    tail = "".join(chars[len(timestamps) - 1 :])
    last = timestamps[-1]
    return [*head[: len(timestamps) - 1], (tail, (last[0], last[1]))]


def _group_by_gap(
    words: list[WordSpan], gap_s: float
) -> list[list[WordSpan]]:
    """相邻字跨度间隙超阈值的切开；同一句内的字归一段。"""
    runs: list[list[WordSpan]] = []
    for word in words:
        if runs and word.start - runs[-1][-1].end <= gap_s:
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


_PUNC_FALSE_ALARM = "Missing punc_model, which is required by spk_model."


class _ExactMessageFilter(logging.Filter):
    """只放行不含指定原文的日志记录——精确到整句，不误伤同通道其他消息。"""

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def filter(self, record: logging.LogRecord) -> bool:
        return self._message not in record.getMessage()


@contextlib.contextmanager
def _punc_false_alarm_silenced() -> Iterator[None]:
    """vad_segment 模式下静音 funasr 的「缺标点模型」ERROR。

    库在 spk 路径上无差别检查 punc（`auto_model.py`：`elif raw_text is None` 分支
    对 vad_segment 模式也报 ERROR），但 vad_segment 只靠 VAD 区间拼句，本就不需要
    标点模型——这是我们主动选的配置，不是缺件。过滤器挂在 root（funasr 用模块级
    logging.error 直打 root），只在 generate 期间在场、消息精确匹配，别的 ERROR
    一条不放行。
    """
    filt = _ExactMessageFilter(_PUNC_FALSE_ALARM)
    root = logging.getLogger()
    root.addFilter(filt)
    try:
        yield
    finally:
        root.removeFilter(filt)
